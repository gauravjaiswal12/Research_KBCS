# Weekly Progress Report — KBCS PFQ Implementation
**Date:** April 16, 2026
**Project:** Karma-Based Congestion Control System (KBCS) in P4

## 1. Priority Queue Concept Implemented
We successfully implemented the priority queueing architecture exactly as required by mapping traffic into the switch's 8 hardware priority queues. Because Active Queue Management (AQM) at the `Ingress` pipeline could not accurately read queue congestion, we had to build a custom `MyEgress` pipeline. Within this custom pipeline, we read the exact `enq_qdepth` and combined it with our Karma algorithm. GREEN traffic is mapped strictly to High Priority (Queue 7), while penalized RED traffic is quarantined in Low Priority (Queue 0). This physical hardware queue separation completely fulfills the priority queue requirement from the PFQ baseline.

## 2. Multi-Host Communication Established
The core Mininet topology is fully functional. We have successfully deployed a 4-host, 3-switch topology (Access & Aggregation switches using IPv4 routing) where multiple hosts run independent TCP streams (`iperf`) that successfully cross paths and compete at a central bottleneck link. 

## 3. Network Metrics Implementation
We successfully developed a real-time observation dashboard using Python, Dash, and the P4 Thrift API. The following network health and fairness metrics are actively computed and graphed in real-time:
*   **Jain’s Fairness Index (JFI):** Computed dynamically based on windowed flow throughput.
*   **Packet Drop Ratio & Buffer Occupancy:** Computed directly from P4 egress registers.
*   **Link Efficiency / Utilization:** Analyzed to determine exact bottleneck pressure.
*   **Karma Dynamics:** Visual graphing of the independent flow penalties over time.

## 4. Implementation of PFQ Paper Ideas & Emulation Challenges
The foundational idea of the Proactive Fair Queueing (PFQ) paper has been written into standard P4 (`kbcs_v2.p4`) and successfully wired to a Reinforcement Learning (Q-Learning) parameter agent. 

**Implementation Challenge: The TCP Latency Illusion**
While the mathematical PFQ drops trigger successfully, we encountered a well-documented challenge regarding software-emulated networks (Mininet + BMv2). P4 processing in a simulated CPU environment introduces significant round-trip latency (~40 ms). Because standard TCP calculates its maximum window limit based on latency, our Congestion Control Algorithms (CCAs) voluntarily throttled themselves, preventing 10 Mbps links from ever fully congesting. 

To prove PFQ works functionally without skewing the CCAs:
1.  **Scaled Evaluation:** We successfully scaled the bottleneck link to 3 Mbps to induce accurate queue buildups and observe PFQ dropping mechanics accurately.
2.  **Future Solution (Time Dilation):** To evaluate at 100 Mbps in software, it would require **Time Dilation** (slowing down the Linux VM clock so CPU delays appear instantaneous to TCP). We are documenting this emulation constraint mathematically as a limitation of software research vs. physical P4 Tofino hardware.

## 5. Topological Testing (Deferred)
Testing the algorithm across multiple diverse topologies (Fat-Tree, Leaf-Spine, Dumbbell) has been deferred. It will be the final step executed once the core PFQ and RL parameter tuning behaviors are finalized on the current baseline topology.
