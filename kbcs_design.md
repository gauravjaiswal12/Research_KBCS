# Karma-Based Credit Scheduler (KBCS) Design

This document details the packet pipeline and implementation strategy for the Karma-Based Credit Scheduler (KBCS).

## 1. Packet Pipeline Flowchart

The following diagram illustrates the complete life cycle of a packet in the KBCS system, from the Sender to the Receiver.

```mermaid
graph TD
    %% Nodes
    Sender[Sender (Host)]
    SwitchIngress[Switch Ingress Pipeline]
    SwitchTM[Switch Traffic Manager]
    SwitchEgress[Switch Egress Pipeline]
    Bottleneck[Bottleneck Link]
    Receiver[Receiver (Host)]

    %% Sub-components
    subgraph SenderSide [Sender Logic]
        Gen[Packet Generation]
        CC[Congestion Control (Cubic/BBR)]
    end

    subgraph Switch [P4 Switch Architecture]
        subgraph Ingress [Ingress Pipeline]
            Parser[Parser]
            Classify[Flow Classification]
            Meter[Rate Measurement]
            KarmaLogic[Karma Update Logic]
            QMap[Queue Mapping]
        end
        
        subgraph TM [Traffic Manager]
            QGold[Gold Queue (Hi-Prio)]
            QSilver[Silver Queue (Med-Prio)]
            QBronze[Bronze Queue (Lo-Prio)]
            Scheduler[Weighted Round Robin (WRR)]
        end
        
        subgraph Egress [Egress Pipeline]
            Rewrite[Header Rewrite]
            Deparser[Deparser]
        end
    end

    %% Flow
    Sender -->|Packet enters network| Switch
    
    %% Inside Switch
    Switch --> Parser
    Parser --> Classify
    Classify --> Meter
    Meter --> KarmaLogic
    KarmaLogic -->|Assign Queue ID| QMap
    
    QMap -->|Enqueue| TM
    TM -->|Wait in specific queue| Scheduler
    Scheduler -->|Dequeue based on weights| Egress
    
    Egress -->|Serialize| Bottleneck
    Bottleneck -->|Transmission Delay| Receiver
    
    Receiver -->|ACK/SACK| Sender
```

## 2. Detailed Packet Life Cycle

### A. Sender Side
1.  **Generation**: The application generates data.
2.  **Congestion Control**: The Transport Layer (TCP/QUIC) determines *when* to send the packet based on its window (CWND) and pacing rate.
    *   *Note*: KBCS works by influencing this step indirectly. By delaying or dropping packets from aggressive flows (like CUBIC) in the switch, KBCS forces the sender's CC algorithm to slow down.

### B. Switch Ingress (The "Brain")
This is where the KBCS logic resides.
1.  **Parser**: Extracts headers (Ethernet, IP, TCP) to identify the flow.
2.  **Flow Classification**: The switch hashes the 5-tuple (SrcIP, DstIP, SrcPort, DstPort, Proto) to get a `Flow_ID`.
3.  **State Retrieval**:
    *   Read `Flow_Rate` (from a Meter or counter).
    *   Read `Current_Karma` (from a Register array).
    *   Read `Global_Queue_Depth` (intrinsic metadata).
4.  **Karma Update Logic**:
    *   If `Queue_Depth > Threshold` AND `Flow_Rate > Fair_Share`:
        *   **Decrease Karma** (e.g., `Karma -= 5`). (Bad feedback).
    *   Else:
        *   **Increase Karma** (e.g., `Karma += 1`). (Good feedback).
5.  **Queue Mapping**:
    *   Identify the queue based on the *new* Karma score:
        *   **Gold**: Karma > 80
        *   **Silver**: 40 < Karma <= 80
        *   **Bronze**: Karma <= 40
    *   Set `monitor.queue_id` or `standard_metadata.egress_spec` to the physical queue index.

### C. Traffic Manager (The "Waiting Room")
This is hardware-managed buffering.
1.  **Apportioning**: The packet is placed into the specific FIFO queue assigned in the Ingress.
2.  **Waiting**:
    *   **Gold Queue**: Packets here wait very little because this queue has high weight/priority.
    *   **Bronze Queue**: Packets here wait longer. If the link is congested, these packets are drained slowly.
