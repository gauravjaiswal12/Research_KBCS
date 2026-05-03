# KBCS Project — Full Conversation Context Handoff

> **Purpose:** This document captures the full context of our conversation so that a new session can pick up exactly where we left off.
> **Date:** March 22, 2026

---

## 1. Project Overview

**Project:** KBCS (Karma-Based Congestion Scoring) — a P4 Data Plane AQM algorithm for TCP fairness.
**Baseline:** P4air — a state-of-the-art CCA-aware AQM from a published IEEE paper.
**Goal:** Prove KBCS can beat P4air in fairness and throughput, and publish at an IEEE conference.
**Teacher:** Actively involved, plans to co-author the paper.

---

## 2. Environment Setup

- **VM:** Official P4 Developer VM (`.ova`) running Ubuntu Linux in VirtualBox.
- **Pre-installed tools:** `p4c` compiler, `simple_switch` (BMv2), Mininet, P4Runtime.
- **No external controller** (like Ryu or ONOS). We use P4Runtime directly via Python scripts.
- **SSH Access:** `ssh p4@localhost -p 2222` (password: `p4`)
- **Windows Host:** Used for plotting graphs (`matplotlib`) and file editing.

---

## 3. P4air Baseline — Completed ✅

### What We Built
- `p4air.p4` / `ingress.p4`: Full P4air implementation (Fingerprinting, Reallocation, Apply Actions).
- `no_aqm.p4`: Simple FIFO forwarding baseline.
- `diff_queues.p4`: Hash-based 8-queue baseline (CRC32 on 5-tuple).
- `run_multiple.py`: Automation script for N-iteration experiments.
- `plot_results_16flows.py`: Graph generation for 16-flow results.

### Critical Bugs Fixed
1. **TCP Checksum Bug:** Removed broken `update_checksum_with_payload` from `parser.p4` (was causing 0 Mbps).
2. **BDP Tuning:** Changed `RTT >> 4` to `RTT >> 10`, min BDP from 2 to 10 (for BMv2 jitter).
3. **State Cleanup:** Added `mn -c`, `killall simple_switch`, `sleep` between experiment runs.

### Final Results (16 Flows, 5 Iterations)
| Configuration | Avg JFI | Avg Total Mbps |
|---------------|---------|----------------|
| No AQM (FIFO) | 0.9123 (±0.03) | 10.23 (±0.08) |
| Diff Queues (Hash) | 0.9390 (±0.02) | 10.35 (±0.15) |
| **P4air (CCA Aware)** | **0.9483 (±0.02)** | **11.02 (±0.07)** |

### Key Findings
- **4-flow test:** P4air underperforms due to BMv2 software jitter and recirculation penalty.
- **16-flow test:** P4air wins because its intelligent CCA classification outperforms blind hashing at scale.
- **This proves P4air is hardware-dependent and brittle → justifies KBCS.**

---

## 4. KBCS Current Prototype

