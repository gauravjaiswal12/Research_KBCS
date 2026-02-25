# KBCS Implementation Plan (Linux/Ubuntu)

**Crucial Note**: P4 development (compiling `p4c`, running `mininet`, using `bmv2`) **REQUIRES Linux**. You should switch to your Ubuntu environment to execute this plan.

## 1. Project Directory Structure
We will create this structure in your Ubuntu workspace.

```text
kbcs_project/
├── p4src/
│   ├── kbcs.p4            # INTENT: The main P4 program
│   └── headers.p4         # INTENT: Protocol headers definition
├── control/
│   └── kbcs_controller.py # INTENT: Python Control Plane (Populate tables, Read registers)
├── topo/
│   ├── topology.json      # INTENT: Mininet topology definition
│   └── s1-runtime.json    # INTENT: Initial table entries (ARP, basic forwarding)
├── utils/
│   ├── mininet_lib.py     # INTENT: Helper scripts for Mininet
│   └── receive.py         # INTENT: Sniffer to verify packets
└── Makefile               # INTENT: Single command build system
```

## 2. Step-by-Step Implementation Strategy

### Phase 1: The Skeleton (Basic Forwarding)
*Goal: Get packets moving from Host A to Host B.*
1.  **Define Headers**: Ethernet, IPv4, TCP (in `headers.p4`).
2.  **Parser**: Parse Eth -> IP -> TCP.
3.  **Ingress**: Implement Basic L3 Forwarding table (`ipv4_lpm`).
4.  **Deparser**: Emit headers.
5.  **Verify**: Ping between hosts in Mininet.

### Phase 2: The Brain (Karma Logic)
*Goal: Implement the credit system.*
1.  **Registers**: Define `karma_register` (width 16, size 65536).
2.  **Meters**: Define `rate_meter` to color packets (Green/Yellow/Red).
3.  **Ingress Logic**:
    *   Read `standard_metadata.enq_qdepth`.
    *   Read Meter result.
    *   Update Register: `if (congested & red) karma -= 5; else karma += 1;`
4.  **Queue Mapping**:
    *   Add logic: `if (karma > 80) egress_queue = 2; else egress_queue = 0;`

### Phase 3: The Environment (Mininet & Traffic)
*Goal: Create the contention scenario.*
1.  **Topology**: 1 Switch, 2 Senders (h1, h2), 1 Receiver (h3).
2.  **Bottleneck**: Set link bandwidth `s1 <-> h3` to **10 Mbps**.
3.  **Traffic Gen**:
    *   **h1 (Aggressor)**: Use `iperf3` with CUBIC (default).
    *   **h2 (Victim)**: Use `iperf3` with BBR (or fragile flow).

### Phase 4: Verification (The Proof)
*Goal: Measure fairness.*
1.  **Without KBCS**: Run 10Mbps bottleneck. Observe h1 getting 9Mbps, h2 getting 1Mbps.
2.  **With KBCS**: Run same test. Observe h1 getting demoted to Bronze results in Fairness (e.g., 5Mbps each).

## 3. Next Steps (In Ubuntu)
1.  Ensure you have **P4 Utils** or **P4 Tutorial VM** installed.
2.  Create the folder `kbcs_project`.
3.  Start with **Phase 1**.

I (Antigravity on Ubuntu) can help you write the code for each of these files once you are there.
