/* ingress.p4 */
#ifndef _INGRESS_P4_
#define _INGRESS_P4_

#include <core.p4>
#include <v1model.p4>
#include "headers.p4"

/* ---- Core tuning constants for phase 3 ---- */
#define KARMA_INIT         100
#define MAX_KARMA          100
#define GREEN              0
#define YELLOW             1
#define RED                2

/* KBCS FIX: Extended window from 5ms to 15ms (1.5x RTT) for complete feedback cycle */
#define WINDOW_USEC        15000
    
/* The actual fair share bytes are now dynamically provided via reg_fair_bytes */

/* Harsher penalties for faster reaction */
// Penalties and Rewards are now dynamically read from registers via RL Meta-Tuner
// #define PEN3               60      // Instantly drives 100 -> RED (40)
// #define PEN2               30
// #define PEN1               10

// #define REWARD             2       // Slow, cautious recovery

/* Ensure registers can scale beyond hardcoded 16 hosts */
#define REG_SIZE           1024

/* STAGE 2: Token Bucket Rate Limiting Constants */
#define TOKEN_BUCKET_SIZE  6250   // ~20ms worth at fair share (312500 * 0.020)
#define DEFAULT_TOKEN_RATE 250000 // bytes/sec = 2.0 Mbps base per flow (conservative)
#define GREEN_TOKEN_RATE   312500 // bytes/sec = 2.5 Mbps for GREEN (fair share)
#define MIN_TOKEN_RATE     187500 // 60% of fair share (prevents starvation)