**Location:** `e:\Research Methodology\Project-Implementation\kbcs\`

Current features:
- 5-tuple flow hashing (CRC32)
- Decayed byte tracking per flow
- Bounded karma update (increment/decrement per packet)
- Color mapping: GREEN / YELLOW / RED
- RED-flow drop behavior

---

## 5. KBCS Enhancement Roadmap — The Master Plan

**Full roadmap file:** `e:\Research Methodology\Project-Implementation\KBCS_Enhancement_Roadmap.md`

### Phase 1 (Quick Wins): E1 ECN, E2 Congestion Penalty, E3 Graduated Enforcement, E8 Idle Recovery
### Phase 2 (Core Novelty): E4 Adaptive Threshold, E5 Stochastic Drop, E6 Karma Momentum
### Phase 3 (Observability): E7 Slow-Start, E9 INT Telemetry, E10 Clone/Mirror, E11 Grafana, E12 Animated Graphs, E13 Architecture Diagram, E14 Screen Recording
### Phase 4 (IEEE Pillars): Pillar A Multi-Switch Propagation, Pillar B Dynamic Queue Weights, Pillar C RL Hybrid Controller

**Total estimated time: ~25.5 hours (4 focused weekends)**

---

## 6. Key Technical Decisions Explained

### Why Diff Queues is compared against P4air (Ablation Study)
- Diff Queues uses hash to blindly assign flows to queues.
- P4air uses hash only as a flow ID, then runs complex fingerprinting to intelligently assign queues.
- Comparing them proves P4air's complexity is justified at scale.

### Why we ran 5 iterations (Statistical Significance)
- Emulation has random CPU jitter and hash collision variance.
- Averaging 5 runs + calculating standard deviation eliminates lucky/unlucky runs.

### How P4air determines transmission rate
- Calculates RTT from SYN timestamps, estimates BDP via bit-shifting (`RTT >> 10`).
- Counts packets per RTT interval. If packets > BDP, flow is too aggressive → punished.

### How KBCS determines transmission rate
- Uses Karma tokens. Each packet costs Karma. If Karma drops below threshold → punished.
- No RTT calculation needed → hardware-agnostic and jitter-resistant.

### Why no Ryu/ONOS controller
- P4 is a Data Plane language; intelligence lives in the switch, not a controller.
- P4Runtime API (already in VM) replaces Ryu/ONOS for pushing table entries.
- A lightweight Python P4Runtime controller can be added in <60 minutes if needed.

### The Recirculate function
- BMv2 has no hardware Traffic Manager, so packet delay is emulated via `recirculate()`.
- Packet re-enters the switch pipeline a second time, simulating a delay penalty.
- This cuts BMv2 throughput in half (explaining P4air's 5.65 Mbps in 4-flow tests).

### How 16 flows are generated from 4 CCAs
- A "flow" is a unique 5-tuple connection, not a unique CCA.
- 16 flows = 4 Cubic + 4 BBR + 4 Vegas + 4 Illinois (each with different IP/port pairs).

---

## 7. Important File Locations

| File | Location | Purpose |
|------|----------|---------|
| P4air Implementation | `~/Baseline/p4air/p4src/` (on VM) | The P4 switch code |
| No AQM Baseline | `~/Baseline/p4air/p4src/no_aqm.p4` | FIFO baseline |
| Diff Queues Baseline | `~/Baseline/p4air/p4src/diff_queues.p4` | Hash baseline |
| Automation Script | `~/Baseline/p4air/experiments/run_multiple.py` | Multi-iteration runner |
| KBCS Code | `e:\...\kbcs\p4src\` | KBCS P4 implementation |
| Enhancement Roadmap | `e:\...\KBCS_Enhancement_Roadmap.md` | Full implementation plan |
| Final Baseline Report | Brain artifacts: `p4air_final_report.md` | Teacher-ready report |
| 16-Flow Graph | Brain artifacts: `comparison_graph_16_flows.png` | Results visualization |

---

## 8. Teacher Interaction Notes

- Teacher wants to co-author the IEEE paper.
- Teacher was confused by terminal-only output → we are adding Grafana dashboard (E11).
- Teacher asked about using Ryu controller → explained P4Runtime replaces it.
- Teacher asked about RL for threshold tuning → added as Pillar C enhancement.
- Teacher asked about implementation issues → we documented 3 major bugs and fixes.
- Other groups using Docker + Grafana look more visually impressive → we are adding E11-E14.

---

## 9. Next Steps (Where to Resume)

1. **Start implementing KBCS enhancements** following the roadmap in `KBCS_Enhancement_Roadmap.md`.
2. Begin with Phase 1 (E1 ECN → E2 → E3 → E8) — estimated 2.25 hours.
3. Run tests after Phase 1 to compare against P4air baseline.
4. Continue through Phases 2-4 as per the schedule.
