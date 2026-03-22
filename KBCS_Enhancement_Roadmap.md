# KBCS Enhancement Roadmap (Final — IEEE Publication Ready)

This document is the single source of truth for all KBCS enhancements. It consolidates the 11 original enhancements + 3 architectural pillars into a unified, phase-wise implementation plan with concrete P4/Python code guidance for each item.

---

## 1. Goals

- **Beat P4air baseline** in both Jain's Fairness Index (JFI) and Total Throughput across 4-flow and 16-flow tests.
- **Maximize novelty** by combining mechanisms not jointly explored in prior P4 AQM papers (Karma + RL + ECN + Multi-Switch).
- **Keep implementation feasible** in BMv2 + Mininet on the P4 VM.

## 2. Current KBCS Prototype (Baseline)

What we already have working:
- 5-tuple flow hashing (CRC32)
- Decayed byte tracking per flow
- Bounded karma update (increment/decrement per packet)
- Color mapping: GREEN (karma > threshold_high) / YELLOW (in between) / RED (karma < threshold_low)
- RED-flow drop behavior
- Automated testing suite (`run_multiple.py`, `plot_results.py`)

All enhancements below are **incremental** on top of this base.

---

## 3. Enhancement Catalog

### 🟢 PHASE 1 — Quick Wins (Low Complexity, High Impact)

These three enhancements are the easiest to implement and will immediately improve your graphs.

---

#### E1. ECN Marking for YELLOW Flows
**What:** Instead of only forwarding or dropping, YELLOW flows get an ECN congestion marking (`CE`) as an early warning signal to the sender.

**Why it beats P4air:** P4air either drops packets or recirculates them (crashing throughput to 5 Mbps). ECN tells the sender to slow down *without* losing a single packet, keeping throughput near 10 Mbps.

**How to implement (P4 code):**
```p4
// In egress control block, after reading karma_color for this flow:
if (meta.karma_color == COLOR_YELLOW) {
    // Set ECN Congestion Experienced (CE) bits
    hdr.ipv4.ecn = 2w0x3;  // CE = binary 11
}
```

**Files to modify:** `egress.p4`
**Estimated time:** 30 minutes

---

#### E2. Congestion-Proportional Karma Penalty
**What:** Replace the fixed penalty (e.g., always `-5`) with a penalty that scales based on the current queue depth (`enq_qdepth`).

**Why it beats P4air:** P4air uses fixed BDP thresholds that break under jitter. Our penalty automatically gets harsher when the queue is full and gentler when it's empty.

**How to implement (P4 code):**
```p4
// In ingress, when calculating karma penalty:
bit<32> queue_depth;
queue_depth = (bit<32>)standard_metadata.enq_qdepth;

bit<32> penalty;
if (queue_depth > 200) {
    penalty = 15;   // Severe congestion: harsh penalty
} else if (queue_depth > 100) {
    penalty = 10;   // Moderate congestion
} else if (queue_depth > 50) {
    penalty = 5;    // Mild congestion
} else {
    penalty = 2;    // Almost empty: gentle penalty
}
// karma = karma - penalty;
```

**Files to modify:** `ingress.p4`
**Estimated time:** 30 minutes

---

#### E3. Graduated Enforcement Chain (ECN → Window Reduce → Drop)
**What:** Instead of a binary forward/drop, use a 3-level punishment pipeline:
- **GREEN:** Normal forward.
- **YELLOW:** Apply ECN mark + optionally halve TCP receive window on ACK packets.
- **RED:** Drop the packet.

**Why it beats P4air:** P4air only has two modes: "forward" or "destroy." Our graduated chain smoothly throttles aggressive flows without crashing their TCP connection.

**How to implement (P4 code):**
```p4
if (meta.karma_color == COLOR_GREEN) {
    // Forward normally
} else if (meta.karma_color == COLOR_YELLOW) {
    hdr.ipv4.ecn = 2w0x3;  // ECN mark
    // Optional: halve TCP window on ACK packets
    if ((hdr.tcp.ctrl & 6w0x10) != 0) {  // ACK flag
        hdr.tcp.window = hdr.tcp.window >> 1;
    }
} else {  // RED
    drop();
}
```

**Files to modify:** `ingress.p4` or `egress.p4`
**Estimated time:** 45 minutes

---

#### E8. Idle-Flow Karma Recovery
**What:** If a flow has not sent any packets for a long time, gradually restore its Karma back toward a neutral/positive state.

