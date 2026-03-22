# Software Requirements Specification (SRS)
## Karma-Based Credit Scheduler (KBCS)

**Version:** 1.0
**Date:** March 2026
**Standard:** IEEE 830 / ISO/IEC/IEEE 29148

---

## 1. Introduction

### 1.1 Purpose
The purpose of this Software Requirements Specification (SRS) is to precisely document the technical and functional requirements for the "Karma-Based Credit Scheduler" (KBCS) system. This document is intended for network engineers, software developers, and researchers tasked with implementing, testing, or extending the KBCS model within a P4 programmable datapath environment. 

### 1.2 Scope
KBCS is a data-plane network packet scheduling system designed to enforce fair bandwidth distribution among competing TCP Congestion Control Algorithms (CCAs) using limited physical switch queues. KBCS operates entirely within the switch hardware (written in P4) without requiring modifications to end-host protocols.
This iteration of the KBCS includes the experimental testbed architecture built on BMv2 (`simple_switch`) and Mininet to evaluate the interactions of loss-based (CUBIC) and model-based (BBR) congestion control protocols.

### 1.3 Definitions, Acronyms, Abbreviations
*   **AQM:** Active Queue Management.
*   **BMv2:** Behavioral Model version 2 (A P4 software switch).
*   **BBR:** Bottleneck Bandwidth and Round-trip propagation time (Google's CCA).
*   **CUBIC:** Default Linux loss-based TCP CCA.
*   **CCA:** Congestion Control Algorithm.
*   **CWND:** Congestion Window.
*   **FCT:** Flow Completion Time.
*   **P4:** Programming Protocol-independent Packet Processors.
*   **Q_DEPTH:** Queue Depth (number of packets currently sitting in a queue).
*   **WRR:** Weighted Round Robin.
*   **Incast:** A network pattern where many flows simultaneously transmit to a single receiver.

### 1.4 Document Overview
Section 2 provides the overall description of the system, including the architectural overview and operating environment. Section 3 outlines specific system requirements (functional and non-functional). Section 4 maps out deployment strategies, while Section 5 covers interfaces and system models.

---

## 2. Overall Description

### 2.1 Product Perspective
KBCS is a standalone P4-based packet processing module intended to replace or augment standard FIFO or strict-priority scheduling on data center switches. The current reference implementation operates in a Mininet virtual topology (`topology.py`) running a BMv2 software switch. 

### 2.2 System Architecture Overview
The system is logically divided into three interconnected planes:
1.  **Data Plane (P4 Switch):**
    *   **Parser (`parser.p4`):** Extracts Ethernet, IPv4, and TCP headers. 
    *   **Ingress Pipeline (`ingress.p4`):** Performs flow identification (5-tuple Hash), flow byte metering (using exponential decay logic), calculates/updates the Karma credit score via persistent registers, sets the "Flow Color" (Red, Yellow, Green), applies AQM actions (mark-to-drop), and routes the packet.
    *   **Traffic Manager (BMv2 Native):** Hardware mechanism that holds packets in queues mapped by the Ingress pipeline.
    *   **Egress Pipeline (`egress.p4`):** Updates checksums and emits the parsed packet onto the bottleneck link.
2.  **Host Plane (Mininet Hosts):**
    *   Hosts (`h1`, `h2`, `h3`) running heavy `iperf3` workloads using specific configured kernels (CUBIC vs. BBR).
3.  **Control Plane (Python scripts):** 
    *   Orchestrates tests, injects static forwarding rules using `simple_switch_CLI`, and collects JSON telemetry metrics.

### 2.3 Product Functions
*   **Flow Classification:** Uniquely identify TCP streams via CRC16 hash of the 5-tuple.
*   **Bandwidth Metering:** Track an approximated sliding window of throughput using an exponential decay mathematical model directly on the switch ALU.
*   **Karma Evaluation:** Dynamically reward (+1) or penalize (-20) flow scores based on their transmission aggression above pre-defined thresholds.
*   **Flow Coloring & Queue Mapping:** Route packets to high, medium, or low-priority logical pipelines based on Karma boundaries.
*   **AQM Enforcement:** Proactively drop packets of "Red" (aggressive) flows when their Karma drops to a critical floor level, forcing TCP senders into Multiplicative Decrease.

### 2.4 User Classes and Characteristics
*   **Network Admins/Operators:** Will deploy the P4 binary binary (`.json`) onto switches and fine-tune threshold constants.
*   **Researchers:** Will run `topology.py` scripts to collect analytical data comparing BBR vs CUBIC contention.
*   **End-Users:** Transparent to the system; they benefit purely from lower FCTs and fair bandwidth distribution.

### 2.5 Operating Environment
*   **Operating System:** Ubuntu Linux 18.04+ (Required for `modprobe tcp_bbr`).
*   **Simulators:** Mininet network emulator.
*   **Compilers:** `p4c` compiler for generating BMv2 JSON artifacts.
*   **Execution Target:** BMv2 `simple_switch` (must be compiled with `--priority-queues` enabled for full efficacy).

### 2.6 Design and Implementation Constraints
*   **Memory Restrictions:** Real P4 switches lack infinite RAM. State is stored in statically sized arrays (e.g., `register<bit<16>>(65536)`). Hash collisions are a known constraint.
*   **Math Limitations:** P4 cannot perform floating-point operations or hardware looping/division. All algorithms (e.g., exponential decay) must be expressed as computationally cheap bit-shifts (`>> 3`).
*   **Lack of Wall-Clock Timers:** The data plane cannot trigger events on a timer. State decay only processes *on packet arrival*. 

---

## 3. System Requirements

### 3.1 Functional Requirements

#### FR-1: Flow Packet Parsing
The system MUST correctly parse incoming packets traversing `Ethernet -> IPv4 -> TCP/UDP/ICMP`. Unknown payloads MUST NOT crash the parser. Non-TCP traffic (such as ICMP/ARP) MUST bypass the Karma logic.

#### FR-2: Stateful Flow Tracking
The system MUST maintain a persistent memory register of size 65,536 indices. The system MUST compute a CRC16 hash of the IPv4 Src/Dst, TCP Src/Dst ports, and IPv4 protocol to determine the index.

#### FR-3: Aggression Metering (Exponential Decay)
The system MUST maintain a `flow_bytes` counter for each flow. Upon packet arrival, the system MUST compute:
`New Bytes = (Old Bytes - (Old Bytes >> 3)) + Packet Length`
This acts as a decaying aggregator without requiring an external clock.

#### FR-4: Karma Calculation Logic
The system MUST read the current Karma score.
*   If `flow_bytes > BYTE_THRESHOLD (4500)`: The system MUST deduct `PENALTY (20)` from the Karma score (Flooring at 1).
*   If `flow_bytes <= BYTE_THRESHOLD`: The system MUST grant `REWARD (1)` to the Karma score (Capping at 100).

#### FR-5: Queue Mapping Strategy
The system MUST categorize the flow color using the updated Karma score:
*   Karma > `HIGH_THRESHOLD (80)`: Assign `COLOR_GREEN (2)`
*   Karma > `LOW_THRESHOLD (50)`: Assign `COLOR_YELLOW (1)`
*   Karma < 50: Assign `COLOR_RED (0)`
The packet MUST be tagged with intrinsic metadata (`meta.queue_id` / egress spec) corresponding to its color.

#### FR-6: AQM Drop Enforcement
If a flow is evaluated as `COLOR_RED` AND its Karma score drops to `<= PENALTY`, the system MUST flag the packet for dropping (`mark_to_drop`). 
*Critical Condition:* Upon dropping a packet, the system MUST reset `flow_bytes` to 0 inside the register to allow the sender's subsequent retransmission to succeed without immediate cascading drops.

#### FR-7: Forwarding and Checksum
The system MUST perform standard IPv4 Longest Prefix Match (LPM) lookup to forward the packet out the correct egress port, decrement the TTL, and recalculate the IPv4 checksum prior to deparsing.

---

### 3.2 Non-Functional Requirements

#### NFR-1: Performance (Line-Rate Execution)
All P4 operations in the `Apply` block MUST execute strictly in O(1) time complexity to ensure the switch can sustain line-rate multi-terabit speeds when deployed on physical ASICs like Intel Tofino.

#### NFR-2: Scalability
The primary constraint on scalability is the register array size (`REG_SIZE = 65536`). The system MUST gracefully handle hash collisions by sharing Karma states between collided flows, ensuring no memory overflow errors occur. 

#### NFR-3: Reliability
System operation must be strictly atomic. The Read-Modify-Write cycle for the Karma registers must be handled in a single hardware transaction to prevent race conditions from concurrent packet pipeline execution.

#### NFR-4: Observability
The evaluation scripts (`topology.py`) MUST capture high-fidelity metrics comparing BBR and CUBIC flows by parsing `.json` output from `iperf3`. The system must automatically compute and log the Jain's Fairness Index for the provided test runs.

---

## 4. Interfaces and Data Requirements

### 4.1 Interface Requirements
*   **Hardware Interface:** Designed for Protocol Independent Switch Architecture (PISA).
*   **Software Interface (CLI):** Relies on `simple_switch_CLI` dynamically linked over Thrift port 9090 to inject initial static routing tables.
*   **Communication Interface:** End-hosts simulate communication using standard Linux TCP/IP stack over virtual Ethernet adapters (`veth`).

### 4.2 Data Models
*   **Persistent Registers:**
    *   `flow_bytes` (`register<bit<32>>`)
    *   `flow_karma` (`register<bit<16>>`)
*   **Volatile Metadata:**
    *   `meta.flow_id` (`bit<32>`)
    *   `meta.flow_color` (`bit<3>`)
    *   `meta.queue_id` (`bit<3>`)

---

## 5. System Deployment and Testing Architecture

### 5.1 Testing Topology 
The execution environment sets up a literal Dumbbell bottleneck for evaluation:
*   `h1` (Sender, CUBIC configured) --> 100 Mbps link --> Switch `s1`
*   `h2` (Sender, BBR configured) --> 100 Mbps link --> Switch `s1`
*   Switch `s1` --> 10 Mbps Link with 5ms delay and strict queue size of 200 --> `h3` (Receiver)

### 5.2 Build / CI Instructions
1.  **Compile:** `p4c-bm2-ss --p4v 16 kbcs.p4 -o kbcs.json`
2.  **Execution script:** `sudo python3 topology.py --behavioral-exe simple_switch --json kbcs.json --traffic`
    *   An explicit flag (`--priority-queues 3`) can be utilized if the BMv2 switch process supports multiple physical queuing structures for `COLOR_GREEN`, `COLOR_YELLOW`, and `COLOR_RED`.

### 5.3 Risk Analysis
*   **Risk:** P4 Switch configuration silences drops if priority queue logic maps traffic to queues that do not physically exist on the BMv2 standard target.
    *   *Mitigation:* The KBCS algorithm temporarily writes priority into general metadata and avoids native `--priority-queues` silent-drop anomalies unless specifically deployed on hardware supporting it. 
*   **Risk:** Retransmission Death Spirals.
    *   *Mitigation:* Successfully isolated in the ingress code via Line 170 `meta.flow_bytes = 0` which clears the penalty accumulator specifically on a packet drop.

---
**[End of Document]**