control MyIngress(inout parsed_headers_t hdr,
                  inout local_metadata_t meta,
                  inout standard_metadata_t standard_metadata) {

    /* Persistent state: byte tracking for rate limiting */
    register<bit<32>>(REG_SIZE) reg_bytes;
    /* Persistent state: tracking drop count for visualization */
    register<bit<32>>(REG_SIZE) reg_drops;
    register<bit<32>>(16) reg_last_time;
    register<bit<16>>(REG_SIZE) reg_karma;
    register<bit<48>>(REG_SIZE) reg_wstart;
    register<bit<48>>(REG_SIZE) reg_last_seen;
    register<bit<32>>(REG_SIZE) reg_total_pkts;
    register<bit<16>>(REG_SIZE) reg_prev_karma;
    register<bit<2>>(REG_SIZE) reg_prev_color;
    
    /* Control Plane Configuration: Dynamic Fair Share per 5ms Window */
    register<bit<32>>(1) reg_fair_bytes;
    
    /* Meta-RL Tunable Parameters */
    register<bit<32>>(1) reg_penalty_amt;
    register<bit<32>>(1) reg_reward_amt;
    
    /* Telemetry for ECN marks */
    register<bit<32>>(REG_SIZE) reg_ecn_marks;
    
    /* RL Control Plane: Per-flow adaptive byte budgets */
    register<bit<32>>(REG_SIZE) reg_fair_bytes_per_flow;
    
    /* RL telemetry: cumulative bytes FORWARDED (excludes drops) */
    register<bit<32>>(REG_SIZE) reg_forwarded_bytes;

    /* STAGE 2: Token Bucket State for Rate Limiting */
    register<bit<32>>(REG_SIZE) reg_tokens;      // Current token count per flow
    register<bit<48>>(REG_SIZE) reg_token_time;  // Last token refill timestamp

    /* STAGE 2: RED zone recovery - track consecutive RED windows */
    register<bit<8>>(REG_SIZE) reg_red_streak;

    action set_flow_id(bit<16> flow_id) {
        meta.flow_id = flow_id;
    }

    table flow_id_exact {
        key = { hdr.ipv4.srcAddr : exact; }
        actions = { set_flow_id; NoAction; }
        size = 1024;
        default_action = NoAction();
    }

    action drop() { mark_to_drop(standard_metadata); }

    action ipv4_forward(macAddr_t dstAddr, egressSpec_t port) {
        standard_metadata.egress_spec = port;
        hdr.ethernet.srcAddr = hdr.ethernet.dstAddr;
        hdr.ethernet.dstAddr = dstAddr;
        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
    }

    action l2_broadcast() { standard_metadata.mcast_grp = 1; }

    table ipv4_lpm {
        key = { hdr.ipv4.dstAddr: lpm; }
        actions = { ipv4_forward; drop; NoAction; }
        size = 1024;
        default_action = drop();
    }

    apply {
        if (hdr.ipv4.isValid()) {
            if (hdr.tcp.isValid()) {

                /* ---- Guard: bypass karma for SYN / FIN / RST ---- */
                bit<6> guard_mask = hdr.tcp.ctrl & 6w0x07; // FIN=1,SYN=2,RST=4
                if (guard_mask == 0) {
                    /* ---- Only DATA / ACK packets reach here ---- */

                    /* STEP 1 — flow ID (Control Plane Assigned) */
                    meta.flow_id = 0; // Default undefined flow
                    flow_id_exact.apply();
                    
                    if (meta.flow_id != 0) {
                        /* STEP 2 — read state */
                        bit<32> idx = (bit<32>)meta.flow_id;
                        reg_bytes.read(meta.flow_bytes, idx);
                        reg_karma.read(meta.karma_score, idx);

                        bit<48> wstart;
                        reg_wstart.read(wstart, idx);

                        bit<48> last_seen;
                        reg_last_seen.read(last_seen, idx);
                        
                        bit<32> total_pkts;
                        reg_total_pkts.read(total_pkts, idx);
                        total_pkts = total_pkts + 1;

                        bit<16> prev_karma;
                        reg_prev_karma.read(prev_karma, idx);

                        bit<48> now = standard_metadata.ingress_global_timestamp;

                        /* Fetch dynamic fair bytes */
                        bit<32> fair_bytes;
                        reg_fair_bytes.read(fair_bytes, 0);
                        if (fair_bytes == 0) { fair_bytes = 1562; } // Safety default (1 pkt)
                        
                        bit<32> pen_base;
                        reg_penalty_amt.read(pen_base, 0);
                        if (pen_base == 0) { pen_base = 10; } // Default PEN1

                        bit<32> reward_base;
                        reg_reward_amt.read(reward_base, 0);
                        if (reward_base == 0) { reward_base = 2; } // Default REWARD
                        
                        bit<32> tier3_bytes = fair_bytes << 3;   // 8x fair share
                        bit<32> tier2_bytes = fair_bytes << 2;   // 4x fair share
                        bit<32> tier1_bytes = fair_bytes + (fair_bytes >> 1); // 1.5x fair share

                        /* E8: Idle-Flow Karma Recovery */
                        if (last_seen != 0) {
                            bit<48> idle_time = now - last_seen;
                            if (idle_time > 500000) { // 500 ms
                                /* Recover karma slowly if starved */
                                meta.karma_score = meta.karma_score + 5;
                                if (meta.karma_score > MAX_KARMA) {
                                    meta.karma_score = MAX_KARMA;
                                }
                                /* Reset window so it doesn't instantly penalize an old burst */
                                wstart = now;
                                meta.flow_bytes = 0;
                                reg_wstart.write(idx, now);
                            }
                        }

                        /* STEP 3 — window logic */
                        if (wstart == 0) {
                            /* brand-new flow — initialise */
                            meta.karma_score = KARMA_INIT;
                            meta.flow_bytes  = standard_metadata.packet_length;
                            reg_wstart.write(idx, now);
                        } else {
                            bit<48> elapsed = now - wstart;
                            if (elapsed > WINDOW_USEC) {
                                /* --- window expired: evaluate + reset --- */
                                if (meta.flow_bytes > fair_bytes) {
                                    /* E7: Slow-Start Leniency (Immunity for first 20 packets) */
                                    if (total_pkts > 20) {
                                        /* E2 proportional penalty */
                                        bit<16> pen = (bit<16>)pen_base;
                                        if (meta.flow_bytes > tier3_bytes) {
                                            pen = (bit<16>)(pen_base << 2); // 4x base
                                        } else if (meta.flow_bytes > tier2_bytes) {
                                            pen = (bit<16>)(pen_base << 1); // 2x base
                                        } 
                                        
                                        if (meta.karma_score > pen) {
                                            meta.karma_score = meta.karma_score - pen;
                                        } else {
                                            meta.karma_score = 0;
                                        }
                                        
                                        /* E6: Karma Momentum (Velocity-Aware Control) */
                                        if (prev_karma > meta.karma_score) {
                                            bit<16> delta = prev_karma - meta.karma_score;
                                            if (delta >= 15) { // Rapid degradation
                                                if (meta.karma_score > 5) {
                                                    meta.karma_score = meta.karma_score - 5;
                                                } else {
                                                    meta.karma_score = 0;
                                                }
                                            }
                                        }
                                    }
                                } else {
                                    /* reward */
                                    meta.karma_score = meta.karma_score + (bit<16>)reward_base;
                                    if (meta.karma_score > MAX_KARMA) {
                                        meta.karma_score = MAX_KARMA;
                                    }
                                }
                                meta.flow_bytes = standard_metadata.packet_length;
                                reg_wstart.write(idx, now);
                                reg_prev_karma.write(idx, meta.karma_score);
                            } else {
                                /* still inside window — accumulate */
                                meta.flow_bytes = meta.flow_bytes + standard_metadata.packet_length;
                            }
                        }

                        /* STEP 4 — Assign COLOR (E5 thresholds) */
                        if (meta.karma_score > 75) {
                            meta.flow_color = GREEN;
                        } else if (meta.karma_score > 40) {
                            meta.flow_color = YELLOW;
                        } else {
                            meta.flow_color = RED;
                        }

                        /* STAGE 2: RED Zone Recovery - prevent permanent lockout */
                        bit<8> red_streak;
                        reg_red_streak.read(red_streak, idx);
                        if (meta.flow_color == RED) {
                            red_streak = red_streak + 1;
                            if (red_streak >= 20) {  // ~300ms at 15ms windows
                                meta.karma_score = 30;  // Boost to low YELLOW
                                meta.flow_color = YELLOW;
                                red_streak = 0;
                            }
                        } else {
                            red_streak = 0;  // Reset streak when not RED
                        }
                        reg_red_streak.write(idx, red_streak);

                        /* Save updated state back to registers */
                        reg_bytes.write(idx, meta.flow_bytes);
                        reg_karma.write(idx, meta.karma_score);
                        reg_last_seen.write(idx, now);
                        reg_total_pkts.write(idx, total_pkts);

                        /* Check color transitions (or every 8th packet) to trigger E2E clone */
                        bit<2> prev_color;
                        reg_prev_color.read(prev_color, idx);

                        if (meta.flow_color != prev_color || (total_pkts & 7) == 0) {
                            reg_prev_color.write(idx, meta.flow_color);
                            // Only E2E clone forward-path packets
                            // Senders to receiver enter on arbitrary ports; receiver ACKs enter on port 3.
                            if (standard_metadata.ingress_port != (bit<9>)3) {
                                meta.should_clone_e2e = 1;
                            }
                        }

                        /* STEP 5 — Budget-Based AQM with Differentiated Drop Treatment
                         * Drop rates tuned for heterogeneous CCA fairness:
                         * - GREEN: Low drops (loss-based CCAs stay active)
                         * - RED: High drops (limit aggressive BBR-like flows)
                         * Drop probability: GREEN=10%, YELLOW=35%, RED=90%
                         */
                        meta.is_dropped = 0;
                        bit<32> flow_budget = fair_bytes;

                        /* Color penalties shrink the budget */
                        if (meta.flow_color == YELLOW) {
                            flow_budget = flow_budget - (flow_budget >> 2); // 75%
                        } else if (meta.flow_color == RED) {
                            flow_budget = flow_budget >> 2; // 25% - very aggressive
                        }

                        /* Differentiated AQM: Drop rates based on karma color */
                        if (meta.flow_bytes > flow_budget) {
                            bit<8> rand_val;
                            random(rand_val, 0, 255);
                            bit<8> drop_threshold;

                            if (meta.flow_color == GREEN) {
                                drop_threshold = 26;   // 10% drop rate (protect loss-based)
                            } else if (meta.flow_color == YELLOW) {
                                drop_threshold = 90;   // 35% drop rate
                            } else {
                                drop_threshold = 230;  // 90% drop rate (limit BBR)
                            }

                            if (rand_val < drop_threshold) {
                                bit<32> drop_count;
                                reg_drops.read(drop_count, idx);
                                reg_drops.write(idx, drop_count + 1);
                                meta.is_dropped = 1;
                                meta.should_clone_e2e = 0;
                                clone(CloneType.I2E, 4);
                                drop();
                            } else {
                                /* Mark ECN for flows that survive */
                                hdr.ipv4.diffserv = hdr.ipv4.diffserv | 3;
                            }
                        }

                        /* Map colors to strict BMv2 hardware priority queues:
                         * Priority 2 = HIGHEST Priority (BMv2 strict priority logic)
                         * Priority 0 = LOWEST Priority 
                         */
                        if (meta.is_dropped == 0) {
                            /* Track forwarded bytes for RL controller */
                            bit<32> fwd_bytes;
                            reg_forwarded_bytes.read(fwd_bytes, idx);
                            reg_forwarded_bytes.write(idx, fwd_bytes + standard_metadata.packet_length);
                            
                            if (meta.flow_color == GREEN) {
                                standard_metadata.priority = 2; 
                            } else if (meta.flow_color == YELLOW) {
                                standard_metadata.priority = 1;
                            } else {
                                standard_metadata.priority = 0;
                            }
                        }
                    } /* End of meta.flow_id != 0 */
                } /* End of guard_mask == 0 */
            } /* End of tcp.isValid() */
            
            /* STEP 7 — Standard Forwarding */
            ipv4_lpm.apply();

        } else {
            /* allow ARP through broadcast */
            if (hdr.ethernet.etherType == 0x0806) {
                l2_broadcast();
            }
        }
    }
}
#endif
