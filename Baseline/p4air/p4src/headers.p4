/* =============================================================================
 * headers.p4 — P4air Header Definitions, Metadata, and Register Arrays
 * =============================================================================
 * Defines all packet headers (Ethernet, IPv4, TCP), P4air-specific custom
 * metadata for fingerprinting/reallocation/actions, and stateful register
 * arrays that persist across packets in BMv2 simple_switch.
 * =========================================================================== */

#ifndef _P4AIR_HEADERS_P4_
#define _P4AIR_HEADERS_P4_

/* =============================================================================
 * Type Aliases — for readability and consistency
 * =========================================================================== */
typedef bit<9>  egressSpec_t;   /* BMv2 egress port width (9 bits = 512 ports) */
typedef bit<48> macAddr_t;      /* Ethernet MAC address (6 bytes) */
typedef bit<32> ip4Addr_t;      /* IPv4 address (4 bytes) */

/* =============================================================================
 * Tunable Constants — control P4air's behavior
 * These are the primary knobs from the P4air paper (Section IV-B).
 * =========================================================================== */

/* --- Flow table sizing --- */
#define FLOW_TABLE_SIZE  1024   /* Max concurrent flows to track (2^10)       */

/* --- Queue configuration --- */
#define NUM_QUEUES       8      /* Total queues per port (BMv2 --priority-queues 8) */
#define NUM_GROUPS       6      /* ant, mice, delay, loss-delay, loss, model  */

/* --- Group IDs ---
 * These IDs map flows to conceptual groups.
 * ant/mice are short-lived; the rest are long-lived CCA groups.
 */
#define GROUP_ANT         0     /* Very short sparse flows (ARP, DNS, DHCP)   */
#define GROUP_MICE        1     /* TCP flows still in slow-start phase        */
#define GROUP_DELAY       2     /* Delay-based CCAs (e.g., Vegas, LoLa)       */
#define GROUP_LOSS_DELAY  3     /* Loss+delay CCAs (e.g., Illinois, YeAH)     */
#define GROUP_LOSS        4     /* Purely loss-based CCAs (e.g., Cubic, Reno) */
#define GROUP_MODEL       5     /* Model-based CCAs (e.g., BBR)               */

/* --- Fingerprinting thresholds (Paper Section IV-B) ---
 * mLD: # of RTT intervals with continuous queue growth before
 *      reclassifying a delay-based flow as loss-delay.
 * mPL: # of RTT intervals before reclassifying as purely loss-based (mPL > mLD).
 * mM:  # of periodic BW probing patterns before classifying as model-based (BBR).
 */
#define M_LD              4     /* delay → loss-delay transition threshold    */
#define M_PL              12    /* loss-delay → purely-loss transition        */
#define M_M               4     /* model-based detection threshold            */

/* --- TCP flag bits (within the 6-bit 'ctrl' field) --- */
#define TCP_FLAG_SYN      6w0x02  /* SYN flag for connection establishment    */
#define TCP_FLAG_ACK      6w0x10  /* ACK flag                                */
#define TCP_FLAG_SYNACK   6w0x12  /* SYN+ACK combined                        */

/* =============================================================================
 * Standard Packet Headers
 * =========================================================================== */

/* Ethernet frame header — always the outermost header */
header ethernet_t {
    macAddr_t dstAddr;       /* Destination MAC address */
    macAddr_t srcAddr;       /* Source MAC address      */
    bit<16>   etherType;     /* Payload type: 0x0800=IPv4, 0x0806=ARP */
}

/* IPv4 packet header — parsed when etherType == 0x0800 */
header ipv4_t {
    bit<4>    version;       /* IP version (always 4)               */
    bit<4>    ihl;           /* Internet Header Length (in 32-bit words) */
    bit<8>    diffserv;      /* DSCP + ECN bits                     */
    bit<16>   totalLen;      /* Total packet length (header + data) */
    bit<16>   identification;/* Fragment identification             */
    bit<3>    flags;         /* Fragment flags (DF, MF)             */
    bit<13>   fragOffset;    /* Fragment offset                     */
    bit<8>    ttl;           /* Time to live (hop count)            */
    bit<8>    protocol;      /* Next protocol: 6=TCP, 17=UDP       */
    bit<16>   hdrChecksum;   /* Header checksum                     */
    ip4Addr_t srcAddr;       /* Source IP address                   */
    ip4Addr_t dstAddr;       /* Destination IP address              */
}

/* TCP segment header — parsed when protocol == 6 */
header tcp_t {
    bit<16> srcPort;         /* Source port number                  */
    bit<16> dstPort;         /* Destination port number             */
    bit<32> seqNo;           /* Sequence number                     */
    bit<32> ackNo;           /* Acknowledgement number              */
    bit<4>  dataOffset;      /* Header length (in 32-bit words)     */
    bit<3>  res;             /* Reserved bits                       */
    bit<3>  ecn;             /* ECN-Nonce, CWR, ECE flags           */
    bit<6>  ctrl;            /* URG, ACK, PSH, RST, SYN, FIN flags */
    bit<16> window;          /* Receiver window size (Apply Actions target) */
    bit<16> checksum;        /* TCP checksum                        */
    bit<16> urgentPtr;       /* Urgent pointer                      */
}

/* The struct of all parsed headers — passed through the pipeline */
struct parsed_headers_t {
    ethernet_t ethernet;
    ipv4_t     ipv4;
    tcp_t      tcp;
}

/* =============================================================================
 * P4air Custom Metadata
 * =============================================================================
 * Carries per-packet state through the ingress/egress pipeline.
 * Populated by the fingerprinting logic, consumed by reallocation and actions.
 * =========================================================================== */
struct p4air_metadata_t {
    /* ---- Flow Identification ---- */
    bit<16> flow_id;              /* Hash of 5-tuple → index into registers */

    /* ---- Flow Classification ---- */
    bit<3>  flow_group;           /* Current group (GROUP_ANT ... GROUP_MODEL) */
    bit<3>  prev_group;           /* Previous group before reclassification   */
    bit<1>  group_changed;        /* 1 if group was just reclassified         */
    bit<1>  is_recirculated;      /* 1 if this packet was recirculated        */

    /* ---- RTT Tracking ---- */
    bit<48> rtt_estimate;         /* Estimated RTT in microseconds            */
    bit<48> rtt_start;            /* Start timestamp of current RTT interval  */
    bit<1>  rtt_valid;            /* 1 if RTT has been estimated              */

    /* ---- Per-RTT Statistics ---- */
    bit<32> num_pkts;             /* Packets processed in current RTT interval */
    bit<32> num_pkts_prev;        /* Packets from previous RTT interval       */
    bit<32> max_enq_len;          /* Max enqueue depth in current RTT         */
    bit<32> max_enq_len_prev;     /* Max enqueue depth from previous RTT      */

    /* ---- Fingerprinting Metrics ---- */
    bit<8>  aggressiveness;       /* How fast queues fill (0-255)             */
    bit<8>  aggr_streak;          /* Consecutive RTTs with queue growth       */
    bit<8>  bwest_counter;        /* BW estimation pattern counter for BBR   */
    bit<32> bdp;                  /* Bandwidth-delay product estimate         */

    /* ---- Queue Assignment ---- */
    bit<3>  assigned_queue;       /* Queue ID (0-7) for scheduling            */
}

#endif /* _P4AIR_HEADERS_P4_ */
