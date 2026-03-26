# KBCS Project — Phase 3 Completed Understanding

> **Document Purpose:** Comprehensive technical reference documenting everything implemented in the KBCS (Karma-Based Congestion Shaping) project through Phase 3b completion.

---

## 1. Project Overview

**KBCS** is a P4-programmable data-plane solution for **TCP fairness enforcement**. It runs on BMv2 `simple_switch` inside a Mininet virtual network. The core idea: assign each flow a **Karma Score** (0–100) that degrades when a flow sends more than its fair share of bandwidth, and recovers when it backs off. Flows with low karma are penalized (queue demotion → packet drops), while well-behaved flows are rewarded.

**Problem Solved:** When aggressive TCP variants like **CUBIC** compete with pacing-based variants like **BBR** on a shared bottleneck link, CUBIC dominates by filling the queue. KBCS detects this unfairness at line rate and shapes CUBIC's traffic to protect BBR.

---

## 2. Network Topology

```
     ┌──────┐  100 Mbps  ┌──────────┐  10 Mbps, 5ms  ┌──────┐
     │  h1  │────Port 1──│          │────Port 3───────│  h3  │
     │CUBIC │             │  s1 (P4) │   (bottleneck)  │Server│
     └──────┘             │          │                 └──────┘
     ┌──────┐  100 Mbps  │          │
     │  h2  │────Port 2──│          │
     │ BBR  │             │          │
     └──────┘             │          │  1 Gbps
     ┌──────────┐         │          │
     │collector │──Port 4─│          │
     │(tcpdump) │         └──────────┘
     └──────────┘
```

| Host | IP | MAC | Role |
|---|---|---|---|
| h1 | 10.0.0.1 | 00:00:00:00:01:01 | CUBIC sender → h3 |
| h2 | 10.0.0.2 | 00:00:00:00:02:02 | BBR sender → h3 |
| h3 | 10.0.0.3 | 00:00:00:00:03:03 | iperf3 server (2 instances: port 5201, 5202) |
| collector | 10.0.0.4 | 00:00:00:00:04:04 | INT telemetry receiver (tcpdump) |

- **Bottleneck:** Port 3 link is 10 Mbps with 5ms delay and max queue size 200.
- **Priority Queues:** `simple_switch` runs with `--priority-queues 3` (GREEN=0, YELLOW=1, RED=2).

---

## 3. P4 Data Plane Architecture

### 3.1 Headers (`headers.p4`)

| Header | Size | Purpose |
|---|---|---|
| `ethernet_t` | 14B | Standard L2 |
| `ipv4_t` | 20B | Standard L3 |
| `tcp_t` | 20B | Standard L4 (used for SYN/FIN/RST guard) |
| `kbcs_telemetry_t` | 5B (40 bits) | Custom INT header for telemetry export |

**Telemetry Header Layout (40 bits):**
```
| karma_score (8b) | color (2b) | queue_id (3b) | enq_qdepth (19b) | is_dropped (1b) | padding (7b) |
```

**Metadata (`local_metadata_t`):**
- `flow_id` — Deterministic: 1=CUBIC(h1), 2=BBR(h2), 3=h3
- `flow_bytes` — Bytes accumulated in current window
- `karma_score` — Current karma (0–100)
- `flow_color` — GREEN(0), YELLOW(1), RED(2)
- `should_clone_e2e` — Flag for Egress-to-Egress cloning
- `saved_qdepth` — Preserves actual egress queue depth for E2E clones

### 3.2 Parser (`parser.p4`)

Standard Ethernet → IPv4 → TCP cascade. EtherType `0x0800` transitions to IPv4; protocol `6` (TCP) transitions to TCP.

### 3.3 Ingress Pipeline (`ingress.p4`)

The Karma Engine runs **only** on TCP DATA/ACK packets (guard skips SYN/FIN/RST):

