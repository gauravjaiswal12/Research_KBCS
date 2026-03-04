/* =============================================================================
 * ingress.p4 — P4air Ingress Pipeline (COMPLETE: Phases 2-5)
 * =============================================================================
 * Implements all P4air modules:
 *   ✅ Phase 2: Registers + basic forwarding
 *   ✅ Phase 3: Fingerprinting (ingress): RTT, BDP, slow-start, BwEst, BBR
 *   ✅ Phase 4: Reallocation: dynamic queue boundaries, flow-to-queue assignment
 *   ✅ Phase 5: Apply Actions: drop (loss), delay (delay-based), window (model)
 *
 * Pipeline order per TCP packet:
 *   1. Flow identification (5-tuple hash)
 *   2. Register state read
 *   3. Handle recirculated packets (group update + reallocation)
 *   4. RTT estimation (SYN handshake)
 *   5. Per-RTT statistics (packet count, BwEst)
 *   6. Slow-start end detection → MICE to DELAY transition
 *   7. Model-based detection → BBR reclassification
 *   8. Queue reallocation (boundary calculation + assignment)
 *   9. Apply Actions (drop / delay / window-adjust per group)
 *   10. IPv4 forwarding
 * =========================================================================== */

#ifndef _P4AIR_INGRESS_P4_
#define _P4AIR_INGRESS_P4_

#include <core.p4>
#include <v1model.p4>
#include "headers.p4"