3.  **Scheduling**: The Scheduler (likely Weighted Round Robin or Strict Priority) picks the next packet to send.
    *   *Example Weights*: Gold (64) : Silver (16) : Bronze (1).
    *   For every 1 packet picked from Bronze, 64 are picked from Gold (if available).

### D. Bottleneck Link
1.  **Serialization**: The packet acts as a signal on the wire.
2.  **Propagation**: Physically travels to the next hop.
3.  This is the *physical constraint* we are managing. The sum of all queues cannot exceed this link's capacity.

### E. Receiver Side
1.  **Ack Generation**: Receiver gets the packet and sends an ACK.
2.  **Feedback Loop**: The ACK travels back to the Sender.
    *   If the packet was delayed in the Bronze queue, the **RTT** (Round Trip Time) increases.
    *   The Sender sees higher RTT and (hopefully) slows down.
    *   If the packet was dropped (AQM in Bronze queue), the Sender sees a Loss event and reduces CWND immediately.

## 3. Implementation Mapping in P4 Switch

| Component | P4 Architecture Block | Implementation Details |
| :--- | :--- | :--- |
| **Flow ID** | **Ingress** | `hash(flow_hash, {hdr.ipv4.src...}, 16w0, 16w65535)` |
| **Karma State** | **Ingress** | `register<bit<16>>(65536) karma_scores;` |
| **Rate Monitor** | **Ingress** | `meter(65536, PacketColor) flow_meter;` |
| **Logic** | **Ingress Control** | `apply { if (meter == RED) karma.write(idx, old - 5); ... }` |
| **Queue Select** | **Ingress Control** | `if (karma > 80) standard_metadata.egress_spec = Q_GOLD;` |
| **Queues** | **Traffic Manager** | *Configured via control plane (runtime_CLI or switch config)*. Map Queue 0->Bronze, Queue 1->Silver, Queue 2->Gold. |
| **Scheduler** | **Traffic Manager** | *Configured via control plane*. Set WRR weights or Priority levels. |

## 4. Congestion Analysis

### Where exactly does Congestion happen?
Congestion occurs **physically** in the **Traffic Manager (TM)**, specifically at the **Egress Queue** of the output port.

*   **Scenario**: Imagine a funnel.
    *   **Wide Input**: Current traffic from all sources (e.g., 40Gbps).
    *   **Narrow Output**: The bottleneck link (e.g., 10Mbps).
    *   **Result**: The liquid (packets) backs up in the funnel (queue).
    *   **The Problem**: The **Traffic Manager** buffer fills up because packets arrive faster than they can leave.

### How do we Detect it? (The "Look Ahead")
Although congestion *happens* in the Traffic Manager (Physical Queue), the Ingress Pipeline needs to know about it *before* sending the packet there.

*   **The Mechanism**: **Intrinsic Metadata**.
    *   Switch ASICs (like Tofino or BMv2 simple_switch) have internal wires that connect the Traffic Manager back to the Ingress Parser.
    *   When a packet arrives, the hardware automatically populates a metadata field with the **current depth** of the target queue.
*   **The Specific Variable**:
    *   In P4 (BMv2), this is `standard_metadata.enq_qdepth`.
    *   This variable tells us: *"If you send this packet to Queue X right now, it will be the Nth packet in line."*
*   **The Logic**:
    *   We compare this `enq_qdepth` against a constant `THRESHOLD` (e.g., 800 packets).
    *   `bool is_congested = (standard_metadata.enq_qdepth > THRESHOLD);`
    *   If sensitive, we can also use **Egress Queue Depth** (if available) or **Port Utilization**, but `sojourn_time` or `enq_qdepth` are the standard metrics.

## 5. The Physics of Buffer Contention

### A. The Journey: From Switch to Wire
How does a packet physically leave the switch?

1.  **Ingress Pipeline (The Brain)**:
    *   Decides *where* the packet goes (e.g., Output Port 5).
    *   Sets `standard_metadata.egress_spec = 5`.