#### Tunable Constants
| Constant | Value | Meaning |
|---|---|---|
| `KARMA_INIT` | 100 | Starting karma for new flows |
| `WINDOW_USEC` | 5000 (5ms) | Byte-rate measurement window |
| `FAIR_BYTES` | 3125 | Fair share per window (10Mbps / 2 flows / 200 windows/sec) |
| `HIGH_THRESHOLD` | 80 | Karma > 80 → GREEN |
| `LOW_THRESHOLD` | 40 | Karma > 40 → YELLOW, else RED |
| `PEN3/PEN2/PEN1/PEN0` | 60/30/10/2 | Proportional penalty tiers |

#### Processing Steps (per packet):
1. **Flow ID Assignment** — srcAddr → flow_id (1=CUBIC, 2=BBR, 3=other)
2. **State Read** — Read `reg_bytes`, `reg_karma`, `reg_wstart`, `reg_last_seen`, `reg_total_pkts`, `reg_prev_karma`
3. **E8: Idle-Flow Karma Recovery** — If idle > 500ms, recover karma by +5
4. **Window Logic** — If window expired (> 5ms):
   - Over `FAIR_BYTES`? → Apply **E2: Proportional Penalty** (Tier 3: -60, Tier 2: -30, Tier 1: -10, Default: -2)
   - Under `FAIR_BYTES`? → Reward (+1 karma, capped at 100)
   - **E6: Karma Momentum** — If karma is rapidly degrading (delta ≥ 15), apply extra -5 penalty
   - **E7: Slow-Start Leniency** — Skip penalties for first 20 packets
5. **Color Assignment** — karma > 80 → GREEN, > 40 → YELLOW, else RED
6. **E2E Clone Trigger** — On color change or every 8th packet, set `should_clone_e2e = 1` (only for flow_id 1 or 2)
7. **Queue Mapping** — `standard_metadata.priority = flow_color`
8. **Traffic Shaping (Enforcement):**
   - RED flows: If `current_bytes > FAIR_BYTES` → increment `reg_drops`, clone I2E, drop
   - YELLOW flows: If bytes > 1.5× `FAIR_BYTES` → clone I2E, drop

#### Persistent Registers
| Register | Size | Purpose |
|---|---|---|
| `reg_bytes` | 16 × 32-bit | Bytes accumulated per flow in current window |
| `reg_drops` | 16 × 32-bit | Total drop count per flow (for visualization) |
| `reg_karma` | 1024 × 16-bit | Karma score per flow |
| `reg_wstart` | 1024 × 48-bit | Window start timestamp |
| `reg_last_seen` | 1024 × 48-bit | Last packet timestamp (for idle detection) |
| `reg_total_pkts` | 1024 × 32-bit | Total packets per flow |
| `reg_prev_karma` | 1024 × 16-bit | Previous window's karma (for momentum) |
| `reg_prev_color` | 1024 × 2-bit | Previous color (for INT clone trigger) |

### 3.4 Egress Pipeline (`egress.p4`)

1. **Normal packets (`instance_type == 0`):**
   - Save `enq_qdepth` to `meta.saved_qdepth`
   - Write `enq_qdepth` to `reg_qdepth` register (indexed by egress port)
   - If `should_clone_e2e == 1` → trigger `clone(CloneType.E2E, 4)`

2. **Cloned packets (`instance_type == 1` or `2`):**
   - Set `kbcs_telemetry_t` header valid
   - Change EtherType to `0x1234` (custom telemetry marker)
   - Stamp karma, color, queue_id, is_dropped
   - E2E clones (`type 2`): stamp real `saved_qdepth` from egress port
   - I2E clones (`type 1`): stamp `enq_qdepth = 0` (ingress has no queue info)

3. **ECN Marking:** YELLOW flows get ECN CE bits set in `diffserv`

4. **Deparser:** Emits Ethernet → kbcs_telemetry → IPv4 → TCP

---

## 4. Telemetry Pipeline

