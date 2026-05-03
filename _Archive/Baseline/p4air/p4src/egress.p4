/* =============================================================================
 * egress.p4 — P4air Egress Pipeline (COMPLETE: Phases 2-5)
 * =============================================================================
 * Implements:
 *   ✅ Phase 2: Register declarations + enqueue depth tracking
 *   ✅ Phase 3: Fingerprinting module (egress part):
 *      - Max enqueue depth tracking per RTT interval
 *      - Aggressiveness computation (queue fill rate)
 *      - Streak counting (consecutive aggressive RTT intervals)
 *      - Group reclassification: delay → loss-delay → purely-loss
 *      - Recirculation on group change (back to ingress for register update)
 *   ✅ Phase 4: Reallocation — recirculate on group change triggers ingress realloc
 *   ✅ Phase 5: Apply Actions (egress part):
 *      - DELAY action for delay-based flows (recirculate to add processing delay)
 *
 * Why egress for the delay action?
 *   recirculate() can only be called from egress in v1model.
 *   Delay-based CCAs (Vegas, LoLa) use RTT as their primary metric.
 *   By recirculating their packets (extra round through the pipeline),
 *   we artificially increase the RTT, causing them to back off voluntarily.
 * =========================================================================== */

#ifndef _P4AIR_EGRESS_P4_
#define _P4AIR_EGRESS_P4_

#include <core.p4>
#include <v1model.p4>
#include "headers.p4"

