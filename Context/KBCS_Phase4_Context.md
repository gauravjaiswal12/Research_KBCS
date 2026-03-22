# KBCS Project Context Handoff

## Project Goal
Implement a **Karma-Based Credit Scheduler (KBCS)** in P4 to achieve throughput fairness between CUBIC and BBR TCP flows on a shared bottleneck link. The system runs on **BMv2 simple_switch** inside a **Mininet** topology on a P4 VM (Ubuntu, accessed via SSH on port 2222, user: p4, pass: p4).

## VM Environment
- **VM Access**: `ssh p4@localhost -p 2222` (port forwarded)
- **Python**: `/usr/bin/python3` (3.12.3)
- **Mininet**: 2.3.0, uses `p4_mininet.py` from `~/kbcs/utils/` (copied from `~/tutorials/utils/`)
- **P4 Compiler**: `p4c-bm2-ss`
- **iperf3**: `/usr/bin/iperf3` (installed via apt)
- **Working Dir on VM**: `~/kbcs/`
- **Upload Script**: `e:\Research Methodology\Project-Implementation\upload_and_run.py` — SSH/SCP script that cleans, uploads, builds, and runs pingall test automatically

## Project Structure (on VM: ~/kbcs/)
```
kbcs/
├── p4src/
│   ├── kbcs.p4              # Main P4 program (includes all others)
│   ├── kbcs_baseline.p4     # Baseline version (no karma, just forwarding)
│   ├── headers.p4           # Ethernet, IPv4, TCP headers + local_metadata_t
│   ├── parser.p4            # Parser: Eth → IPv4 → TCP
│   ├── ingress.p4           # KBCS karma engine (CURRENT WORKING VERSION)
│   ├── ingress_baseline.p4  # Plain forwarding (no karma, for baseline test)
│   └── egress.p4            # Deparser + checksum
├── topology.py              # Mininet topology, iperf3 tests, results parsing
├── Makefile                 # build, test, traffic, baseline-traffic targets
├── runtime.json             # Table entries (IP → MAC → port mapping)
├── run_experiment.py        # Automated baseline vs KBCS comparison
├── simple_switch_pq.sh      # (Unused) wrapper script attempt
├── utils/                   # Copied from ~/tutorials/utils/ (p4_mininet.py etc.)
├── build/                   # Compiled JSON files
└── results/                 # iperf3 JSON output
```

## Local Windows Directory
`e:\Research Methodology\Project-Implementation\kbcs\` — mirrors the VM structure, uploaded via `upload_and_run.py`

## Completed Phases

### ✅ Phase 1: Basic Forwarding
- IPv4 LPM forwarding table with 3 hosts on 10.0.0.0/24
- Static ARP entries configured in topology.py
- `pingall` test passes: 0% dropped (6/6 received)

### ✅ Phase 2: Karma Logic (P4 Code Complete)
Full 8-step pipeline in `ingress.p4`:
1. **Flow ID**: CRC16 hash of 5-tuple → 16-bit index (0–65535)
2. **State Read**: `flow_bytes` and `flow_karma` registers
3. **Aggression Detection**: Decay-based `(old >> 1) + pkt_len`
4. **Karma Update**: Aggressive → penalty (−5), Good → reward (+1), clamped 0–100
5. **Flow Coloring**: GREEN (karma > 80) / YELLOW (40-80) / RED (< 40)
6. **Queue Mapping**: `standard_metadata.priority` = flow_color (2/1/0)
7. **AQM Enforcement**: RED flows get packets dropped (forces CUBIC to back off)
8. **IPv4 Forwarding**: Independent of karma

### ✅ Phase 3: Environment & Traffic
- Topology: h1(CUBIC, 100Mbps) ↔ s1 ↔ h3(Receiver, **10Mbps bottleneck**, 5ms delay)
- Topology: h2(BBR, 100Mbps) ↔ s1 ↔ h3
- iperf3 dual-server on h3 (ports 5201, 5202)
- Uses `sendCmd()`/`waitOutput()` for parallel iperf3 execution
- Results written to `/tmp/kbcs_h1_cubic.json` and `/tmp/kbcs_h2_bbr.json`
- Automatic Jain's Fairness Index calculation

### 🔄 Phase 4: Verification (Partially Done)

#### Baseline Test COMPLETED ✅
```
h1 (CUBIC): 8.28 Mbps (retransmits: 78)
h2 (BBR):   1.82 Mbps (retransmits: 12)
Jain's Fairness Index: 0.7093
```
This proves CUBIC bullies BBR (8.28 vs 1.82 Mbps on a 10 Mbps link).

#### KBCS Test PENDING ❌
The KBCS traffic test needs to be run with `make traffic`.
The user hasn't run it after the latest fix (restored full architecture with AQM enforcement).

## Known Issue: BMv2 --priority-queues
- `simple_switch --priority-queues 3` crashes on this VM ("P4 switch did not start correctly")
- The flag may not be supported in this BMv2 version
- **Workaround**: AQM enforcement (Step 7) drops packets from RED flows directly in P4, which forces CUBIC to reduce CWND — functionally equivalent to a tail-dropping Bronze queue
- `standard_metadata.priority` is still SET in the P4 code for architectural completeness
- **TODO**: Check `simple_switch --help 2>&1 | grep -i priority` to see if the flag name is different

## Key Makefile Targets
```bash
make build             # Compile kbcs.p4
make build-baseline    # Compile kbcs_baseline.p4 (no karma)
make test              # Build + pingall test
make traffic           # Build + 30s iperf3 test (KBCS enabled)
make baseline-traffic  # Build baseline + 30s iperf3 test (no KBCS)
```

## What Remains
- [ ] Run `make traffic` to get KBCS results
- [ ] Compare baseline vs KBCS Jain's Fairness Index
- [ ] Read karma register values via `simple_switch_CLI` to verify karma changes
- [ ] Phase 4: Document results, generate comparison table
- [ ] Optional: Parameter sensitivity study (vary BYTE_THRESHOLD, PENALTY, REWARD)
- [ ] Optional: Limitations section for documentation

## Design Documents
- `e:\Research Methodology\Project-Implementation\kbcs_design.md` — Full KBCS design with flow diagrams
- `e:\Research Methodology\Project-Implementation\kbcs_implementation_plan.md` — Phase-by-phase implementation strategy
