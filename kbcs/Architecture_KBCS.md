# KBCS System Architecture
Below is the system architecture of the enhanced Karma-Based Congestion Signaling (KBCS) Phase 3 platform, outlining data plane mechanics and external observability features.

```mermaid
graph TD
    classDef host fill:#e1f5fe,stroke:#01579b,stroke-width:2px;
    classDef p4 fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    classDef ext fill:#fff3e0,stroke:#e65100,stroke-width:2px;
    
    subgraph Clients
        H1["Host 1: CUBIC<br>(Aggressive)"]:::host
        H2["Host 2: BBR<br>(Model-Based)"]:::host
    end
    
    subgraph "BMv2 P4 Switch (KBCS Data Plane)"
        Parser["Parser<br>(Extracts TCP/IP)"]:::p4
        
        subgraph "Ingress Control"
            State["State Lookup<br>(Karma, Bytes, Time)"]:::p4
            Engine["Karma Engine<br>(Penalty/Reward)"]:::p4
            E5["E5: Stochastic Drop"]:::p4
            E6["E6: Momentum Track"]:::p4
            E7["E7: Slow-Start Leniency"]:::p4
            E8["E8: Idle Recovery"]:::p4
            E10["E10: Clone/Mirror"]:::p4
        end
        
        TM["Traffic Manager<br>(3 Priority Queues)"]:::p4
        
        subgraph "Egress Control"
            E1["E1: ECN Marking<br>(Yellow Flows)"]:::p4
            E9["E9: INT Telemetry<br>(kbcs_telemetry_t)"]:::p4
        end
        
        Parser --> State --> Engine
        Engine -.-> E6
        Engine -.-> E7
        Engine -.-> E8
        Engine --> E5
        E5 --> E10
        E10 --> TM
        TM --> E1
        E1 --> E9
    end
    
    subgraph Observability
        S1["simple_switch_CLI"]:::ext
        M1["metrics_exporter.py<br>(E11 Data Polling)"]:::ext
        CSV["karma_log.csv"]:::ext
        GIF["plot_animated_karma.py<br>(E12 Visualization)"]:::ext
    end
    
    subgraph Server
        H3["Host 3<br>(iperf3 receiver)"]:::host
    end
    
    H1 -->|100 Mbps| Parser
    H2 -->|100 Mbps| Parser
    E9 -->|10 Mbps Bottleneck| H3
    
    Engine -.->|reg_karma| S1
    S1 --> M1
    M1 --> CSV
    CSV --> GIF
```

### Module Descriptions
- **Karma Engine:** Computes proportional penalties dynamically based on throughput.
- **E5 (Stochastic Drop):** Flattens TCP synchronization crashes using random drops.
- **E6 (Momentum):** Punishes rapidly decaying karmas.
- **E7 (Slow-Start Leniency):** Grants 20-packet immunity for TCP handshakes.
- **E8 (Idle Recovery):** Escapes starvation deadlocks post-timeout.
- **E9 (INT):** Appends local metadata securely to cloned egress packets.
- **E11 + E12 (Telemetry Export):** Automates the visual rendering of complex queuing battles across different bottlenecks.
