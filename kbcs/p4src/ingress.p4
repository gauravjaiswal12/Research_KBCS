/* ingress.p4 — KBCS Full Enhanced Ingress Pipeline                     */
/* Implements ALL Phase 1 gap closures and Phase 2+ enhancements         */
/* from Major_Enhacements_Final.md and implementation_plan.md            */
/*                                                                        */
/* Enhancement Index:                                                     */
/*  [G1] Queue-depth-aware gating — penalty only during congestion       */
/*  [G2] Selective AQM drop — only at CRITICAL_KARMA (20), reset bytes  */
/*  [G3] Priority queues enabled — standard_metadata.priority written    */
/*  [G4] Hash collision guard — signature register prevents aliasing     */
/*  [E1] Dynamic thresholds — read from control-plane registers          */
/*  [E2] Congestion-proportional penalty — scales with enq_qdepth       */
/*  [E3] Graduated enforcement — ECN → window-halve → drop chain        */
/*  [E4] Active-flow-count adaptive threshold — fair share by N flows   */
/*  [E5] Stochastic fair drop — probabilistic drop by karma severity     */
/*  [E6] Karma momentum — velocity-based extra penalty                   */
/*  [E7] Slow-start leniency — immunity for first 20 packets of a flow  */
/*  [E8] Idle-flow karma recovery — restore karma after long silence     */
/*  [Platinum] Short-flow fast lane — mice flows skip karma evaluation   */
/* ----------------------------------------------------------------------- */
#ifndef _INGRESS_P4_
#define _INGRESS_P4_

#include <core.p4>
#include <v1model.p4>
#include "headers.p4"

/* ================================================================== */
/* Compile-Time Defaults (overridden at runtime by control plane)       */
/* ================================================================== */
#define DEFAULT_BYTE_THRESH    120000  // EWMA threshold: above = aggressive
#define DEFAULT_QDEPTH_THRESH  50     // Queue depth threshold for congestion
#define SHORT_FLOW_BYTES       15000  // Platinum lane ceiling for mice flows

#define KARMA_INIT     100
#define MAX_KARMA      100
#define CRITICAL_KARMA 20   // [G2] AQM drop trigger floor
#define SLOW_START_PKT 20   // [E7] Packet count immunity window

/* [E2] Congestion-proportional penalty tiers (scaled by queue depth)  */
#define PENALTY_SEVERE   15   // enq_qdepth > 200
#define PENALTY_HIGH     10   // enq_qdepth > 100
#define PENALTY_MED       5   // enq_qdepth > 50
#define PENALTY_LOW       2   // enq_qdepth <= 50 but congested
#define REWARD            1   // Compliant flow or no congestion

#define HIGH_THRESHOLD   80   // Karma boundary: above = GREEN
#define LOW_THRESHOLD    40   // Karma boundary: above = YELLOW, below = RED

/* [E3] Graduated enforcement: flow color */
#define COLOR_RED      0   // AQM drop (stochastic), low queue priority
#define COLOR_YELLOW   1   // ECN mark + window halve on ACKs
#define COLOR_GREEN    2   // Normal high-priority forwarding
#define COLOR_PLATINUM 3   // Short-flow absolute top priority

#define REG_SIZE       65536