**Why it helps:** Prevents old penalties from permanently harming flows that paused and restarted. A flow that was aggressive 30 seconds ago shouldn't still be punished.

**How to implement (P4 code):**
```p4
// Read last-seen timestamp for this flow
bit<48> last_seen;
reg_last_seen.read(last_seen, (bit<32>)meta.flow_id);
bit<48> idle_time = standard_metadata.ingress_global_timestamp - last_seen;

// If idle for more than 2 RTTs, recover karma
if (idle_time > (current_rtt << 1)) {
    if (karma < KARMA_MAX) {
        karma = karma + 5;  // Gradual recovery
    }
}
reg_last_seen.write((bit<32>)meta.flow_id, standard_metadata.ingress_global_timestamp);
```

**Files to modify:** `ingress.p4`
**Estimated time:** 30 minutes

---

### 🟡 PHASE 2 — Core Novelty (Medium Complexity, Highest Publication Value)

These three enhancements form the technical heart of your IEEE paper. They are the hardest to implement but provide the most unique contribution.

---

#### E4. Active-Flow-Count Adaptive Threshold
**What:** Scale the Karma aggressiveness threshold by the current number of active flows, instead of using one fixed number.

**Why it beats P4air:** P4air uses a single BDP number for all traffic. KBCS dynamically adjusts: with 4 flows, the threshold is relaxed; with 64 flows, it becomes strict.

**How to implement (P4 code):**
```p4
// Maintain a global active flow counter
bit<32> active_flows;
reg_active_flows.read(active_flows, 0);

// Scale the karma threshold inversely with flow count
bit<32> dynamic_threshold;
if (active_flows <= 4) {
    dynamic_threshold = 1000;  // Relaxed
} else if (active_flows <= 16) {
    dynamic_threshold = 500;   // Moderate
} else {
    dynamic_threshold = 200;   // Strict
}
// Use dynamic_threshold instead of fixed KARMA_THRESHOLD
```

**Files to modify:** `ingress.p4`
**Estimated time:** 1 hour

---

#### E5. Stochastic Fair Drop (Karma-Weighted Probability)
**What:** For RED flows, instead of dropping 100% of packets, apply a *probabilistic* drop based on how negative the Karma is. A flow with Karma = -5 gets a 30% drop rate. A flow with Karma = -50 gets a 90% drop rate.

**Why it beats P4air:** P4air drops all packets from aggressive flows deterministically, which causes "TCP Synchronized Collapse" (all flows crash at the exact same time and restart together, creating oscillations). Probabilistic dropping smooths this out.

**How to implement (P4 code):**
```p4
// Generate pseudo-random number from packet fields
bit<16> rand_val;
hash(rand_val, HashAlgorithm.crc16,
     (bit<16>)0, {hdr.ipv4.identification, hdr.tcp.seq_no},
     (bit<16>)100);  // Random value 0-99

// Drop probability scales with how negative karma is
bit<16> drop_threshold;
if (karma < -40) {
    drop_threshold = 90;  // 90% drop rate
} else if (karma < -20) {
    drop_threshold = 60;  // 60% drop rate
} else {
    drop_threshold = 30;  // 30% drop rate
}

if (rand_val < drop_threshold) {
    drop();
}
```

**Files to modify:** `ingress.p4`
**Estimated time:** 1 hour

---

#### E6. Karma Momentum (Velocity-Aware Control)
**What:** Track not just the current Karma score, but the *rate of change* (`delta_karma`). If a flow's Karma is dropping rapidly (velocity is highly negative), react faster. If it's recovering, ease off the punishment.

**Why it beats P4air:** P4air classifies flows once and rarely changes. KBCS Momentum detects behavioral shifts in real time.

**How to implement (P4 code):**
```p4
// Store previous karma value
bit<32> prev_karma;
reg_prev_karma.read(prev_karma, (bit<32>)meta.flow_id);

// Calculate delta (momentum)
bit<32> delta = karma - prev_karma;  // Negative = getting worse

// If momentum is strongly negative, apply extra penalty
if (delta < -10) {
    karma = karma - 5;  // Extra punishment for rapidly degrading flows
}

// Save current karma for next comparison
reg_prev_karma.write((bit<32>)meta.flow_id, karma);
```

**Files to modify:** `ingress.p4`
**Estimated time:** 45 minutes

---

### 🔴 PHASE 3 — Robustness & Observability (Edge Cases + Beautiful Graphs)

These enhancements handle corner cases and produce the stunning evaluation graphs that IEEE reviewers expect.

---