2.  **Traffic Manager (The Waiting Room)**:
    *   This is the **Buffer Memory**.
    *   The packet is stored in a specific queue (e.g., Queue 0, 1, or 2) attached to Port 5.
    *   **Crucial**: If the link is busy sending another packet, *this* packet must wait here.

3.  **Scheduler (The Bouncer)**:
    *   This hardware logic decides *who leaves next*.
    *   It looks at all queues (Gold, Silver, Bronze) and picks one packet based on the algorithm (Strict Priority or Weighted Round Robin).
    *   Example: "I send 10 packets from Gold, then 1 from Bronze."

4.  **Egress Pipeline (The Last Check)**:
    *   The packet is read from memory and modified one last time (e.g., decrement TTL).

5.  **Serializer (The Door)**:
    *   The packet is converted from bits in memory to electrical signals on the wire.
    *   **Bottleneck**: This door has a fixed speed (e.g., 10 Gigabits/sec). It can only push 1 bit at a time. This physical limit is why queues build up in step 2.

### B. The Battle Royale: CUBIC vs. BBR
Where do they fight? They fight in the **Traffic Manager Buffer**.

*   **CUBIC's Strategy**: "I will increase my rate until I see a packet drop."
    *   **Effect**: It fills the buffer (Queue 0) completely. It *needs* the buffer to be full to know it has reached the limit.
*   **BBR's Strategy**: "I will estimate the bandwidth and RTT, and send exactly that amount."
    *   **Effect**: It tries to keep the buffer empty (just enough for the pipe).
*   **The Conflict**:
    *   If they share a queue (FIFO), CUBIC fills it up.
    *   BBR packets arrive and find a full queue (created by CUBIC).
    *   BBR packets experience **Bufferbloat** (high latency) or **Drop** (if queue is 100% full).
    *   **Result**: CUBIC bullies BBR, starving it of bandwidth.

**KBCS Solution**: We separate them *before* the fight starts. CUBIC goes to the "Penalty Box" (Bronze Queue), while BBR stays in Gold/Silver.

## 6. The Karma Algorithm: Detailed Logic

This section defines exactly *how* we calculate the credit score.

### A. The Variables (What we track)
We maintain state for every flow in the **Ingress Pipeline** using P4 Registers.

| Variable Name | Type | Description |
| :--- | :--- | :--- |
| `Use_Karma` | **State** (Register) | The current credit score of the flow. Range: 0-100. Starts at 100 (Max). |
| `Flow_Rate` | **Input** (Meter) | The estimated bandwidth usage of this flow. |
| `Queue_Depth` | **Input** (Metadata) | The current fill level of the bottleneck queue. |
| `Last_Update` | **State** (Register) | Timestamp of the last Karma change (to prevent flapping). |

### B. The Parameters (Tunable Constants)
These are "knobs" we can turn to tune the system's sensitivity.

*   `CONGESTION_THRESHOLD`: **80%** (If Queue > 80%, we are congested).
*   `FAIR_SHARE_RATE`: **2 Mbps** (Example: Link Capacity / Number of Flows).
*   `PENALTY_VALUE`: **5 points** (How much Karma to lose for bad behavior).
*   `REWARD_VALUE`: **1 point** (How much Karma to gain for good behavior).

### C. The Logic (The Algorithm)
For every packet `P` arriving at Ingress:

```python
# 1. Get Inputs
current_qdepth = standard_metadata.enq_qdepth
flow_rate = meter.read(flow_id)
current_karma = register_karma.read(flow_id)

# 2. Check for Congestion
is_congested = (current_qdepth > CONGESTION_THRESHOLD)

# 3. Check for Aggression
# Meter returns Green (Low), Yellow (Medium), Red (High)
is_aggressive = (flow_rate == RED) # Sending > Fair Share

# 4. Update Karma
if is_congested AND is_aggressive:
    # CRITICAL: Punishment
    # We penalize aggressive flows ONLY when the network is congested.
    new_karma = current_karma - PENALTY_VALUE
else:
    # RECOVERY: Redemption
    # If the network is fine OR the flow is behaving (even if network is busy),
    # we slowly forgive it.
    new_karma = current_karma + REWARD_VALUE

# 5. Clamping (Keep within bounds 0-100)
new_karma = min(100, max(0, new_karma))

# 6. Apply Decision
register_karma.write(flow_id, new_karma)
```

