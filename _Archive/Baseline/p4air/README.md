# P4air — Baseline Implementation for KBCS

> **Paper**: *P4air: Increasing Fairness among Competing Congestion Control Algorithms*
> **Authors**: Belma Turkovic & Fernando Kuipers (TU Delft, IEEE INFOCOM 2020)

## Overview

P4air enforces fairness between flows using different congestion control algorithms (CCAs) by running three modules entirely in the P4 data plane:

1. **Fingerprinting** — classifies flows into 4 CCA groups (loss-based, loss-delay, delay-based, model-based)
2. **Reallocation** — dynamically distributes queues among groups proportional to flow counts
3. **Apply Actions** — applies per-group actions (drop, delay, window-adjust) to suppress aggressive flows

## Quick Start (on P4 VM)

```bash
cd Baseline/p4air/

# 1. Compile the P4 program
make build

# 2. Run Mininet with interactive CLI
make run

# 3. Run connectivity test
make test

# 4. Run traffic experiment (4 flows: Cubic, BBR, Vegas, Illinois)
make traffic

# 5. View results
cat results/last_test.json
python3 analysis/calculate_fairness.py --dir /tmp/
```

## Project Structure

```
p4air/
├── p4src/                          # P4 source code
│   ├── p4air.p4                    # Top-level program
│   ├── headers.p4                  # Headers, metadata, constants
│   ├── parser.p4                   # Parser, deparser, checksums
│   ├── ingress.p4                  # Ingress pipeline
│   └── egress.p4                   # Egress pipeline
├── utils/
│   └── p4_mininet.py               # BMv2 Mininet helper
├── experiments/
│   └── run_comparison.py           # Automated comparison experiments
├── analysis/
│   ├── calculate_fairness.py       # Jain's Fairness Index calculator
│   └── plot_results.py             # Generate comparison charts
├── topology.py                     # Mininet topology builder
├── runtime.json                    # Static forwarding rules
├── Makefile                        # Build & run automation
├── simple_switch_pq.sh             # BMv2 priority queue wrapper
└── README.md                       # This file
```

## Requirements

- P4 VM with: `simple_switch` (BMv2), `p4c-bm2-ss`, Mininet, Python 3
- Python packages: `scapy`, `matplotlib`, `numpy` (for analysis)
- Linux CCA modules: `tcp_cubic`, `tcp_bbr`, `tcp_vegas`, `tcp_illinois`