#### E7. Slow-Start Leniency (Flow-Phase Awareness)
**What:** Detect early rapid growth likely due to TCP slow start and apply temporary immunity to avoid misclassifying startup bursts as persistent aggression.

**How to implement:**
```p4
// For new flows (packet count < 20), don't penalize karma
if (num_pkts < 20) {
    // Skip karma penalty — this is likely TCP slow start
    // Still track bytes, but don't punish yet
} else {
    // Normal karma calculation
}
```

**Files to modify:** `ingress.p4`
**Estimated time:** 30 minutes

---

#### E9. INT Karma Telemetry Stamping
**What:** Attach the flow's karma score, color, and queue ID into a custom P4 header field for observability and downstream use.

**How to implement:**
```p4
// Define custom telemetry header in headers.p4
header kbcs_telemetry_t {
    bit<8>  karma_score;
    bit<2>  color;       // GREEN=0, YELLOW=1, RED=2
    bit<3>  queue_id;
    bit<3>  padding;
}

// In egress, stamp the telemetry
hdr.kbcs_telemetry.setValid();
hdr.kbcs_telemetry.karma_score = (bit<8>)karma;
hdr.kbcs_telemetry.color = meta.karma_color;
hdr.kbcs_telemetry.queue_id = standard_metadata.egress_port[2:0];
```

**Files to modify:** `headers.p4`, `parser.p4`, `egress.p4`
**Estimated time:** 1 hour

---

#### E10. Karma Transition Telemetry Export (Clone/Mirror)
**What:** When a flow changes color (e.g., GREEN → YELLOW or YELLOW → RED), clone the packet to a monitoring port for external logging. This produces beautiful timeline graphs for your paper.

**How to implement:**
```p4
// When color changes, clone the packet to a mirror port
if (meta.karma_color != meta.prev_color) {
    clone3(CloneType.I2E, MIRROR_SESSION_ID, meta);
}
```

**Files to modify:** `ingress.p4`, plus configure mirror session in `runtime.json`
**Estimated time:** 1 hour

---

#### E11. Real-Time Grafana Dashboard (InfluxDB + P4Runtime)
**What:** A live, real-time visual dashboard (via Grafana) showing Karma scores dropping/recovering, total packet loss, and queue depths updating every 1 second.

**Why it helps:** This is specifically for live demoing to your teacher. Live visualization of a P4 switch enforcing fairness dynamically looks incredibly professional and secures high grades.

**How to implement:**
1. Write a Python daemon `metrics_exporter.py` that reads BMv2 registers via P4Runtime every 1 second.
2. The Python script pushes those values via HTTP POST to a local **InfluxDB** database.
3. Install **Grafana**, connect it to InfluxDB, and build 3-4 gauges/graphs (JFI, Throughput, Karma State).

**Dependencies:** `influxdb` and `grafana-server` installed on the VM or the Windows host.
**Files to modify:** new `metrics_exporter.py`
**Estimated time:** 1.5 hours

---

#### E12. Animated Matplotlib Graphs (Karma Timelines)
**What:** Instead of static bar charts, generate animated `.gif` or `.mp4` visualizations showing how per-flow Karma scores rise and fall over the duration of the experiment, with color transitions (GREEN → YELLOW → RED) visible frame by frame.

**Why it helps:** Static graphs show the final result. Animated graphs show the **journey** — your teacher can visually watch Cubic's Karma crash while BBR's stays healthy. This is extremely powerful for presentations and the IEEE paper.

**How to implement:**
```python
# In plot_animated_karma.py
import matplotlib.animation as animation

def animate(frame):
    ax.clear()
    for flow_id in flows:
        ax.plot(time[:frame], karma_scores[flow_id][:frame], label=f"Flow {flow_id}")
    ax.set_ylabel("Karma Score")
    ax.set_xlabel("Time (seconds)")
    ax.legend()

ani = animation.FuncAnimation(fig, animate, frames=len(time), interval=100)
ani.save("karma_animation.gif", writer="pillow")
```

**Dependencies:** `matplotlib`, `pillow` (both available on Windows host)
**Files to create:** new `experiments/plot_animated_karma.py`
**Estimated time:** 45 minutes

---

#### E13. Professional Architecture Diagram
**What:** A clean, color-coded network architecture diagram showing the full KBCS system: the 16 hosts, the P4 switch with internal Karma pipeline, the RL Controller, the Grafana dashboard, and the InfluxDB database — all connected with labeled arrows.

