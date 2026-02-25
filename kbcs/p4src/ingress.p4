/* ingress.p4 - KBCS Karma Engine (Full Architecture) */
#ifndef _INGRESS_P4_
#define _INGRESS_P4_

#include <core.p4>
#include <v1model.p4>
#include "headers.p4"

/* ============================================================
 * KBCS Tunable Constants
 * ============================================================ */
#define BYTE_THRESHOLD     120000   // Decay-weighted aggression threshold
#define KARMA_INIT         100      // All flows start with max karma
#define PENALTY            5        // Fast demotion for aggressors
#define REWARD             1        // Slow climb for good behavior
#define MAX_KARMA          100
#define HIGH_THRESHOLD     80       // Above: GREEN (high priority)
#define LOW_THRESHOLD      40       // Above: YELLOW, Below: RED
#define REG_SIZE           65536

/* Flow Color Constants */
#define COLOR_GREEN  2              // Well-behaved → high priority
#define COLOR_YELLOW 1              // Neutral → normal priority
#define COLOR_RED    0              // Aggressive → low priority / throttled

control MyIngress(inout parsed_headers_t hdr,
                  inout local_metadata_t meta,
                  inout standard_metadata_t standard_metadata) {

    /* ----------------------------------------------------------
     * Per-Flow State Registers
     * ---------------------------------------------------------- */
    register<bit<32>>(REG_SIZE) flow_bytes;    // Decay-weighted byte counter
    register<bit<16>>(REG_SIZE) flow_karma;    // Karma credit score (0-100)

    /* ----------------------------------------------------------
     * Actions
     * ---------------------------------------------------------- */
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

    /* ----------------------------------------------------------
     * Forwarding Table
     * ---------------------------------------------------------- */
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

    /* ----------------------------------------------------------
     * Apply Block - KBCS Pipeline
     * ---------------------------------------------------------- */
    apply {
        if (hdr.ipv4.isValid()) {

            /* ======================================================
             * KBCS KARMA ENGINE (active for TCP flows only)
             * Ping (ICMP) traffic is forwarded without karma processing
             * ====================================================== */
            if (hdr.tcp.isValid()) {

                /* ---- STEP 1: Flow Identification ---- */
                // Hash 5-tuple to get a stable per-flow index
                hash(meta.flow_id,
                     HashAlgorithm.crc16,
                     (bit<16>)0,
                     { hdr.ipv4.srcAddr,
                       hdr.ipv4.dstAddr,
                       hdr.tcp.srcPort,
                       hdr.tcp.dstPort,
                       hdr.ipv4.protocol },
                     (bit<32>)REG_SIZE);

                /* ---- STEP 2: State Read ---- */
                flow_bytes.read(meta.flow_bytes, (bit<32>)meta.flow_id);
                flow_karma.read(meta.karma_score, (bit<32>)meta.flow_id);

                /* ---- STEP 3: Aggression Detection (Decay-Based) ----
                 * Exponential decay: halve the old value, add new packet size
                 * This approximates a sliding window without timers.
                 * If a flow sends bursts, flow_bytes grows quickly.
                 * If a flow is quiet, flow_bytes decays toward 0.
                 */
                meta.flow_bytes = (meta.flow_bytes >> 1) + standard_metadata.packet_length;
                flow_bytes.write((bit<32>)meta.flow_id, meta.flow_bytes);

                /* ---- STEP 4: Karma Update Logic ---- */
                // Initialize new flows with max karma
                if (meta.karma_score == 0 && meta.flow_bytes == standard_metadata.packet_length) {
                    meta.karma_score = KARMA_INIT;
                } else {
                    if (meta.flow_bytes > BYTE_THRESHOLD) {
                        // PENALIZE: Flow exceeds fair share → karma drops fast
                        if (meta.karma_score > PENALTY) {
                            meta.karma_score = meta.karma_score - PENALTY;
                        } else {
                            meta.karma_score = 0;
                        }
                    } else {
                        // REWARD: Flow is well-behaved → karma rises slowly
                        meta.karma_score = meta.karma_score + REWARD;
                        if (meta.karma_score > MAX_KARMA) {
                            meta.karma_score = MAX_KARMA;
                        }
                    }
                }
                // Write updated karma back to register
                flow_karma.write((bit<32>)meta.flow_id, meta.karma_score);

                /* ---- STEP 5: Flow Coloring ----
                 * Classify flow based on karma score into
                 * GREEN (trusted), YELLOW (neutral), RED (penalized)
                 */
                if (meta.karma_score > HIGH_THRESHOLD) {
                    meta.flow_color = COLOR_GREEN;
                } else if (meta.karma_score > LOW_THRESHOLD) {
                    meta.flow_color = COLOR_YELLOW;
                } else {
                    meta.flow_color = COLOR_RED;
                }

                /* ---- STEP 6: Queue Mapping ----
                 * Map flow color to a priority queue via standard_metadata.priority
                 *   GREEN  → priority 2 (high priority queue)
                 *   YELLOW → priority 1 (normal queue)
                 *   RED    → priority 0 (low priority queue / throttled)
                 *
                 * Note: BMv2 requires --priority-queues N flag at startup
                 * for this to have scheduling effect. When unavailable,
                 * RED flows get packets dropped as AQM enforcement.
                 */
                standard_metadata.priority = (bit<3>)meta.flow_color;
                meta.queue_id = (bit<3>)meta.flow_color;

                /* ---- STEP 7: AQM Enforcement ----
                 * Secondary enforcement: drop packets from RED flows.
                 * This forces loss-based CC (CUBIC) to reduce CWND.
                 * Functionally equivalent to a Bronze queue with tail-drop.
                 */
                if (meta.flow_color == COLOR_RED) {
                    drop();
                }
            }

            /* ---- STEP 8: IPv4 Forwarding ----
             * Forwarding is independent of karma logic.
             * If drop() was called, mark_to_drop flag overrides forwarding.
             */
            ipv4_lpm.apply();

        } else if (hdr.ethernet.isValid() && hdr.ethernet.etherType == 0x0806) {
            // ARP broadcast
            l2_broadcast();
        }
    }
}

#endif
