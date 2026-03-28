# KBCS Architecture Deep Dive

This document provides a highly technical breakdown of the KBCS (Karma-Based Congestion Signaling) architecture. It is separated into three major domains: Data-Plane Enforcement, Control-Plane Intelligence, and Full-Stack Telemetry. 

---

## 1. Abstract System Architecture

Our KBCS architecture uniquely separates high-speed enforcement from high-complexity learning. We avoid passing every single packet through a Python-based Reinforcement Learning (RL) agent. The 600ms Inter-Process Communication (IPC) bottleneck makes per-packet software tuning impossible.

Instead, we designed a **Macro-Micro Separation:**
1. **The P4 Switch (Data Plane - Micro):** Enforces rules, tracks karma, drops packets, or marks ECN in the sub-millisecond range using hardcoded math (`ingress.p4`). 
2. **The Meta-RL Tuner (Control Plane - Macro):** Monitors global network fairness (JFI) every 2 seconds via Thrift registers and slowly adjusts the *parameters* (Penalty/Reward scales) inside the P4 switch.

---

## 2. P4 Data-Plane: KBCS-AQM algorithm (`ingress.p4`)

Active Queue Management (AQM) determines how to handle network congestion before the queue physically fills up.

### A. Karma Tracking (The Memory)
The switch tracks each flow's recent behavior. 
- Packets that fit comfortably within the fair share budget earn **Reward** points.
- Packets that massively exceed the budget earn **Penalty** points.
Karma decays over time. As penalty points accumulate, a flow's color degrades: `GREEN -> YELLOW -> RED`.

### B. Hybrid Enforcement (The Action)
We designed a radically novel approach to Congestion Control enforcement. 
When a flow exceeds its allocated budget (`fair_bytes`):
1. **GREEN Flows (ECN Protection):** The switch applies an **Explicit Congestion Notification (ECN)** mark to the IPv4 header `(hdr.ipv4.diffserv = hdr.ipv4.diffserv | 3)`. Delay-sensitive algorithms like **BBR** or **Vegas** respond excellently to ECN. They gently reduce their sending rate without catastrophically collapsing their congestion window. 
2. **RED/YELLOW Flows (Drop Punishment):** The switch actively **drops** the packet. Loss-sensitive algorithms like **CUBIC** ignore slight delays, and thus accumulate bad karma. The only way to stop CUBIC from taking over a network is to forcefully drop its packets. 

### C. Budget Shrinking 
Before applying the ECN/Drop penalty, the switch dynamically shrinks the target flow's budget:
- `YELLOW` flows only get 75% of the `fair_bytes` allocated to them.
- `RED` flows only get 50%.
This mathematically ensures that aggressive CCAs are starved back down to a fair equilibrium.

---

## 3. Control-Plane: The Meta-RL Tuner (`rl_controller.py`)

A pure static P4 switch can't handle wildly varying traffic patterns (e.g., 3 CUBIC vs 1 BBR, or 10 Vegas vs 1 CUBIC). The penalty and reward thresholds must be dynamically tuned. 

### Epoch-Based Tuning
The Python `rl_controller.py` polls the P4 switch via Thrift (`simple_switch_CLI` `register_read`) every 2 seconds. 
It ingests:
1. `reg_total_pkts`
2. `reg_drops`
3. `reg_ecn_marks`

The controller computes the real-time **Jain's Fairness Index (JFI)** across all flows. 

### The Meta-Strategy
If the JFI is consistently low (e.g., `< 0.70`) for three consecutive epochs, the system knows that aggressive flows are successfully dominating the polite flows. 
The RL agent issues a `register_write` to increase the `reg_penalty_amt`. This makes the P4 switch punish aggressive behavior much faster. Conversely, if JFI is extremely high (`> 0.90`), the network is stable, and the Meta-Tuner decreases the penalty to improve global link utilization.

---

## 4. Addressing Heterogeneous Validation 

A critical step in KBCS research methodology was proving the system works on **True Heterogeneous Traffic**.

### The Kernel Module Issue
Most network simulator setups (like Mininet) run hosts in shared kernel network namespaces. By default, standard Ubuntu kernels do not install the `tcp_vegas.ko` or `tcp_illinois.ko` TCP connection algorithms. Without them, Mininet silently defaults all requested connections to `CUBIC`, completely nullifying any multi-CCA fairness testing.

### The Fix
Our architecture scripts (`upload_and_run.py` & `topology.py`) now explicitly:
1. Sudo-install `linux-modules-extra-$(uname -r)` inside the VM. 
2. Load the rare TCP modules directly into the Linux kernel via `modprobe`.
3. Force write the allowed lists to `/proc/sys/net/ipv4/tcp_allowed_congestion_control` to bypass namespace quoting bugs in Mininet.

This ensures every benchmark tested on the KBCS-AQM is authentic, separating aggressive loss-based behaviors from polite RTT-delay behaviors.