### D. Why Asymmetric? (-5 vs +1)
We use a **"Fast Drop, Slow Rise"** strategy.
*   **Safety**: If a flow causes damage (congestion), we must stop it *immediately*. A -5 penalty quickly demotes it to Bronze.
*   **Stability**: If we forgave it too quickly (+5), it would jump right back to Gold, cause congestion again, and oscillate. Slow recovery (+1) forces the flow to *prove* it can be stable for a longer time.

## 7. The Feedback Loop: How Senders Learn
The switch doesn't talk to the Sender directly. It uses the **Receiver's ACKs** as a messenger.

### A. The Signal (What the Switch does)
*   **In Bronze Queue**: Packets are **delayed** (high latency) or **dropped** (if queue full).
*   **In Gold Queue**: Packets pass through quickly (low latency).

### B. The Messenger (The Receiver)
*   **On Receipt**: The Receiver gets the packet.
*   **On Delay**: It sends an ACK immediately. If the packet arrived late, the ACK is generated late.
    *   *Result*: The **RTT (Round Trip Time)** calculated by the Sender increases.
*   **On Drop**: The Receiver notices a "hole" in the sequence numbers (e.g., got 1, 2, 4... missing 3).
    *   *Result*: It sends **Duplicate ACKs (Dup-Acks)** or **SACKs** saying "I missed packet #3".

### C. The Learner (The Sender's Algorithm)
1.  **CUBIC (Loss-Based)**:
    *   **Trigger**: Receives 3 Duplicate ACKs (signaling Packet Loss).
    *   **Reaction**: "Ouch! I hit the limit."
    *   **Action**: Multiplicative Decrease. It cuts its **CWND (Congestion Window)** by **30%**.
    *   *KBCS Effect*: The aggressive flow slows down significantly.

2.  **BBR (Model-Based)**:
    *   **Trigger**: Does NOT cut rate on random loss. It monitors **RTT** and **Delivery Rate**.
    *   **Reaction to Delay**: "RTT is increasing, so the pipe is full."
    *   **Action**: It stops increasing its pacing rate. It tries to convert "In-flight data" to match the Bandwidth-Delay Product (BDP).
    *   *KBCS Effect*: The high latency in Bronze Queue tells BBR "the path is congested," preventing it from pushing harder.

## 8. Crucial Hardware Realities (Implementation Details)
To make this work on a real P4 switch (Tofino/BMv2), we must respect hardware constraints.

### A. Atomicity (Read-Modify-Write)
*   **Challenge**: P4 programs run in parallel pipelines. If two packets from the same flow arrive at the same time, they might read the same extensive `Old_Karma`, modify it, and write it back, causing a "Race Condition".
*   **HW Solution**: **Atomic ALU blocks**. In P4, Register operations (Read -> Modify -> Write) happen in a **single atomic transaction** within the ALU.
    *   *Implication*: We don't need locks. The hardware guarantees consistency.

### B. Memory Persistence
*   **Metadata**: Exists only for the lifetime of one packet. (Ephemeral).
*   **Registers**: Exist forever (until reboot). (Persistent).
    *   *Usage*: We MUST store `Karma` and `Last_Update_Time` in **Registers**. We cannot pass them as metadata because we need to remember the flow's history for the *next* packet.

### C. Hash Collisions
*   **Problem**: We map 5-tuple (IPs, Ports) to a Register Index (e.g., 65536 slots). Two different flows might hash to the same index.
*   **Reality**: In KBCS, we accept this. If two flows collide, they share the Karma score. A "bad" flow might punish a "good" unlucky flow.
    *   *Mitigation*: Use a large enough register array (e.g., 65k or 131k slots) to minimize probability. Or use "Cuckoo Hashing" (complex). For this project, **Simple Hashing** is sufficient.