### 4.1 Data Flow Architecture

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐     ┌──────────┐     ┌─────────┐
│  P4 Switch  │────→│  tcpdump    │────→│int_collector │────→│InfluxDB  │────→│ Grafana │
│ (BMv2 s1)   │ INT │(collector)  │PCAP │   .py        │JSON │ (Docker) │     │(Docker) │
│             │clone│  Port 4     │     │              │     │Port 8086 │     │Port 3000│
└─────────────┘     └─────────────┘     └──────────────┘     └──────────┘     └─────────┘
       │                                                            ↑
       │ reg_karma, reg_bytes, reg_drops                            │
       └──────────────────→ metrics_exporter.py ───→ karma_log.csv ─┘
                            (simple_switch_CLI                 (upload_and_run.py
                             batch polling 2Hz)                 pushes to InfluxDB)
```

### 4.2 INT Collector (`int_collector.py`)

- Runs on the VM, reads `/tmp/collector.pcap` (captured by tcpdump on the collector host)
- Uses raw `struct` binary parsing (no Scapy dependency)
- Handles `LINKTYPE_ETHERNET`, `LINKTYPE_LINUX_SLL`, `LINKTYPE_LINUX_SLL2`
- Accepts both EtherType `0x1234` (telemetry) and `0x0800` (fallback for I2E clones)
- Extracts: karma_score, color, queue_id, enq_qdepth, is_dropped, flow (from IP srcAddr)
- Outputs `results/telemetry.json`

### 4.3 Metrics Exporter (`metrics_exporter.py`)

- Runs on the VM alongside iperf3 traffic
- **Batched CLI reads:** All 6 register reads (`reg_karma[1,2]`, `reg_bytes[1,2]`, `reg_drops[1,2]`) are piped into a single `simple_switch_CLI` invocation for speed (~2Hz sampling)
- **Queue Proxy:** `cubic_qdepth = cubic_bytes // 1500` (converts window bytes to approximate packet count)
- **Drop Rate:** Computes delta between consecutive `reg_drops` readings
- Outputs `results/karma_log.csv` with columns: `time_sec, cubic_karma, bbr_karma, cubic_qdepth, bbr_qdepth, cubic_drops, bbr_drops`

### 4.4 Upload & Run (`upload_and_run.py`)

Orchestrates the entire pipeline from the Windows host:
1. SSH into VM → Clean old files → SCP upload all KBCS files
2. `make build` → P4 compilation
3. Run pingall test → Verify connectivity
4. Run traffic test (Mininet + iperf3 + metrics_exporter + tcpdump)
5. SCP download results from VM
6. Push to InfluxDB: reads `karma_log.csv` + `telemetry.json`, creates InfluxDB line protocol, POSTs to `http://localhost:8086/write?db=kbcs_telemetry`
7. Timestamps are mapped to current time window so Grafana's "Last 5 minutes" view always works

### 4.5 Docker Infrastructure (`docker-compose.yml`)

| Container | Image | Port | Purpose |
|---|---|---|---|
| `kbcs_influxdb` | influxdb:1.8 | 8086 | Time-series database |
| `kbcs_grafana` | grafana/grafana:latest | 3000 | Dashboard visualization |

- InfluxDB auto-creates `kbcs_telemetry` database
- Grafana auto-provisions data source + dashboard via mounted volumes

---

## 5. Grafana Dashboard (`kbcs.json`)

Three time-series panels on the **"KBCS Physical INT Telemetry"** dashboard:

| Panel | Query | Y-Axis | Description |
|---|---|---|---|
| **Physical Packet Drops** | `SELECT sum("dropped") ... GROUP BY time(1s)` | Auto | CUBIC drops spike to 50–150/interval during congestion; BBR stays 0 |
| **Live Queue Occupancy** | `SELECT mean("qdepth") ... GROUP BY time(1s)` | 0–15 | CUBIC queue proxied from `reg_bytes`; BBR stays near 0 |
| **Hardware Karma Score** | `SELECT mean("karma") ... GROUP BY time(1s)` | 0–110 | CUBIC oscillates 0–100; BBR stays flat at 100 |

---

## 6. Key Bugs Fixed

### Bug 1: Missing `--priority-queues` flag
**Symptom:** All flows went to the same FIFO queue; KBCS had no effect.
**Fix:** Created `KBCSSwitch` subclass of `P4Switch` that injects `--priority-queues 3` into the `simple_switch` command.

