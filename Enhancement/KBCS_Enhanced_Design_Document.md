# Software Requirements Specification (SRS)
## for Karma-Based Credit Scheduler (KBCS)

**Version:** 1.0  
**Status:** Approved  
**Date:** March 3, 2026

---

## 1. Introduction

### 1.1 Purpose
The purpose of this document is to specify the software requirements for the Karma-Based Credit Scheduler (KBCS). KBCS is an advanced packet scheduling and queue management system designed for programmable data plane switches (specifically P4 architecture). The system aims to resolve competitive unfairness and bufferbloat issues that occur when heterogeneous TCP congestion control algorithms (e.g., CUBIC and BBR) share a bottleneck link.

### 1.2 Scope
This document covers the complete software architecture, functional, and non-functional requirements of the KBCS system. The KBCS applies a "Social Credit" or "Karma" state to network flows in real-time, penalizing aggressive flows that monopolize queues while rewarding stable behaviors. The system includes:
- A P4-based switch implementation for traffic shaping and AQM (Active Queue Management).
- A Python/Mininet-based evaluation topology for performance simulation.
- Control plane initialization scripts.

### 1.3 Definitions, Acronyms, Abbreviations
- **AQM**: Active Queue Management.
- **BBR**: Bottleneck Bandwidth and Round-trip propagation time (Google's congestion control).
- **BMv2**: Behavioral Model version 2 (software switch for P4).
- **CUBIC**: Default Linux TCP congestion control algorithm.
- **P4**: Programming Protocol-independent Packet Processors.
- **SRS**: Software Requirements Specification.
- **WRR**: Weighted Round Robin.
- **TM**: Traffic Manager.

### 1.4 References
- IEEE 830: Recommended Practice for Software Requirements Specifications.
- `kbcs_design.md`: KBCS Pipeline Flowchart and Algorithm Design.
- `ingress.p4`: P4 Data Plane source implementation.

### 1.5 Document Overview
The remainder of this document outlines the overall functional description of KBCS, specific architectural constraints, granular requirements (functional and non-functional), performance models, and hardware/software interfaces necessary for deployment and verification.

---

## 2. Overall Description

### 2.1 Product Perspective
KBCS operates within the network switch infrastructure, specifically residing in the ingress pipeline and traffic manager of a P4-programmable switch. It is a subsystem that replaces default FIFO queuing with an intelligent, flow-aware scheduling logic. It interfaces downstream with Linux host network stacks and upstream with Mininet/SDN controllers.

### 2.2 System Architecture Overview
The system is divided into two major planes:
1. **Data Plane (P4 Switch)**: Executes line-rate operations including flow hashing, Karma register updates, Active Queue Management (AQM), and traffic classification.
2. **Control Plane & Simulation (Python/Mininet)**: Defines the network topology, instantiates virtual hosts with specific TCP stacks (CUBIC, BBR), and sets exact routing specifications via Thrift APIs.

### 2.3 Product Functions
- **Flow Parsing and Hashing**: Extracts 5-tuple metrics from incoming packet headers to assign a unique `Flow_ID` to TCP traffic.
- **Bandwidth Estimation**: Computes an exponentially decayed rate metric (`flow_bytes`) per flow without relying on hardware timers.
- **Karma Credit Adjustments**: Punishes flow abuse (subtracts points) during congestion bursts or rewards stability (adds points).
- **Differentiated Queuing**: Maps flow states (GREEN, YELLOW, RED) to strict hardware priority queues to enforce scheduling weight.
- **Active Retransmission Forgiveness**: Clears flow-rate registries temporarily upon packet drop to prevent TCP retransmission loops.

### 2.4 User Classes and Characteristics
- **Network Engineers/Researchers**: Will deploy the system in virtual (Mininet) or physical (Tofino) testbeds to collect network fairness data.
- **Automated CI/CD Pipelines**: Will invoke `upload_and_run.py` to compile and functionally test the P4 pipeline automatically. 

### 2.5 Operating Environment
- **Development/Simulation**: Ubuntu Linux (requires Kernel capabilities to modify `tcp_congestion_control`).
- **Network Emulator**: Mininet with P4 Behavioral Model (BMv2) `simple_switch`.
- **Compiler**: `p4c` for P4_16 standards.
- **Scripting Environment**: Python 3.x with Paramiko, Scp, and Mininet Python APIs.

### 2.6 Design and Implementation Constraints
- **State Atomicity**: All Karma updates must operate atomically across P4 ALU blocks to prevent race conditions.
- **Memory Limitation**: Given switch SRAM constraints, the state registry is hard-capped to 65,536 indices, accepting hash collisions natively.
- **Queue Limitations**: Simulation relies heavily on the `--priority-queues` argument in BMv2. Default BMv2 without this flag causes silent packet drops.

### 2.7 Assumptions and Dependencies
- The underlying switch architecture supports P4_16 standard and V1Model architectures.
- External Linux endpoints correctly increment TCP Sequence/ACK numbers.
- SSH and secure protocols are enabled in target VM bounds for remote execution via deployment scripts.

---

## 3. System Architecture

### 3.1 High-level Architecture Diagram

[Host 1: CUBIC Sender] ------\
                              \
                            [ P4 Switch: Ingress ] 
                              (1. Parser & Hashing)
                              (2. Flow_Bytes State Machine)
                              (3. Karma +/- Algorithmic Update)
                              (4. QoS Mapping & AQM)
                                       |
                            [ P4 Switch: Traffic Manager ] 
                              (Priority Queues via Scheduler)
                                       |
                            [ P4 Switch: Egress ] 
                                       |
[Host 2: BBR Sender] --------/      Bottleneck Link (10Mbps / 5ms Delay)
                                       |
                                [Host 3: Receiver]

### 3.2 Component-level Breakdown
1. **Parser (`parser.p4`)**: Extracts headers across OSI Layers 2-4 (Ethernet, IPv4, TCP).
2. **Ingress Engine (`ingress.p4`)**: The principal logic domain. Houses memory registers (`flow_bytes`, `flow_karma`), enforces exact match forwarding mapping (`ipv4_lpm`), and isolates malicious flows.
3. **Deparser (`egress.p4` / Core)**: Reassembles evaluated packets for serial transmission onto output port channels.
4. **Topology Orchestrator (`topology.py`)**: Boots Mininet overlay configurations, assigns traffic constraints, and instruments Linux `iperf3` binaries.

### 3.3 Module Interactions
- **Topology to Switch**: Submits REST/Thrift calls via `simple_switch_CLI` to inject `ipv4_lpm` routing paths instantly upon boot.
- **Ingress to Traffic Manager**: Passes processed intrinsic metadata (`queue_id`) derived from Karma colors (Color 0, 1, 2) directly into TM FIFO hardware queues.

### 3.4 Data Flow Description
When a TCP packet arrives, the switch:
1. Validates standard Headers and maps IP/Ports to a 16-bit hash.
2. Queries the fast-SRAM register for `flow_bytes` and `flow_karma`.
3. Checks if incoming `flow_bytes` + new payload size exceeds `BYTE_THRESHOLD`.
4. Executes the KBCS penalty or reward subroutine based on threshold deviation.
5. Emits the packet to an appropriate software/hardware buffer in the TM.

### 3.5 API Structure
- **Data Plane API (P4 Runtime)**: Used implicitly to manage table rule insertions.
- **Command & Control API (`upload_and_run.py`)**: Remote execution facade that interfaces with standard SSH/SCP pipelines.

### 3.6 External Integrations
- Bound locally to Linux TC (Traffic Control) primitives managed automatically by Mininet's `TCLink`.
- Bound externally to `iperf3` utility frameworks for metric ingestion and automated JSON log rendering.

---

## 4. Functional Requirements

### 4.1 Numbered Requirements
- **FR-1**: The system must extract Ethernet, IPv4, and TCP protocol headers from incoming packets.
- **FR-2**: The system must generate a 16-bit flow hash using Source IP, Dest IP, Source Port, Dest Port, and Protocol as input seeds.
- **FR-3**: The system must track per-flow transmission volume using a persistent register (`flow_bytes`).
- **FR-4**: The `flow_bytes` value must decay exponentially on packet arrival (`flow_bytes = flow_bytes - (flow_bytes >> 3) + packet_size`) to simulate a sliding temporal window without real-time clocks.
- **FR-5**: The system must enforce a Karma ceiling of `100` and a Karma floor of `1` for all active flows.
- **FR-6**: If `flow_bytes` exceeds `4500` (BYTE_THRESHOLD), the system must penalize the flow's Karma by `20` units.
- **FR-7**: If `flow_bytes` is below or equal to the threshold, the system must reward the flow's Karma by `1` unit.
- **FR-8**: The system must categorize flows as GREEN (Karma > 80), YELLOW (Karma > 50), or RED (Karma <= 50).
- **FR-9**: The system must actively drop packets (AQM) belonging to a RED flow if its Karma drops exactly to or below `20` (PENALTY limit).
- **FR-10**: On AQM packet drop, the system must manually rest the aggressive flow’s `flow_bytes` array to `0` to permit TCP retransmission escape phases.

### 4.2 Validation rules
- Packets that are non-TCP (e.g., ICMP Ping, ARP) must bypass the Karma assignment algorithm and immediately undergo Level-3 routing logic to avoid accidental link disruption.

### 4.3 Error handling requirements
- In instances of TCP retransmission flooding, the dropping function explicitly intercepts and logs the event structurally within Mininet virtual traces.
- If SSH deployment fails, `upload_and_run.py` triggers an immediate termination (`sys.exit(1)`) capturing standard error variables securely.

### 4.4 State transitions
- **Uninitialized → Active**: Registers return `0`. Switch initializes `karma = 100`.
- **Active → Demoted**: Continuous polling of excessive traffic thresholds triggers a sharp downgrade to RED state. 
- **Demoted → Trusted**: Continued slow polling of sparse TCP ACKs allows gradual incrementing (+1) to navigate back into YELLOW, then GREEN.

---

## 5. Non-Functional Requirements

### 5.1 Performance requirements
- The P4 switch logic must compute the entire Karma assessment block within the minimal instruction threshold allowable by the ASIC (or software emulation equivalent).
- State read/write mechanisms must happen in O(1) time complexity per packet.

### 5.2 Scalability
- Must natively process up to `65,536` concurrent unique network flows simultaneously leveraging built-in SRAM limits. Hardware upgrades scale memory indices up exclusively to hardware allowances.

### 5.3 Reliability
- System routing states must prevent silent catastrophic failure scenarios (routing black holes). Handled gracefully by the fail-open policy configured on missing lookup indices.

### 5.4 Maintainability
- P4 modules are explicitly decoupled (`headers.p4`, `parser.p4`, `ingress.p4`) allowing modular architectural revisions without impacting root Karma logic.

### 5.5 Usability
- Execution runs entirely via a single terminal entry `python3 upload_and_run.py`, automating cleaning, building, and benchmarking execution processes end-to-end.

---

## 6. Data Requirements

### 6.1 Data schema & Storage
- **`flow_bytes`**: `Register<bit<32>>[65536]`. Tracks accumulated decayed byte payload.
- **`flow_karma`**: `Register<bit<16>>[65536]`. Tracks assigned credit score metric.

### 6.2 Data formats
- Data evaluation relies on standard IEEE 802.3 and RFC 791/793 frame encapsulations. No custom overlay encapsulation is inherently added, retaining backwards compatibility with edge systems.

### 6.3 Backup and recovery requirements
- Runtime test topologies are completely ephemeral; there is no persistent storage schema outside of the transient hardware registers which are purposefully scrubbed between reboot lifecycles.

---

## 7. Interface Requirements

### 7.1 User Interface
- Output logs from `iperf3` are directly printed via STDOUT onto CLI boundaries detailing final Jain's Fairness Index derivations and discrete transfer metrics. 

### 7.2 Hardware Interface
- Compatible strictly via standard `v1model` architectures, primarily mapped against the Intel Tofino ASIC abstractions and BMv2 architectures.

### 7.3 Software Interface
- Linux capabilities interface extensively to alter core congestion stacks (`sysctl net.ipv4.tcp_congestion_control`).

### 7.4 Communication Interface
- SSH/SCP port `2222` utilized strictly in emulation layers targeting local loopback VM boundaries (`localhost`). 

---

## 8. System Models

### 8.1 Use Case System Context
1. **Developer Execution**: User runs python framework → Framework SSHes into VM → Automates compilation phases → Begins Mininet emulator → Connects Hosts → Benchmarks traffic schemas → Extracts fairness matrices.

### 8.2 Sequence descriptions (Dataplane Engine)
1. **Event**: TCP Data packet arrives at P4 parser hook.
2. **Action 1**: Parser forwards to Ingress hook; `HashManager` isolates ID based on UDP/TCP source metrics.
3. **Action 2**: ALU requests fast-read block of ID metadata.
4. **Decision Block**: Validate packet volume increment against internal `decay_multiplier`. 
5. **Action 3**: Increment/Decrement integer states synchronously.
6. **Action 4**: Annotate local processing hooks with egress mapped queues. Forward to Traffic Manager.

---

## 9. Deployment Architecture

### 9.1 Environment setup
- Primary build targets must be Ubuntu-based machines (e.g., Ubuntu 20.04/22.04) running native support for user-space P4 execution binaries (`p4c`, `simple_switch`, `simple_switch_CLI`).
- Topology requirements mandate Mininet and associated kernel network isolated namespace architectures.

### 9.2 CI/CD considerations
- The core artifact `upload_and_run.py` replaces continuous delivery pipelines by actively flushing `.json` runtime payloads to staging hardware directly prior to compilation bindings.

### 9.3 Dependency management
- Target virtual environments necessitate python dependencies strictly bounded to `paramiko`, `scp`, `mininet`, alongside `iperf3` networking toolsets.

---

## 10. Risk Analysis

### 10.1 Technical risks
- **Hash Collision**: The 16-bit array restricts states to 65k addresses. Heavily congested external backbones may invoke Pigeonhole principles where aggressive flows erroneously punish stable neighbors residing on shared hash spaces. 
- **Timer Drift**: Lacking explicit hardware wall-clocks within P4 forces decay implementations bound exclusively to temporal influxes. Senders transmitting excessively slow might artificially retain large penalty pools implicitly due to lacking clock cycles capable of scrubbing them.

### 10.2 Mitigation strategies
- Employ Cuckoo hashing models on subsequent system enhancements to bypass collision frequencies linearly.
- Implement explicit packet-delay annotations on header tags dynamically mapped to TTL modifications validating elapsed time matrices against core payload frames.

---

## 11. Future Enhancements

- Integration of ECN (Explicit Congestion Notification) metadata bindings to augment AQM (Active Queue Management) dropping cycles.
- Expansion of the `REG_SIZE` parameter leveraging multidimensional indexing on contemporary scalable architectures.
- Extension of framework schemas to natively ingest UDP/QUIC streams inherently bypassing legacy payload interpretations.

---

## 12. Appendix

### 12.1 Folder structure mapping
- `kbcs/p4src/*`: Dataplane P4 Logic blocks.
- `kbcs/topology.py`: Simulated Testbed logic block.
- `KBCS_Enhanced_Design_Document.md`: Finalized documentation.
- `upload_and_run.py`: Staging environment launcher.

### 12.2 Glossary
- **Karma**: Discrete integer valuation characterizing normalized flow behaviors.
- **Fair Share**: The equitably divided maximum bandwidth allowed linearly between independent TCP streams bounded across a finite singular medium.