**Why it helps:** Every IEEE paper needs a "System Architecture" figure. Every teacher presentation needs a visual topology. This single image replaces 10 minutes of verbal explanation.

**How to implement:**
- Option A: Use the AI image generation tool to create a polished diagram.
- Option B: Use draw.io (free) or PowerPoint to manually draw it.
- The diagram should show: `Hosts (h1-h16)` → `P4 Switch (KBCS Engine)` → `RL Controller` → `Grafana Dashboard`.

**Files to create:** `Architecture_KBCS_Enhanced.png`
**Estimated time:** 30 minutes

---

#### E14. Live Demo Screen Recording
**What:** Record a 2-minute screen capture video showing the full KBCS system running live: the terminal running the experiment, the Grafana dashboard updating in real-time, and the RL controller adjusting thresholds — all visible simultaneously on screen.

**Why it helps:** If your teacher cannot attend a live demo or wants to review later, a polished video recording is the ultimate proof of a working system. It can also be submitted as supplementary material with the IEEE paper.

**How to implement:**
1. Open 3 windows side-by-side: Terminal (experiment running), Grafana (live dashboard), RL Controller (Python logs).
2. Use OBS Studio (free) or Windows Game Bar (`Win+G`) to record the screen.
3. Trim to 2 minutes and export as `.mp4`.

**Dependencies:** OBS Studio or Windows Game Bar
**Files to create:** `demo_recording.mp4`
**Estimated time:** 15 minutes (after Grafana is set up)

---

### 🔵 PHASE 4 — The "Three Pillars" (IEEE Publication Showstoppers)

These are the architectural innovations that transform KBCS from a "homework project" into a publishable, closed-loop, AI-driven network system.

---

#### Pillar A. Multi-Switch Karma Propagation
**What:** Embed the flow's Karma score directly into a custom P4 header so downstream switches instantly know the flow's reputation without recalculating it.

**How to implement:**
1. Define `header kbcs_metadata_t { bit<8> karma_score; }` in `headers.p4`.
2. In egress of Switch 1: `hdr.kbcs_metadata.setValid(); hdr.kbcs_metadata.karma_score = (bit<8>)karma;`
3. In parser of Switch 2: extract `kbcs_metadata` and use it as the initial Karma seed.
4. For testing: create a 2-switch linear topology in `topology.py`.

**Files to modify:** `headers.p4`, `parser.p4`, `egress.p4`, `topology.py`
**Estimated time:** 2-3 hours

---

#### Pillar B. Dynamic Queue Weights from Aggregate Karma (E11)
**What:** Periodically compute class-level behavior statistics (average karma per color class) and adapt queue scheduling weights from a Python control plane script.

**How to implement:**
1. P4 switch stores aggregate karma sums in registers (one per color class).
2. Python controller reads these registers every 2 seconds via P4Runtime.
3. Controller calculates optimal queue weights and writes them back to P4 registers.
4. The P4 egress block reads the weight registers to decide priority scheduling.

**Files to modify:** `ingress.p4`, `egress.p4`, new `controller.py`
**Estimated time:** 3-4 hours

---

#### Pillar C. Reinforcement Learning (RL) Hybrid Architecture
**What:** A Python-based Control Plane agent using RL (PPO or DQN) to dynamically find the optimal Karma penalty weights, replacing all manual guessing.

**How to implement:**
1. **State:** Python reads queue depths, active flow count, and current JFI from P4 registers every 1 second.
2. **Action:** The RL model outputs new values for `karma_penalty`, `karma_threshold_red`, `karma_threshold_yellow`.
3. **Reward:** `reward = current_JFI * 100 + total_throughput_mbps`. Higher reward = fairer + faster.
4. **Push:** Python writes the new values to P4 registers via `p4runtime_lib` gRPC.
5. **P4 reads:** The ingress block reads these registers at the start of every packet to get the latest AI-tuned thresholds.

**Dependencies:** `pip install torch gymnasium` on the VM or on an external machine.

**Files to modify:** new `rl_controller.py`, `ingress.p4` (add register reads for dynamic thresholds)
**Estimated time:** 4-6 hours

---

## 4. Implementation Order (Step-by-Step)

