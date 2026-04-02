/* headers.p4 — KBCS Full Enhanced Header Definitions                   */
/* Supports all Phase 1–4 enhancements from Major_Enhancements_Final.md */
#ifndef _HEADERS_P4_
#define _HEADERS_P4_

typedef bit<9>  egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;

/* ------------------------------------------------------------------ */
/* Protocol Headers                                                     */
/* ------------------------------------------------------------------ */
header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}

header ipv4_t {
    bit<4>    version;
    bit<4>    ihl;
    bit<8>    diffserv;    // bits [1:0] = ECN field (used for CE marking)
    bit<16>   totalLen;
    bit<16>   identification;
    bit<3>    flags;
    bit<13>   fragOffset;
    bit<8>    ttl;
    bit<8>    protocol;
    bit<16>   hdrChecksum;
    ip4Addr_t srcAddr;
    ip4Addr_t dstAddr;
}

header tcp_t {
    bit<16> srcPort;
    bit<16> dstPort;
    bit<32> seqNo;
    bit<32> ackNo;
    bit<4>  dataOffset;
    bit<3>  res;
    bit<3>  ecn;
    bit<6>  ctrl;          // TCP flags: URG ACK PSH RST SYN FIN
    bit<16> window;        // TCP receive window (halved for YELLOW flows)
    bit<16> checksum;
    bit<16> urgentPtr;
}

/* ------------------------------------------------------------------ */
/* Parsed Header Stack                                                  */
/* ------------------------------------------------------------------ */
struct parsed_headers_t {
    ethernet_t ethernet;
    ipv4_t     ipv4;
    tcp_t      tcp;
}

/* ------------------------------------------------------------------ */
/* Per-Packet Local Metadata                                            */
/*                                                                      */
/* Flow color encoding (2 bits):                                        */
/*   RED      = 0  → Q0 (Bronze, lowest priority → drop at crit. karma)*/
/*   YELLOW   = 1  → Q1 (Silver, ECN marking + window halve on ACKs)   */
/*   GREEN    = 2  → Q2 (Gold, high priority forwarding)               */
/*   PLATINUM = 3  → Q3 (Short-flow fast lane, absolute top priority)  */
/* ------------------------------------------------------------------ */
struct local_metadata_t {
    /* Core karma state */
    bit<16> flow_id;           // CRC16 hash index into register arrays
    bit<32> flow_bytes;        // EWMA decayed byte counter
    bit<16> karma_score;       // Bounded karma [0–100]
    bit<16> prev_karma;        // Previous karma for momentum calculation [E6]
    bit<2>  flow_color;        // Behavioral class (RED/YELLOW/GREEN/PLATINUM)
    bit<2>  prev_color;        // Previous color (for transition detection [E10])
    bit<3>  queue_id;          // Maps color → BMv2 priority queue index

    /* Hash collision guard [G4] */
    bit<16> pkt_sig;           // Signature computed for this packet
    bit<16> stored_sig;        // Signature stored in register for this slot

    /* Dynamic threshold state [E1 dynamic params] */
    bit<32> dyn_qdepth_thresh; // Live queue-depth congestion threshold
    bit<32> dyn_byte_thresh;   // Live byte aggressiveness threshold

    /* Computed per-packet values */
    bit<32> penalty_val;       // CCA-aware penalty for this packet [E2]
    bit<32> rand_val;          // Pseudo-random value for stochastic drop [E5]
    bit<16> pkt_count;         // Per-flow packet counter for slow-start [E7]
    bit<48> last_seen_ts;      // Timestamp for idle-flow recovery [E8]
}

#endif