control P4airEgress(inout parsed_headers_t hdr,
                    inout p4air_metadata_t meta,
                    inout standard_metadata_t standard_metadata) {

    /* Field list ID for recirculate — tells BMv2 which metadata fields
     * to preserve when recirculating a packet back to ingress. */
    @name("recirc_fl")
    action do_recirculate() {
        recirculate_preserving_field_list((bit<8>)0);
    }

    /* =========================================================================
     * EGRESS-SIDE REGISTERS
     * ======================================================================= */

    /* reg_max_enq: max enqueue depth in current RTT (captures peak queue fill) */
    register<bit<32>>(FLOW_TABLE_SIZE) reg_max_enq;

    /* reg_max_enq_prev: max enqueue depth from previous RTT interval */
    register<bit<32>>(FLOW_TABLE_SIZE) reg_max_enq_prev;

    /* reg_aggr_streak: consecutive RTTs where queue grew (key reclassification metric) */
    register<bit<8>>(FLOW_TABLE_SIZE) reg_aggr_streak;

    /* reg_egress_rtt_start: egress-side RTT interval start timestamp */
    register<bit<48>>(FLOW_TABLE_SIZE) reg_egress_rtt_start;

    /* reg_egress_rtt: egress copy of estimated RTT */
    register<bit<48>>(FLOW_TABLE_SIZE) reg_egress_rtt;

    /* reg_egress_group: egress shadow of flow group (for detecting changes) */
    register<bit<3>>(FLOW_TABLE_SIZE) reg_egress_group;

    /* =========================================================================
     * APPLY BLOCK — Egress Fingerprinting + Reclassification
     * ======================================================================= */
    apply {
        if (hdr.tcp.isValid()) {

            /* ==========================================================
             * STEP 1: FLOW IDENTIFICATION (recompute hash for safety)
             * Same hash as ingress — gives identical flow_id.
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
             * STEP 2: READ EGRESS-SIDE STATE
             * ========================================================== */
            bit<32> max_enq;
            bit<32> max_enq_prev;
            bit<8>  aggr_streak;
            bit<48> eg_rtt_start;
            bit<48> eg_rtt;
            bit<3>  eg_group;

            reg_max_enq.read(max_enq, (bit<32>)meta.flow_id);
            reg_max_enq_prev.read(max_enq_prev, (bit<32>)meta.flow_id);
            reg_aggr_streak.read(aggr_streak, (bit<32>)meta.flow_id);
            reg_egress_rtt_start.read(eg_rtt_start, (bit<32>)meta.flow_id);
            reg_egress_rtt.read(eg_rtt, (bit<32>)meta.flow_id);
            reg_egress_group.read(eg_group, (bit<32>)meta.flow_id);

            /* Sync RTT from ingress metadata if egress doesn't have it yet.
             * This happens once when RTT is first estimated in ingress. */
            if (eg_rtt == 0 && meta.rtt_estimate > 0) {
                eg_rtt = meta.rtt_estimate;
                reg_egress_rtt.write((bit<32>)meta.flow_id, eg_rtt);
                eg_rtt_start = standard_metadata.egress_global_timestamp;
                reg_egress_rtt_start.write((bit<32>)meta.flow_id, eg_rtt_start);
            }

            /* Sync group from ingress metadata */
            if (eg_group == 0 && meta.flow_group > 0) {
                eg_group = meta.flow_group;
                reg_egress_group.write((bit<32>)meta.flow_id, eg_group);
            }

            /* ==========================================================
             * STEP 3: TRACK MAX ENQUEUE DEPTH
             * standard_metadata.enq_qdepth gives the queue depth when
             * this packet was enqueued. We track the maximum per RTT.
             * ========================================================== */
            bit<32> current_enq = (bit<32>)standard_metadata.enq_qdepth;
            if (current_enq > max_enq) {
                max_enq = current_enq;
                reg_max_enq.write((bit<32>)meta.flow_id, max_enq);
            }

            /* ==========================================================
             * STEP 3.5: APPLY ACTIONS — DELAY for delay-based flows
             * Paper Section III-D: "For delay-based algorithms, P4air
             * recirculates packets causing additional processing delay.
             * Since these CCAs use RTT as their primary metric, the
             * added delay causes them to voluntarily back off."
             *
             * This must happen in egress because recirculate() is only
             * available here in v1model. The BDP check was done in
             * ingress and the result is in meta.num_pkts / meta.bdp.
             *
             * We only recirculate if:
             *   1. Flow is delay-based (GROUP_DELAY)
             *   2. Flow has exceeded its BDP (sending above fair share)
             *   3. Packet is not already a recirculated copy (prevent loops)
             * ========================================================== */
            if (eg_group == GROUP_DELAY &&
                meta.num_pkts > meta.bdp &&
                standard_metadata.instance_type == 0) {
                /* Recirculate: packet goes through the pipeline again.
                 * This adds ~1 pipeline processing time worth of delay,
                 * which delay-based CCAs detect as increased RTT. */
                do_recirculate();
            }

            /* ==========================================================
             * STEP 4: RTT INTERVAL BOUNDARY CHECK (Egress Side)
             * At the end of each RTT interval, compute aggressiveness
             * and check for group reclassification.
             * ========================================================== */
            if (eg_rtt > 0) {
                bit<48> eg_elapsed;
                eg_elapsed = standard_metadata.egress_global_timestamp - eg_rtt_start;

                if (eg_elapsed > eg_rtt) {
                    /* ---- EGRESS RTT INTERVAL BOUNDARY ---- */

                    /* ----- AGGRESSIVENESS COMPUTATION -----
                     * Paper Section III-A, Eq. for aggressiveness:
                     * "If max_enq_current > max_enq_prev × 1.01, the flow
                     * is filling queues aggressively → increment streak."
                     *
                     * Hardware approx: max_enq > max_enq_prev + (max_enq_prev / 100)
                     * For small queue values, use max_enq > max_enq_prev + 1 as floor.
                     * On BMv2 we can do proper division; using shift approx for hardware compat.
                     */
                    bit<32> growth_threshold;
                    /* Approx 1%: max_enq_prev >> 7 ≈ 0.78%, close enough for detection */
                    growth_threshold = max_enq_prev + (max_enq_prev >> 7);
                    /* Floor: at least max_enq_prev + 1 (for small values) */
                    if (growth_threshold <= max_enq_prev) {
                        growth_threshold = max_enq_prev + 1;
                    }

                    if (max_enq > growth_threshold) {
                        /* Queue is growing → flow is aggressive this RTT */
                        aggr_streak = aggr_streak + 1;
                    } else {
                        /* Queue stopped growing → reset streak */
                        aggr_streak = 0;
                    }
                    reg_aggr_streak.write((bit<32>)meta.flow_id, aggr_streak);

                    /* ----- GROUP RECLASSIFICATION (queue-fill based) -----
                     * Paper Section III-A:
                     * delay → loss-delay: aggr_streak >= mLD (4)
                     * loss-delay → purely-loss: aggr_streak >= mPL (12)
                     *
                     * These transitions only apply to long-lived flows
                     * (not ants, mice, or already-model-based).
                     */
                    meta.group_changed = 0;

                    if (eg_group == GROUP_DELAY && aggr_streak >= (bit<8>)M_LD) {
                        /* DELAY → LOSS-DELAY transition.
                         * The flow has been filling queues for mLD consecutive
                         * RTT intervals, suggesting it reacts to loss + delay. */
                        meta.prev_group = eg_group;
                        eg_group = GROUP_LOSS_DELAY;
                        meta.flow_group = GROUP_LOSS_DELAY;
                        meta.group_changed = 1;
                        reg_egress_group.write((bit<32>)meta.flow_id, GROUP_LOSS_DELAY);
                    }
                    else if (eg_group == GROUP_LOSS_DELAY && aggr_streak >= (bit<8>)M_PL) {
                        /* LOSS-DELAY → PURELY-LOSS transition.
                         * Continuous queue filling for mPL RTTs indicates
                         * the flow only reacts to actual packet loss. */
                        meta.prev_group = eg_group;
                        eg_group = GROUP_LOSS;
                        meta.flow_group = GROUP_LOSS;
                        meta.group_changed = 1;
                        reg_egress_group.write((bit<32>)meta.flow_id, GROUP_LOSS);
                    }

                    /* ----- ROTATE RTT INTERVAL -----
                     * Save current max_enq as previous, reset current. */
                    reg_max_enq_prev.write((bit<32>)meta.flow_id, max_enq);
                    reg_max_enq.write((bit<32>)meta.flow_id, 0);

                    /* Start new egress RTT interval */
                    reg_egress_rtt_start.write((bit<32>)meta.flow_id,
                                               standard_metadata.egress_global_timestamp);

                    /* ----- RECIRCULATE ON GROUP CHANGE -----
                     * If the group was reclassified, recirculate the packet
                     * so ingress can update the master group register and
                     * run the reallocation algorithm. */
                    if (meta.group_changed == 1) {
                        do_recirculate();
                    }

                } /* end: egress RTT interval boundary */
            } /* end: if egress RTT is known */

            /* Store final metadata values */
            meta.max_enq_len = max_enq;
            meta.aggr_streak = aggr_streak;

        } /* end: TCP processing */
    }
}

#endif /* _P4AIR_EGRESS_P4_ */
