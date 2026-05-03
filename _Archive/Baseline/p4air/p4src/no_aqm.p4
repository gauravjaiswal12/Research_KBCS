/* =============================================================================
 * no_aqm.p4 — Baseline: Simple IPv4 Forwarding (No AQM, No Queue Management)
 * =============================================================================
 * This is the simplest baseline: just forwards IPv4 packets using LPM.
 * No registers, no fingerprinting, no queue management.
 * All flows share a single FIFO queue (BMv2 default behavior).
 *
 * Purpose: demonstrates the WORST-CASE fairness scenario where loss-based
 * CCAs (Cubic, Reno) dominate delay-based ones (Vegas, LoLa) because
 * there is no mechanism to separate or equalize them.
 *
 * Expected result: Jain's Fairness Index should be LOW because aggressive
 * loss-based flows fill the queue, increasing RTT for delay-based flows
 * which then voluntarily reduce their rate, getting starved.
 * =========================================================================== */

#include <core.p4>
#include <v1model.p4>
#include "headers.p4"

/* ---------- Parser (reuse same header definitions) ---------- */
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

/* ---------- Ingress: Just forward packets ---------- */
control P4airIngress(inout parsed_headers_t hdr,
                     inout p4air_metadata_t meta,
                     inout standard_metadata_t standard_metadata) {

    /* Drop action for default/miss */
    action drop() {
        mark_to_drop(standard_metadata);
    }

    /* Standard L3 forwarding: set egress port and rewrite dst MAC */
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
            /* No queue management — just forward.
             * All packets use the default FIFO queue (priority 0). */
            ipv4_lpm.apply();
        } else if (hdr.ethernet.isValid() && hdr.ethernet.etherType == 0x0806) {
            l2_broadcast();
        }
    }
}

/* ---------- Egress: empty (no processing needed) ---------- */
control P4airEgress(inout parsed_headers_t hdr,
                    inout p4air_metadata_t meta,
                    inout standard_metadata_t standard_metadata) {
    apply { /* Nothing to do in egress for this baseline */ }
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

/* ---------- V1Switch pipeline assembly ---------- */
V1Switch(
    P4airParser(),
    P4airVerifyChecksum(),
    P4airIngress(),
    P4airEgress(),
    P4airComputeChecksum(),
    P4airDeparser()
) main;
