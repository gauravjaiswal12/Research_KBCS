# KBCS: Karma-Based Congestion Control System
## Comprehensive Presentation & Methodology Guide

This document provides an in-depth breakdown of the KBCS (Karma-Based Congestion Control System) project. It is structured to provide all the detailed talking points, technical depth, and research justification required for a comprehensive academic presentation.

---

### 1. The Problem: Why is KBCS Needed?

#### The Inter-CCA Fairness Crisis
Modern computer networks are no longer homogenous. Historically, the internet was dominated by Loss-based Congestion Control Algorithms (CCAs) like TCP CUBIC and TCP Reno, which cut their sending rates when they detected packet loss. 
However, the landscape has shifted with the introduction of Model-based/Delay-based CCAs like Google's TCP BBR. BBR does not react to packet loss; instead, it models the network pipe and pushes data to maintain high throughput. 

**The result is a severe fairness imbalance:**
When CUBIC and BBR share a bottleneck link, BBR's aggressive probing fills the queue, causing packet drops. CUBIC interprets these drops as severe congestion and drastically reduces its speed. BBR ignores the drops and takes over the freed bandwidth. 
* **The Impact:** Loss-based flows are starved, suffering extreme performance degradation. 
* **The Need:** Networks require an intelligent, intermediary system inside the switch (Active Queue Management - AQM) to detect this bullying behavior and enforce fairness, regardless of the CCA running on the end-host.

---

### 2. The Solution: How is KBCS Better?

#### Beyond Traditional AQM
Traditional Active Queue Management (like RED - Random Early Detection) simply drops packets randomly when queues get full. They are "CCA-blind" and treat all flows equally, meaning aggressive flows like BBR still win.

#### The KBCS Advantage
KBCS is a **Stateful, Karma-Aware AQM**. It evaluates flows not just on their current packet rate, but on their historical behavior and willingness to share bandwidth.
* **Fairness-First:** KBCS actively calculates Jain's Fairness Index (JFI) and intervenes specifically to maximize it.
* **Granular Enforcement:** Instead of just dropping packets, KBCS uses a multi-stage enforcement pipeline including ECN (Explicit Congestion Notification) marking, dynamic flow budgeting, and hardware-level Priority Queues.
* **Behavioral Tracking (Karma):** Flows earn or lose "Karma" based on their aggressiveness, creating a persistent reputation system inside the switch.

---

### 3. The Novelty: What Are We Doing That Others Have Not?

#### Dynamic Karma vs. Static Classification
Recent state-of-the-art research (like the *P4CCI* paper) attempts to solve this by using Machine Learning to classify flows (e.g., "This is BBR", "This is CUBIC") and mapping them to static queues. 
**Why KBCS is superior/novel:**
1. **P4CCI relies on static classification:** If a new CCA is invented, the ML model in P4CCI cannot classify it without retraining. 
2. **KBCS is CCA-Agnostic:** We do not care *what* CCA the host is running. We evaluate the *behavior*. If a flow behaves aggressively and hogs bandwidth, it loses Karma. If it behaves fairly, it gains Karma. This makes KBCS infinitely scalable to future TCP variants.
3. **Reinforcement Learning (RL) Integration:** Unlike static heuristics, our control plane uses RL to dynamically tune penalty thresholds based on real-time network states.
4. **Red Streak Recovery (The "Second Chance" Mechanism):** KBCS implements a novel recovery mechanism where chronically penalized flows are given a temporary karma reset (probation) to prevent permanent starvation, a feature absent in strict ML classifiers.

---

### 4. In-Depth Methodology: How KBCS Works

KBCS splits operations between a **P4 Data Plane** (for line-rate packet processing) and a **Python Control Plane** (for asynchronous intelligence).

#### Phase 1: Ingress Traffic Monitoring (P4 Data Plane)
Every time a packet enters the switch, the P4 pipeline extracts the 5-tuple to identify the flow.
* **Bytes in Flight (BIF) Estimation:** The switch parses TCP Sequence and Acknowledgment numbers to estimate how much data the flow currently has in the network.
* **Hardware Counters:** P4 registers track exactly how many bytes each flow has successfully forwarded and how many packets have been dropped.

#### Phase 2: Karma Calculation & State Management (Control Plane)
Every 15 milliseconds, the Python controller reads the P4 registers via gRPC.
* **Fairness Calculation:** It computes the exact fair share budget (`fair_bytes`) and the current Jain's Fairness Index (JFI).
* **Karma Update:** 
  * If a flow exceeds its fair share, its Karma score decreases.
  * If a flow stays within its limits, its Karma score increases.
* The updated Karma scores and dynamic thresholds are pushed back down into the P4 switch registers.

#### Phase 3: Color-Coding & Dynamic Budgeting (P4 Ingress)
Based on the Karma score provided by the controller, the P4 switch classifies the flow into a color:
* **GREEN (Karma > 75):** Good citizen. Gets 100% of the fair share budget.
* **YELLOW (Karma 41-75):** Suspicious. Gets 75% of the fair share budget.
* **RED (Karma 0-40):** Aggressive. Restricted to 25% of the fair share budget.

#### Phase 4: Active Enforcement (P4 Egress)
When packets are scheduled to leave the switch, KBCS enforces the rules:
1. **ECN Marking:** If a flow exceeds its dynamic budget (e.g., a YELLOW flow sends more than 75% of the fair share), KBCS sets the ECN (Explicit Congestion Notification) bits in the IP header. This politely tells the sender to slow down.
2. **Priority Flow Queues (PFQ):** This is the ultimate enforcer. KBCS utilizes BMv2's hardware priority queues:
   * **Queue 2 (High Priority):** Reserved exclusively for GREEN flows. Their packets are sent first.
   * **Queue 1 (Medium Priority):** Used by YELLOW flows.
   * **Queue 0 (Low Priority):** Used by RED flows. RED flows only get bandwidth if GREEN and YELLOW have nothing to send.

#### Phase 5: The Red Streak Recovery
If an aggressive flow stays in the RED zone for 20 consecutive cycles (~300ms), it is technically starved. KBCS detects this "Red Streak" and forcefully resets its Karma to a low YELLOW state. This acts as a probation period, allowing the flow to transmit briefly and prove it has slowed down, ensuring the system does not permanently kill connections.

---

### 5. Expected Results & Proof of Concept

When presenting the results, focus on the **Jain's Fairness Index (JFI)**.
* **Baseline (FIFO):** In a mixed environment (e.g., CUBIC + BBR), the JFI typically collapses to ~0.70 or lower, with BBR consuming the vast majority of the bandwidth and CUBIC nearly dropping to 0.
* **KBCS:** By mapping flows to separate priority queues based on dynamic Karma, the throughput equalizes. The JFI rises above **0.95**, proving mathematically that KBCS successfully forces inherently unfair CCAs to share the network equally.
