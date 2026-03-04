/* =============================================================================
 * diff_queues.p4 — Baseline: Hash-Based Static Queue Assignment
 * =============================================================================
 * Forwards IPv4 packets AND assigns each flow to a priority queue based on
 * a simple 5-tuple hash (hash % 8). No fingerprinting or classification.
 *
 * This baseline tests whether queue isolation ALONE (without intelligent
 * CCA-based grouping) improves fairness compared to a single FIFO queue.
 *
 * Key difference from P4air:
 *   - P4air groups flows by CCA type (delay, loss, model) → matching actions
 *   - This baseline groups flows RANDOMLY by hash → no matching actions
 *   - Flows from the same CCA may end up in different queues (random split)
 *
 * Expected result: Jain's Fairness Index should be HIGHER than No AQM
 * (because queue separation prevents total starvation) but LOWER than P4air
 * (because random grouping doesn't match CCAs to appropriate actions).
 * =========================================================================== */

#include <core.p4>
#include <v1model.p4>
#include "headers.p4"

/* ---------- Parser ---------- */
parser P4airParser(packet_in packet,
                   out parsed_headers_t hdr,
                   inout p4air_metadata_t meta,
                   inout standard_metadata_t standard_metadata) {
    state start {
        transition parse_ethernet;
    }
    state parse_ethernet {
        packet.extract(hdr.ethernet);
        transition select(hdr.ethernet.etherType) {
            16w0x0800: parse_ipv4;
            default: accept;
        }
    }
    state parse_ipv4 {
        packet.extract(hdr.ipv4);
        transition select(hdr.ipv4.protocol) {
            8w6: parse_tcp;
            default: accept;
        }
    }
    state parse_tcp {
        packet.extract(hdr.tcp);
        transition accept;
    }
}

/* ---------- Ingress: Forward + Static Queue Assignment ---------- */
control P4airIngress(inout parsed_headers_t hdr,
                     inout p4air_metadata_t meta,
                     inout standard_metadata_t standard_metadata) {

    /* Drop action */
    action drop() {
        mark_to_drop(standard_metadata);
    }

    /* L3 forwarding */
    action ipv4_forward(macAddr_t dstAddr, egressSpec_t port) {
        standard_metadata.egress_spec = port;
        hdr.ethernet.dstAddr = dstAddr;
        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
    }

    /* ARP broadcast */
    action l2_broadcast() {
        standard_metadata.mcast_grp = 1;
    }

    /* LPM forwarding table */
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

    apply {
        if (hdr.ipv4.isValid()) {

            /* --- STATIC QUEUE ASSIGNMENT (hash-based) ---
             * Hash the 5-tuple to get a flow ID, then use the low 3 bits
             * as the priority queue index (0-7).
             *
             * This gives each flow a "random" but consistent queue.
             * Unlike P4air, there is NO intelligence about CCA type —
             * a Cubic flow and a Vegas flow might end up in the same queue,
             * or they might not. It's purely hash-based. */
            if (hdr.tcp.isValid()) {
                hash(meta.flow_id,
                     HashAlgorithm.crc16,
                     (bit<16>)0,
                     { hdr.ipv4.srcAddr,
                       hdr.ipv4.dstAddr,
                       hdr.tcp.srcPort,
                       hdr.tcp.dstPort,
                       hdr.ipv4.protocol },
                     (bit<16>)FLOW_TABLE_SIZE);

                /* Assign queue = flow_id % 8 (using low 3 bits) */
                standard_metadata.priority = (bit<3>)meta.flow_id;
            }

            /* Forward the packet normally */
            ipv4_lpm.apply();

        } else if (hdr.ethernet.isValid() && hdr.ethernet.etherType == 0x0806) {
            l2_broadcast();
        }
    }
}

/* ---------- Egress: empty ---------- */
control P4airEgress(inout parsed_headers_t hdr,
                    inout p4air_metadata_t meta,
                    inout standard_metadata_t standard_metadata) {
    apply { /* No egress processing for this baseline */ }
}

/* ---------- Checksum controls ---------- */
control P4airVerifyChecksum(inout parsed_headers_t hdr,
                            inout p4air_metadata_t meta) {
    apply {
        verify_checksum(
            hdr.ipv4.isValid(),
            { hdr.ipv4.version, hdr.ipv4.ihl, hdr.ipv4.diffserv,
              hdr.ipv4.totalLen, hdr.ipv4.identification,
              hdr.ipv4.flags, hdr.ipv4.fragOffset,
              hdr.ipv4.ttl, hdr.ipv4.protocol,
              hdr.ipv4.srcAddr, hdr.ipv4.dstAddr },
            hdr.ipv4.hdrChecksum, HashAlgorithm.csum16);
    }
}

control P4airComputeChecksum(inout parsed_headers_t hdr,
                             inout p4air_metadata_t meta) {
    apply {
        update_checksum(
            hdr.ipv4.isValid(),
            { hdr.ipv4.version, hdr.ipv4.ihl, hdr.ipv4.diffserv,
              hdr.ipv4.totalLen, hdr.ipv4.identification,
              hdr.ipv4.flags, hdr.ipv4.fragOffset,
              hdr.ipv4.ttl, hdr.ipv4.protocol,
              hdr.ipv4.srcAddr, hdr.ipv4.dstAddr },
            hdr.ipv4.hdrChecksum, HashAlgorithm.csum16);
    }
}

/* ---------- Deparser ---------- */
control P4airDeparser(packet_out packet, in parsed_headers_t hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.tcp);
    }
}

/* ---------- V1Switch ---------- */
V1Switch(
    P4airParser(),
    P4airVerifyChecksum(),
    P4airIngress(),
    P4airEgress(),
    P4airComputeChecksum(),
    P4airDeparser()
) main;