| Step | Enhancement | Est. Time | Cumulative |
|------|-------------|-----------|------------|
| 1 | E1 — ECN Marking | 30 min | 30 min |
| 2 | E2 — Congestion-Proportional Penalty | 30 min | 1 hr |
| 3 | E3 — Graduated Enforcement Chain | 45 min | 1.75 hrs |
| 4 | E8 — Idle-Flow Recovery | 30 min | 2.25 hrs |
| 5 | **🧪 RUN TESTS — Compare vs P4air** | 15 min | 2.5 hrs |
| 6 | E4 — Active-Flow Adaptive Threshold | 1 hr | 3.5 hrs |
| 7 | E5 — Stochastic Fair Drop | 1 hr | 4.5 hrs |
| 8 | E6 — Karma Momentum | 45 min | 5.25 hrs |
| 9 | **🧪 RUN TESTS — Compare vs P4air (expect to beat it here)** | 15 min | 5.5 hrs |
| 10 | E7 — Slow-Start Leniency | 30 min | 6 hrs |
| 11 | E9 — INT Telemetry | 1 hr | 7 hrs |
| 12 | E10 — Clone/Mirror Export | 1 hr | 8 hrs |
| 13 | E11 — Real-Time Grafana Dashboard | 1.5 hrs | 9.5 hrs |
| 14 | E12 — Animated Matplotlib Graphs | 45 min | 10.25 hrs |
| 15 | E13 — Professional Architecture Diagram | 30 min | 10.75 hrs |
| 16 | **🧪 RUN TESTS — Full ablation study** | 30 min | 11.25 hrs |
| 17 | Pillar A — Multi-Switch Propagation | 3 hrs | 14.25 hrs |
| 18 | Pillar B — Dynamic Queue Weights | 4 hrs | 18.25 hrs |
| 19 | Pillar C — RL Controller | 6 hrs | 24.25 hrs |
| 20 | **🧪 FINAL TESTS — Full system, 30 iterations, graphs** | 1 hr | 25.25 hrs |
| 21 | E14 — Live Demo Screen Recording | 15 min | 25.5 hrs |

**Total estimated engineering time: ~25.5 hours (4 focused weekends)**

---

## 5. Priority Table

| ID | Enhancement | Impact | Novelty | Complexity | Priority |
|----|-------------|--------|---------|------------|----------|
| E1 | ECN for YELLOW | High | Medium | Low | 🔴 Critical |
| E2 | Congestion-proportional penalty | High | High | Low | 🔴 Critical |
| E3 | Graduated enforcement | High | Medium-High | Low-Med | 🔴 Critical |
| E4 | Flow-count adaptive threshold | High | High | Medium | 🔴 Critical |
| E5 | Stochastic fair drop | High | High | Medium | 🔴 Critical |
| E6 | Karma momentum | Medium-High | High | Medium | 🔴 Critical |
| E7 | Slow-start leniency | Medium | High | Medium | 🟡 Important |
| E8 | Idle recovery | Medium | Medium | Low | 🟡 Important |
| E9 | INT karma telemetry | Medium | High | Medium | 🟡 Important |
| E10 | Transition telemetry export | Medium | Low-Med | Low | 🟡 Important |
| E11 | Real-time Grafana Dashboard | High (Demo Impact) | Low | Medium | 🟡 Important |
| E12 | Animated Matplotlib Graphs | High (Presentation) | Low | Low | 🟡 Important |
| E13 | Professional Architecture Diagram | High (Paper + Demo) | Low | Low | 🟡 Important |
| E14 | Live Demo Screen Recording | Very High (Demo) | Low | Low | 🟡 Important |
| Pillar A | Multi-Switch Propagation | High | Very High | Medium | 🔴 Critical |
| Pillar B | Dynamic Queue Weights | Medium-High | High | Med-High | 🟡 Important |
| Pillar C | RL Hybrid Controller | Very High | Very High | High | 🔴 Critical |

---

## 6. Expected Final Results (After All Enhancements)

With all enhancements implemented, the expected performance comparison:

| Metric | No AQM | Diff Queues | P4air | KBCS (Enhanced) |
|--------|--------|-------------|-------|-----------------|
| JFI (4 flows) | ~0.86 | ~0.81 | ~0.77 | **~0.95+** |
| JFI (16 flows) | ~0.91 | ~0.93 | ~0.94 | **~0.97+** |
| Total Mbps | ~10.2 | ~10.3 | ~5.6 (4-flow) / 11.0 (16-flow) | **~10.5+** |
| Throughput Stability (±std) | ±0.08 | ±0.15 | ±0.07 | **±0.03** |

**Key advantage over P4air:** KBCS maintains high throughput (no recirculation penalty) while achieving equal or better fairness, and the RL controller eliminates P4air's fatal weakness of hardcoded thresholds.