/* ================================================================== */
/* Ingress Control                                                       */
/* ================================================================== */
control MyIngress(inout parsed_headers_t hdr,
                  inout local_metadata_t meta,
                  inout standard_metadata_t standard_metadata) {

    /* -------------------------------------------------------------- */
    /* Per-Flow State Registers                                         */
    /* -------------------------------------------------------------- */
    register<bit<32>>(REG_SIZE) reg_flow_bytes;   // EWMA byte accumulator
    register<bit<16>>(REG_SIZE) reg_flow_karma;   // Karma [0–100]
    register<bit<16>>(REG_SIZE) reg_flow_sig;     // [G4] Collision guard
    register<bit<16>>(REG_SIZE) reg_prev_karma;   // [E6] Karma momentum
    register<bit<16>>(REG_SIZE) reg_pkt_count;    // [E7] Slow-start counter
    register<bit<2>>(REG_SIZE)  reg_prev_color;   // [E10] Transition detection
    register<bit<48>>(REG_SIZE) reg_last_seen;    // [E8] Idle-flow recovery

    /* -------------------------------------------------------------- */
    /* Dynamic Control-Plane Parameter Registers [E1]                   */
    /* Written periodically by kbcs_controller.py                       */
    /* -------------------------------------------------------------- */
    register<bit<32>>(1) reg_qdepth_thresh;  // Adaptive queue-depth threshold
    register<bit<32>>(1) reg_byte_thresh;    // Adaptive byte threshold
    register<bit<32>>(1) reg_active_flows;   // [E4] Total active flow count

    /* -------------------------------------------------------------- */
    /* Actions                                                          */
    /* -------------------------------------------------------------- */
    action drop() {
        mark_to_drop(standard_metadata);
    }

    action ipv4_forward(macAddr_t dstAddr, egressSpec_t port) {
        standard_metadata.egress_spec = port;
        hdr.ethernet.dstAddr = dstAddr;
        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
    }

    action l2_broadcast() {
        standard_metadata.mcast_grp = 1;
    }

    /* -------------------------------------------------------------- */
    /* Forwarding Table                                                 */
    /* -------------------------------------------------------------- */
    table ipv4_lpm {
        key = {
            hdr.ipv4.dstAddr: lpm;
        }
        actions = {
            ipv4_forward;
            drop;
            NoAction;
        }
        size = 1024;
        default_action = drop();
    }

    /* ============================================================== */
    /* Apply Block                                                       */
    /* ============================================================== */
    apply {
        if (hdr.ipv4.isValid()) {

            if (hdr.tcp.isValid()) {

                /* ================================================== */
                /* [E1] READ DYNAMIC THRESHOLDS                         */
                /* ================================================== */
                reg_qdepth_thresh.read(meta.dyn_qdepth_thresh, (bit<32>)0);
                if (meta.dyn_qdepth_thresh == 0) {
                    meta.dyn_qdepth_thresh = DEFAULT_QDEPTH_THRESH;
                }
                reg_byte_thresh.read(meta.dyn_byte_thresh, (bit<32>)0);
                if (meta.dyn_byte_thresh == 0) {
                    meta.dyn_byte_thresh = DEFAULT_BYTE_THRESH;
                }

                /* ================================================== */
                /* STEP 1: Flow Identification                           */
                /* ================================================== */
                hash(meta.flow_id,
                     HashAlgorithm.crc16,
                     (bit<16>)0,
                     { hdr.ipv4.srcAddr,
                       hdr.ipv4.dstAddr,
                       hdr.tcp.srcPort,
                       hdr.tcp.dstPort,
                       hdr.ipv4.protocol },
                     (bit<32>)REG_SIZE);

                /* ================================================== */
                /* [G4] STEP 2: Hash Collision Guard                    */
                /* ================================================== */
                meta.pkt_sig = (bit<16>)(hdr.ipv4.srcAddr[15:0] ^
                                         hdr.ipv4.dstAddr[15:0] ^
                                         hdr.tcp.srcPort           ^
                                         hdr.tcp.dstPort);
                reg_flow_sig.read(meta.stored_sig, (bit<32>)meta.flow_id);

                if (meta.stored_sig != 0 && meta.stored_sig != meta.pkt_sig) {
                    // Collision: forward safely at YELLOW, skip karma
                    meta.flow_color = COLOR_YELLOW;
                    meta.karma_score = (bit<16>)HIGH_THRESHOLD;
                    standard_metadata.priority = (bit<3>)COLOR_YELLOW;
                    meta.queue_id = (bit<3>)COLOR_YELLOW;
                    ipv4_lpm.apply();
                } else {

                    // Register new flow signature
                    if (meta.stored_sig == 0) {
                        reg_flow_sig.write((bit<32>)meta.flow_id, meta.pkt_sig);
                    }

                    /* ============================================== */
                    /* STEP 3: State Read                              */
                    /* ============================================== */
                    reg_flow_bytes.read(meta.flow_bytes, (bit<32>)meta.flow_id);
                    reg_flow_karma.read(meta.karma_score, (bit<32>)meta.flow_id);
                    reg_prev_karma.read(meta.prev_karma,  (bit<32>)meta.flow_id);
                    reg_pkt_count.read(meta.pkt_count,    (bit<32>)meta.flow_id);
                    reg_prev_color.read(meta.prev_color,  (bit<32>)meta.flow_id);
                    reg_last_seen.read(meta.last_seen_ts, (bit<32>)meta.flow_id);

                    /* ============================================== */
                    /* STEP 4: EWMA Byte Decay                          */
                    /* flow_bytes = (old >> 1) + pkt_len               */
                    /* ============================================== */
                    meta.flow_bytes = (meta.flow_bytes >> 1)
                                      + (bit<32>)standard_metadata.packet_length;
                    reg_flow_bytes.write((bit<32>)meta.flow_id, meta.flow_bytes);

                    /* ============================================== */
                    /* STEP 5: New-Flow Initialisation                 */
                    /* ============================================== */
                    if (meta.karma_score == 0 &&
                        meta.flow_bytes == (bit<32>)standard_metadata.packet_length) {
                        meta.karma_score = KARMA_INIT;
                        // Increment active flow counter [E4]
                        bit<32> active;
                        reg_active_flows.read(active, (bit<32>)0);
                        reg_active_flows.write((bit<32>)0, active + 1);
                    }

                    /* ============================================== */
                    /* STEP 6: Packet Counter (for slow-start) [E7]    */
                    /* ============================================== */
                    meta.pkt_count = meta.pkt_count + 1;
                    reg_pkt_count.write((bit<32>)meta.flow_id, meta.pkt_count);

                    /* ============================================== */
                    /* [E8] STEP 7: Idle-Flow Karma Recovery           */
                    /* If the flow has been silent (last_seen far in   */
                    /* the past), boost its karma to give it a fresh   */
                    /* start instead of leaving it permanently RED.    */
                    /* ============================================== */
                    bit<48> now = standard_metadata.ingress_global_timestamp;
                    bit<48> idle_time = now - meta.last_seen_ts;
                    // ~2 RTTs idle at 5ms RTT = 10ms = 10,000 µs
                    if (meta.last_seen_ts != 0 && idle_time > 10000) {
                        // Fast recovery for idle flows
                        if (meta.karma_score < (bit<16>)(MAX_KARMA - 5)) {
                            meta.karma_score = meta.karma_score + 5;
                        } else {
                            meta.karma_score = MAX_KARMA;
                        }
                    }
                    reg_last_seen.write((bit<32>)meta.flow_id, now);

                    /* ============================================== */
                    /* [G1] STEP 8: Congestion Gate                    */
                    /* All penalties require actual queue congestion.  */
                    /* ============================================== */
                    bool is_congested =
                        ((bit<32>)standard_metadata.enq_qdepth > meta.dyn_qdepth_thresh);

                    /* ============================================== */
                    /* [E4] STEP 9: Active-Flow Adaptive Threshold     */
                    /* Divide the fair-share threshold by active-flow  */
                    /* count so each flow's budget shrinks with scale. */
                    /* ============================================== */
                    bit<32> active_n;
                    reg_active_flows.read(active_n, (bit<32>)0);
                    bit<32> effective_byte_thresh = meta.dyn_byte_thresh;
                    if (active_n > 16) {
                        effective_byte_thresh = meta.dyn_byte_thresh >> 2; // /4
                    } else if (active_n > 4) {
                        effective_byte_thresh = meta.dyn_byte_thresh >> 1; // /2
                    }
                    // else: threshold stays at full value for ≤4 flows

                    /* ============================================== */
                    /* [E7] STEP 10: Slow-Start Leniency              */
                    /* Skip penalty for first SLOW_START_PKT packets  */
                    /* to avoid misclassifying TCP ramp-up as aggression*/
                    /* ============================================== */
                    bool in_slow_start = (meta.pkt_count < SLOW_START_PKT);

                    /* ============================================== */
                    /* [E2] STEP 11: Congestion-Proportional Karma    */
                    /* Penalty scales with enq_qdepth severity.       */
                    /* ============================================== */
                    if (is_congested && !in_slow_start) {
                        bit<32> qdepth32 = (bit<32>)standard_metadata.enq_qdepth;

                        if (meta.flow_bytes > effective_byte_thresh) {
                            // Flow is aggressive AND congestion is happening
                            if (qdepth32 > 200) {
                                meta.penalty_val = PENALTY_SEVERE;
                            } else if (qdepth32 > 100) {
                                meta.penalty_val = PENALTY_HIGH;
                            } else if (qdepth32 > 50) {
                                meta.penalty_val = PENALTY_MED;
                            } else {
                                meta.penalty_val = PENALTY_LOW;
                            }
                        } else {
                            // Congested but this flow is being cooperative
                            meta.penalty_val = 0;
                        }
                    } else {
                        // Not congested or in slow start → reward
                        meta.penalty_val = 0;
                    }

                    /* Apply karma delta */
                    if (meta.penalty_val > 0) {
                        if (meta.karma_score > (bit<16>)meta.penalty_val) {
                            meta.karma_score = meta.karma_score
                                               - (bit<16>)meta.penalty_val;
                        } else {
                            meta.karma_score = 0;
                        }
                    } else {
                        if (meta.karma_score < MAX_KARMA) {
                            meta.karma_score = meta.karma_score + REWARD;
                        }
                    }

                    /* ============================================== */
                    /* [E6] STEP 12: Karma Momentum                    */
                    /* If the flow's karma is dropping rapidly         */
                    /* (delta < -10), apply extra deterrent penalty.   */
                    /* Uses signed comparison via unsigned subtraction. */
                    /* ============================================== */
                    if (meta.prev_karma > meta.karma_score) {
                        bit<16> karma_drop = meta.prev_karma - meta.karma_score;
                        if (karma_drop > 10) {
                            // Rapidly deteriorating: add extra 5-point penalty
                            if (meta.karma_score > 5) {
                                meta.karma_score = meta.karma_score - 5;
                            } else {
                                meta.karma_score = 0;
                            }
                        }
                    }

                    // Write karma and save previous for next packet
                    reg_flow_karma.write((bit<32>)meta.flow_id, meta.karma_score);
                    reg_prev_karma.write((bit<32>)meta.flow_id, meta.karma_score);

                    /* ============================================== */
                    /* [Platinum + E3] STEP 13: Flow Coloring          */
                    /* ============================================== */
                    if (meta.flow_bytes < SHORT_FLOW_BYTES) {
                        meta.flow_color = COLOR_PLATINUM;  // Mice fast lane
                    } else if (meta.karma_score > HIGH_THRESHOLD) {
                        meta.flow_color = COLOR_GREEN;
                    } else if (meta.karma_score > LOW_THRESHOLD) {
                        meta.flow_color = COLOR_YELLOW;
                    } else {
                        meta.flow_color = COLOR_RED;
                    }

                    // Save color for transition telemetry [E10]
                    reg_prev_color.write((bit<32>)meta.flow_id, meta.flow_color);

                    /* ============================================== */
                    /* [G3] STEP 14: Priority Queue Assignment          */
                    /* ============================================== */
                    standard_metadata.priority = (bit<3>)meta.flow_color;
                    meta.queue_id              = (bit<3>)meta.flow_color;

                    /* ============================================== */
                    /* [E3] STEP 15: Graduated Enforcement Chain       */
                    /*                                                  */
                    /* GREEN    → forward normally (no action here)    */
                    /* YELLOW   → ECN mark + halve TCP window on ACKs  */
                    /* RED      → stochastic probabilistic drop [E5]   */
                    /*            (hard drop only at CRITICAL_KARMA)   */
                    /* ============================================== */

                    if (meta.flow_color == COLOR_YELLOW) {
                        // ECN Congestion Experienced (CE) marking
                        // Set bits [1:0] of IP diffserv field = 0b11
                        hdr.ipv4.diffserv = hdr.ipv4.diffserv | 0x03;

                        // Halve TCP receive window on ACK packets [E3]
                        // ACK flag is bit 4 of TCP ctrl field (0x10)
                        if ((hdr.tcp.ctrl & 6w0x10) != 0) {
                            hdr.tcp.window = hdr.tcp.window >> 1;
                        }
                    }

                    else if (meta.flow_color == COLOR_RED) {
                        /* [G2] Selective + [E5] Stochastic Drop        */
                        /* Hard drop only at CRITICAL_KARMA (20).       */
                        /* Above that, use probabilistic dropping where  */
                        /* the probability scales with karma severity:   */
                        /*   karma 21–40 → 30% drop                     */
                        /*   karma <= 20 → hard drop (100%)             */
                        if (is_congested) {
                            if (meta.karma_score <= CRITICAL_KARMA) {
                                // [G2] Hard drop at critical karma
                                reg_flow_bytes.write((bit<32>)meta.flow_id, 0);
                                drop();
                            } else {
                                // [E5] Stochastic fair drop
                                // Pseudo-random from packet identification field
                                hash(meta.rand_val,
                                     HashAlgorithm.crc16,
                                     (bit<16>)0,
                                     { hdr.ipv4.identification,
                                       hdr.tcp.seqNo },
                                     (bit<32>)100);

                                // karma 21–40 → ~30% drop rate
                                if (meta.rand_val < 30) {
                                    drop();
                                }
                            }
                        }
                    }

                    // Forward all surviving packets
                    ipv4_lpm.apply();
                }

            } else {
                // Non-TCP IP (ICMP, etc.) → forward without karma
                ipv4_lpm.apply();
            }

        } else if (hdr.ethernet.isValid() && hdr.ethernet.etherType == 0x0806) {
            l2_broadcast();
        }
    }
}

#endif