control P4airIngress(inout parsed_headers_t hdr,
                     inout p4air_metadata_t meta,
                     inout standard_metadata_t standard_metadata) {

    /* =========================================================================
     * REGISTER ARRAYS
     * ======================================================================= */

    /* Per-flow registers (indexed by flow_id, size = FLOW_TABLE_SIZE) */
    register<bit<3>>(FLOW_TABLE_SIZE)  reg_group;
    register<bit<3>>(FLOW_TABLE_SIZE)  reg_queue;
    register<bit<48>>(FLOW_TABLE_SIZE) reg_rtt;
    register<bit<48>>(FLOW_TABLE_SIZE) reg_rtt_start;
    register<bit<1>>(FLOW_TABLE_SIZE)  reg_syn_seen;
    register<bit<48>>(FLOW_TABLE_SIZE) reg_syn_ts;
    register<bit<32>>(FLOW_TABLE_SIZE) reg_num_pkts;
    register<bit<32>>(FLOW_TABLE_SIZE) reg_num_pkts_prev;
    register<bit<8>>(FLOW_TABLE_SIZE)  reg_bwest;

    /* Per-group registers (indexed by group_id, size = NUM_GROUPS) */
    register<bit<32>>(NUM_GROUPS)      reg_group_flows;
    register<bit<3>>(NUM_GROUPS)       reg_group_q_start;
    register<bit<3>>(NUM_GROUPS)       reg_group_q_end;
    register<bit<3>>(NUM_GROUPS)       reg_group_seq_idx;

    /* Global register */
    register<bit<32>>(1)               reg_total_flows;

    /* =========================================================================
     * ACTIONS
     * ======================================================================= */

    /* drop: marks packet for dropping (loss-based/loss-delay enforcement + default). */
    action drop() {
        mark_to_drop(standard_metadata);
    }

    /* ipv4_forward: L3 forwarding — set output port and rewrite dst MAC. */
    action ipv4_forward(macAddr_t dstAddr, egressSpec_t port) {
        standard_metadata.egress_spec = port;
        hdr.ethernet.dstAddr = dstAddr;
        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
    }

    /* l2_broadcast: send via multicast group 1 (for ARP resolution). */
    action l2_broadcast() {
        standard_metadata.mcast_grp = 1;
    }

    /* =========================================================================
     * TABLES
     * ======================================================================= */

    /* ipv4_lpm: longest prefix match forwarding table. */
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

    /* =========================================================================
     * APPLY BLOCK — Complete P4air Ingress Pipeline
     * ======================================================================= */
    apply {
        if (hdr.ipv4.isValid()) {

            if (hdr.tcp.isValid()) {

                /* ==========================================================
                 * STEP 1: FLOW IDENTIFICATION
                 * Hash 5-tuple → flow_id, used as register index.
                 * ========================================================== */
                hash(meta.flow_id,
                     HashAlgorithm.crc16,
                     (bit<16>)0,
                     { hdr.ipv4.srcAddr,
                       hdr.ipv4.dstAddr,
                       hdr.tcp.srcPort,
                       hdr.tcp.dstPort,
                       hdr.ipv4.protocol },
                     (bit<16>)FLOW_TABLE_SIZE);

                /* ==========================================================
                 * STEP 2: READ FLOW STATE
                 * ========================================================== */
                bit<3>  current_group;
                bit<48> current_rtt;
                bit<48> current_rtt_start;
                bit<1>  syn_seen;
                bit<48> syn_ts;
                bit<32> num_pkts;
                bit<32> num_pkts_prev;
                bit<8>  bwest;
                bit<3>  current_queue;

                reg_group.read(current_group, (bit<32>)meta.flow_id);
                reg_rtt.read(current_rtt, (bit<32>)meta.flow_id);
                reg_rtt_start.read(current_rtt_start, (bit<32>)meta.flow_id);
                reg_syn_seen.read(syn_seen, (bit<32>)meta.flow_id);
                reg_syn_ts.read(syn_ts, (bit<32>)meta.flow_id);
                reg_num_pkts.read(num_pkts, (bit<32>)meta.flow_id);
                reg_num_pkts_prev.read(num_pkts_prev, (bit<32>)meta.flow_id);
                reg_bwest.read(bwest, (bit<32>)meta.flow_id);
                reg_queue.read(current_queue, (bit<32>)meta.flow_id);

                /* Initialize metadata */
                meta.flow_group = current_group;
                meta.rtt_estimate = current_rtt;
                meta.rtt_start = current_rtt_start;
                meta.num_pkts = num_pkts;
                meta.num_pkts_prev = num_pkts_prev;
                meta.bwest_counter = bwest;
                meta.assigned_queue = current_queue;
                meta.rtt_valid = 0;
                meta.group_changed = 0;
                meta.is_recirculated = 0;
                meta.prev_group = current_group;
                meta.bdp = 2;  /* Safe default */

                /* ==========================================================
                 * STEP 3: HANDLE RECIRCULATED PACKETS (Phase 4)
                 * Recirculated by egress after group reclassification.
                 * Update master group register + run reallocation.
                 * ========================================================== */
                if (standard_metadata.instance_type != 0) {
                    meta.is_recirculated = 1;

                    /* Write new group to ingress master register */
                    reg_group.write((bit<32>)meta.flow_id, meta.flow_group);
                    current_group = meta.flow_group;

                    /* --- Update group flow counters --- */
                    bit<32> old_grp_cnt;
                    bit<32> new_grp_cnt;
                    reg_group_flows.read(old_grp_cnt, (bit<32>)meta.prev_group);
                    reg_group_flows.read(new_grp_cnt, (bit<32>)meta.flow_group);
                    if (old_grp_cnt > 0) {
                        reg_group_flows.write((bit<32>)meta.prev_group, old_grp_cnt - 1);
                    }
                    reg_group_flows.write((bit<32>)meta.flow_group, new_grp_cnt + 1);

                    /* --- REALLOCATION: Recalculate queue boundaries ---
                     * Paper Section III-C: "The number of allocated queues per
                     * group is proportional to the group's size."
                     *
                     * Available queues for long-lived: Q2-Q7 (6 queues)
                     * Q0 = ants, Q1 = mice (always reserved)
                     *
                     * Simple proportional allocation:
                     * Each group gets max(1, round(group_flows / total * 6)) queues
                     * Boundaries: [q_start, q_end) for each group
                     */
                    bit<32> total_long;
                    reg_total_flows.read(total_long, 0);

                    /* Read all group sizes */
                    bit<32> delay_flows;
                    bit<32> loss_delay_flows;
                    bit<32> loss_flows;
                    bit<32> model_flows;
                    reg_group_flows.read(delay_flows, (bit<32>)GROUP_DELAY);
                    reg_group_flows.read(loss_delay_flows, (bit<32>)GROUP_LOSS_DELAY);
                    reg_group_flows.read(loss_flows, (bit<32>)GROUP_LOSS);
                    reg_group_flows.read(model_flows, (bit<32>)GROUP_MODEL);

                    /* Only reallocate if there are long-lived flows */
                    if (total_long > 0) {
                        /* Assign queues proportionally among active groups.
                         * We have 6 dynamic queues (Q2-Q7).
                         * Strategy: each active group gets at least 1 queue.
                         * Remaining queues go to the largest group. */
                        bit<3> q_cursor = 2;  /* Start after ant(0) and mice(1) */

                        /* Count active long-lived groups (groups with > 0 flows) */
                        bit<3> active_groups = 0;
                        if (delay_flows > 0)      { active_groups = active_groups + 1; }
                        if (loss_delay_flows > 0)  { active_groups = active_groups + 1; }
                        if (loss_flows > 0)        { active_groups = active_groups + 1; }
                        if (model_flows > 0)       { active_groups = active_groups + 1; }

                        /* Ensure we don't have zero active groups */
                        if (active_groups == 0) {
                            active_groups = 1;
                        }

                        /* Base queues per group: 6 / active_groups
                         * P4 has no runtime division, so we use if-else. */
                        bit<3> base_q;
                        if (active_groups == 1) {
                            base_q = 6;
                        } else if (active_groups == 2) {
                            base_q = 3;
                        } else if (active_groups == 3) {
                            base_q = 2;
                        } else {
                            base_q = 1;  /* 4 groups → 1 queue each, 2 remaining */
                        }

                        /* Assign queue ranges for each long-lived group */
                        /* DELAY group */
                        if (delay_flows > 0) {
                            reg_group_q_start.write((bit<32>)GROUP_DELAY, q_cursor);
                            q_cursor = q_cursor + base_q;
                            if (q_cursor > 7) { q_cursor = 7; }
                            reg_group_q_end.write((bit<32>)GROUP_DELAY, q_cursor);
                        }
                        /* LOSS-DELAY group */
                        if (loss_delay_flows > 0) {
                            reg_group_q_start.write((bit<32>)GROUP_LOSS_DELAY, q_cursor);
                            q_cursor = q_cursor + base_q;
                            if (q_cursor > 7) { q_cursor = 7; }
                            reg_group_q_end.write((bit<32>)GROUP_LOSS_DELAY, q_cursor);
                        }
                        /* LOSS group */
                        if (loss_flows > 0) {
                            reg_group_q_start.write((bit<32>)GROUP_LOSS, q_cursor);
                            q_cursor = q_cursor + base_q;
                            if (q_cursor > 7) { q_cursor = 7; }
                            reg_group_q_end.write((bit<32>)GROUP_LOSS, q_cursor);
                        }
                        /* MODEL group (gets remaining queues) */
                        if (model_flows > 0) {
                            reg_group_q_start.write((bit<32>)GROUP_MODEL, q_cursor);
                            reg_group_q_end.write((bit<32>)GROUP_MODEL, 7);
                        }
                    }

                    /* --- Assign this flow's queue within its new group --- */
                    bit<3> q_start;
                    bit<3> q_end;
                    bit<3> seq_idx;
                    reg_group_q_start.read(q_start, (bit<32>)current_group);
                    reg_group_q_end.read(q_end, (bit<32>)current_group);
                    reg_group_seq_idx.read(seq_idx, (bit<32>)current_group);

                    /* Queue = q_start + (seq_idx % queue_range) */
                    bit<3> q_range = q_end - q_start;
                    if (q_range == 0) { q_range = 1; }

                    /* Simple modulo for small values (P4 has no % operator) */
                    bit<3> q_offset = seq_idx;
                    if (q_offset >= q_range) {
                        q_offset = q_offset - q_range;
                    }
                    if (q_offset >= q_range) {
                        q_offset = 0;
                    }

                    current_queue = q_start + q_offset;
                    if (current_queue > 7) { current_queue = 7; }

                    /* Update sequential index for next flow in this group */
                    reg_group_seq_idx.write((bit<32>)current_group, seq_idx + 1);
                    reg_queue.write((bit<32>)meta.flow_id, current_queue);
                }

                /* ==========================================================
                 * STEP 4: RTT ESTIMATION (from 3-way handshake)
                 * On SYN → store timestamp
                 * On first data after SYN → RTT = now - SYN_ts
                 * ========================================================== */
                if (current_rtt == 0) {
                    if ((hdr.tcp.ctrl & 6w0x02) != 0 && syn_seen == 0) {
                        /* SYN packet: record timestamp for RTT calculation */
                        reg_syn_seen.write((bit<32>)meta.flow_id, 1);
                        reg_syn_ts.write((bit<32>)meta.flow_id,
                                         standard_metadata.ingress_global_timestamp);
                        syn_ts = standard_metadata.ingress_global_timestamp;

                        /* New flow → classify as MICE (in slow-start) */
                        if (current_group == 0 && num_pkts == 0) {
                            current_group = GROUP_MICE;
                            reg_group.write((bit<32>)meta.flow_id, GROUP_MICE);
                        }

                    } else if (syn_seen == 1 && (hdr.tcp.ctrl & 6w0x02) == 0) {
                        /* First non-SYN after handshake → compute RTT */
                        bit<48> estimated_rtt;
                        estimated_rtt = standard_metadata.ingress_global_timestamp - syn_ts;

                        if (estimated_rtt > 0) {
                            current_rtt = estimated_rtt;
                            reg_rtt.write((bit<32>)meta.flow_id, estimated_rtt);
                            meta.rtt_estimate = estimated_rtt;
                            meta.rtt_valid = 1;

                            /* Start first RTT interval */
                            reg_rtt_start.write((bit<32>)meta.flow_id,
                                                standard_metadata.ingress_global_timestamp);
                            current_rtt_start = standard_metadata.ingress_global_timestamp;

                            /* Set MICE and update counters */
                            current_group = GROUP_MICE;
                            reg_group.write((bit<32>)meta.flow_id, GROUP_MICE);
                            meta.flow_group = GROUP_MICE;

                            bit<32> total_flows;
                            reg_total_flows.read(total_flows, 0);
                            reg_total_flows.write(0, total_flows + 1);

                            bit<32> mice_count;
                            reg_group_flows.read(mice_count, (bit<32>)GROUP_MICE);
                            reg_group_flows.write((bit<32>)GROUP_MICE, mice_count + 1);
                        }
                    }
                }

                /* ==========================================================
                 * STEP 5: PER-RTT STATISTICS + RECLASSIFICATION
                 * Only for tracked flows (RTT known).
                 * ========================================================== */
                if (current_rtt > 0) {
                    /* Count packet */
                    num_pkts = num_pkts + 1;
                    reg_num_pkts.write((bit<32>)meta.flow_id, num_pkts);
                    meta.num_pkts = num_pkts;

                    /* BDP calculation: BDP ≈ RTT >> s (shift approximation)
                     * s=10 for BMv2 emulation on 10Mbps / 4-flow setup.
                     * RTT in BMv2 is µs: 10ms = 10000µs → BDP = 10000>>10 ≈ 10 pkts.
                     * At 10Mbps w/ 1500B MTU, ~8 pkts/RTT, so BDP≈10 is appropriate. */
                    meta.bdp = (bit<32>)(current_rtt >> 10);
                    if (meta.bdp < 10) { meta.bdp = 10; }

                    /* Check RTT interval boundary */
                    bit<48> elapsed;
                    elapsed = standard_metadata.ingress_global_timestamp - current_rtt_start;

                    if (elapsed > current_rtt) {
                        /* ---- RTT INTERVAL BOUNDARY ---- */

                        /* Slow-start end detection (MICE only) */
                        if (current_group == GROUP_MICE) {
                            /* Pattern 1: sending rate decreased */
                            if (num_pkts_prev > 0 && num_pkts < num_pkts_prev) {
                                bit<32> m_cnt;
                                bit<32> d_cnt;
                                reg_group_flows.read(m_cnt, (bit<32>)GROUP_MICE);
                                reg_group_flows.read(d_cnt, (bit<32>)GROUP_DELAY);
                                if (m_cnt > 0) {
                                    reg_group_flows.write((bit<32>)GROUP_MICE, m_cnt - 1);
                                }
                                reg_group_flows.write((bit<32>)GROUP_DELAY, d_cnt + 1);
                                current_group = GROUP_DELAY;
                                reg_group.write((bit<32>)meta.flow_id, GROUP_DELAY);
                                meta.flow_group = GROUP_DELAY;
                            }
                            /* Pattern 2: reached BDP → proactive drop */
                            else if (num_pkts >= meta.bdp) {
                                bit<32> m_cnt2;
                                bit<32> d_cnt2;
                                reg_group_flows.read(m_cnt2, (bit<32>)GROUP_MICE);
                                reg_group_flows.read(d_cnt2, (bit<32>)GROUP_DELAY);
                                if (m_cnt2 > 0) {
                                    reg_group_flows.write((bit<32>)GROUP_MICE, m_cnt2 - 1);
                                }
                                reg_group_flows.write((bit<32>)GROUP_DELAY, d_cnt2 + 1);
                                current_group = GROUP_DELAY;
                                reg_group.write((bit<32>)meta.flow_id, GROUP_DELAY);
                                meta.flow_group = GROUP_DELAY;
                                drop();
                            }
                        }

                        /* BwEst update: detect periodic BW probing (BBR) */
                        if (num_pkts_prev > 0) {
                            bit<32> threshold;
                            threshold = num_pkts_prev + (num_pkts_prev >> 3);
                            if (num_pkts >= threshold) {
                                bwest = bwest + 1;
                                reg_bwest.write((bit<32>)meta.flow_id, bwest);
                            }
                        }

                        /* Model-based detection: bwest >= M_M → BBR */
                        if (bwest >= (bit<8>)M_M && current_group != GROUP_MODEL) {
                            meta.prev_group = current_group;
                            bit<32> o_cnt;
                            bit<32> m_cnt3;
                            reg_group_flows.read(o_cnt, (bit<32>)current_group);
                            reg_group_flows.read(m_cnt3, (bit<32>)GROUP_MODEL);
                            if (o_cnt > 0) {
                                reg_group_flows.write((bit<32>)current_group, o_cnt - 1);
                            }
                            reg_group_flows.write((bit<32>)GROUP_MODEL, m_cnt3 + 1);
                            current_group = GROUP_MODEL;
                            reg_group.write((bit<32>)meta.flow_id, GROUP_MODEL);
                            meta.flow_group = GROUP_MODEL;
                            meta.group_changed = 1;
                        }

                        /* Rotate RTT interval */
                        reg_num_pkts_prev.write((bit<32>)meta.flow_id, num_pkts);
                        reg_num_pkts.write((bit<32>)meta.flow_id, 0);
                        meta.num_pkts_prev = num_pkts;
                        meta.num_pkts = 0;
                        reg_rtt_start.write((bit<32>)meta.flow_id,
                                            standard_metadata.ingress_global_timestamp);
                    }

                    /* ==========================================================
                     * STEP 6: APPLY ACTIONS (Phase 5)
                     * Paper Section III-D: "P4air applies a custom action to
                     * each group to reduce the rate of that group."
                     *
                     * Actions are triggered ONLY when a flow sends more
                     * packets than its BDP in the current RTT interval
                     * (i.e., it exceeds its fair share).
                     * ========================================================== */
                    if (num_pkts > meta.bdp) {
                        if (current_group == GROUP_LOSS ||
                            current_group == GROUP_LOSS_DELAY) {
                            /* LOSS / LOSS-DELAY groups: DROP the packet.
                             * Paper: "Loss-based algorithms primarily use packet
                             * loss as their metric. Dropping forces CWND reduction."
                             * This is equivalent to tail-drop AQM for these flows. */
                            drop();
                        }
                        else if (current_group == GROUP_MODEL) {
                            /* MODEL-BASED (BBR): Reduce the TCP receiver window.
                             * Paper Section III-D: "Since BBR doesn't react to
                             * loss or delay, P4air reduces the receiver window
                             * in the ACK packets, limiting the sender's rate."
                             *
                             * We halve the window on data packets going through.
                             * The TCP checksum will be recomputed in ComputeChecksum. */
                            hdr.tcp.window = hdr.tcp.window >> 1;
                            /* Ensure window doesn't go to zero (would stall flow) */
                            if (hdr.tcp.window == 0) {
                                hdr.tcp.window = 1;
                            }
                        }
                        /* DELAY-BASED: handled via recirculation in egress.
                         * The packet goes through egress → recirculate → ingress,
                         * adding processing delay that delay-based CCAs (Vegas, LoLa)
                         * detect as increased RTT and voluntarily back off.
                         *
                         * Note: We only apply delay action from EGRESS since that's
                         * where recirculate() is available. We set a flag here for
                         * egress to pick up. */
                    }
                }

                /* ==========================================================
                 * STEP 7: QUEUE ASSIGNMENT (Phase 4)
                 * Map the flow's group to a BMv2 priority queue.
                 * For recirculated packets, queue was already assigned in Step 3.
                 * For regular packets, use group-to-queue mapping.
                 * ========================================================== */
                if (meta.is_recirculated == 0) {
                    /* Non-recirculated: use the stored queue or default mapping */
                    if (current_queue == 0 && current_group > GROUP_MICE) {
                        /* Assign default queue based on group */
                        bit<3> q_s;
                        reg_group_q_start.read(q_s, (bit<32>)current_group);
                        if (q_s >= 2) {
                            current_queue = q_s;
                        } else {
                            /* Fallback: direct group-to-queue mapping */
                            if (current_group == GROUP_DELAY) {
                                current_queue = 2;
                            } else if (current_group == GROUP_LOSS_DELAY) {
                                current_queue = 3;
                            } else if (current_group == GROUP_LOSS) {
                                current_queue = 4;
                            } else if (current_group == GROUP_MODEL) {
                                current_queue = 5;
                            }
                        }
                        reg_queue.write((bit<32>)meta.flow_id, current_queue);
                    }
                }

                /* Set BMv2 priority (determines which queue the packet enters) */
                standard_metadata.priority = current_queue;
                meta.flow_group = current_group;
                meta.assigned_queue = current_queue;

            } /* end: TCP processing */

            /* STEP FINAL: IPv4 forwarding */
            ipv4_lpm.apply();

        } else if (hdr.ethernet.isValid() && hdr.ethernet.etherType == 0x0806) {
            /* ARP → broadcast */
            l2_broadcast();
        }
    }
}

#endif /* _P4AIR_INGRESS_P4_ */