### Bug 2: Zero `enq_qdepth` in telemetry
**Symptom:** The Live Queue Occupancy graph showed all zeros.
**Root Cause:** I2E clones (triggered at Ingress) are sent directly to the collector port (Port 4), which has an idle queue → `enq_qdepth = 0`.
**Fix:** Switched admitted packets to **E2E cloning** (triggered at Egress after the packet traverses the bottleneck port). `meta.saved_qdepth` preserves the real `enq_qdepth` for the clone. Dropped packets continue using I2E (they never reach Egress).

### Bug 3: E2E clones capturing h3 ACKs
**Symptom:** Only 12 out of 1883 PCAP frames matched h1/h2 IPs.
**Root Cause:** The E2E clone trigger fired for ALL flows including h3→h1/h2 ACK packets. These ACKs traverse non-congested ports (1/2), so their queue depth was always 0.
**Fix:** Restricted `should_clone_e2e = 1` to only `flow_id == 1 || flow_id == 2`.

### Bug 4: CUBIC/BBR queue depth overlapping
**Symptom:** Both flow lines were identical on the Queue Occupancy graph.
**Root Cause:** The proxy calculated `total_bytes / 1500` and pushed the same value to both flows.
**Fix:** Split into `cubic_qdepth = cubic_bytes // 1500` and `bbr_qdepth = bbr_bytes // 1500`.

### Bug 5: Sparse Physical Packet Drops
**Symptom:** The Drops graph was essentially a flat line with scattered dots.
**Root Cause:** Drop events came only from PCAP-sampled INT clones (~10 per test).
**Fix:** Added `reg_drops` register in Ingress that increments on every KBCS drop. The metrics exporter polls it at 2Hz and computes a per-interval drop rate.

---

## 7. Test Results (Latest Run)

```
h1 (CUBIC): 4.75 Mbps (retransmits: 392)
h2 (BBR):   0.35 Mbps (retransmits: 0)
Jain's Fairness Index: 0.5731
```

- **135 telemetry data points** pushed to InfluxDB (62 from karma_log + 11 from PCAP)
- **Sampling rate:** ~2Hz (62 samples / 30 seconds)
- **Data columns:** karma, qdepth, drops — all per-flow (CUBIC vs BBR)

---

## 8. Running the Project

### Prerequisites
- Windows host with Python 3, Docker Desktop
- VirtualBox VM with BMv2, Mininet, iperf3 (SSH on port 2222, user: p4/p4)

### Commands
```bash
# 1. Start telemetry infrastructure (Windows, from kbcs/ folder)
docker-compose up -d

# 2. Run full pipeline (Windows, from Project-Implementation/ folder)
python upload_and_run.py --traffic --duration 30

# 3. View dashboard
# Open http://localhost:3000 → Set time to "Last 5 minutes"
```

---

## 9. File Index

| File | Location | Purpose |
|---|---|---|
| `headers.p4` | `kbcs/p4src/` | Header definitions + metadata struct |
| `parser.p4` | `kbcs/p4src/` | Ethernet → IPv4 → TCP parser |
| `ingress.p4` | `kbcs/p4src/` | Karma Engine + Traffic Shaping |
| `egress.p4` | `kbcs/p4src/` | INT stamping + E2E cloning + ECN marking |
| `kbcs.p4` | `kbcs/p4src/` | Top-level P4 program (includes all above) |
| `topology.py` | `kbcs/` | Mininet topology + iperf3 test orchestration |
| `metrics_exporter.py` | `kbcs/` | 2Hz register polling → karma_log.csv |
| `int_collector.py` | `kbcs/` | PCAP binary parser → telemetry.json |
| `upload_and_run.py` | root | SSH orchestrator + InfluxDB pusher |
| `docker-compose.yml` | `kbcs/` | InfluxDB + Grafana containers |
| `kbcs.json` | `kbcs/grafana-provisioning/dashboards/` | Grafana dashboard definition |
