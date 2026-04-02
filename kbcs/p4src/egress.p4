/* egress.p4 — KBCS Enhanced Egress Pipeline                            */
/*                                                                        */
/* Handles:                                                               */
/*  [E3] Graduated enforcement for YELLOW flows (ECN + window halving   */
/*        was already done in ingress; egress just updates checksums)    */
/*  [E9] INT Karma Telemetry Stamping — optional observability header   */
/*        stamped in a custom diffserv field for external monitoring     */
/*  [E10] Color Transition Detection — observability via diffserv DSCP  */
/* ----------------------------------------------------------------------- */

#ifndef _EGRESS_P4_
#define _EGRESS_P4_

#include <core.p4>
#include <v1model.p4>
#include "headers.p4"

/* ================================================================== */
/* Egress Control                                                       */
/* ================================================================== */
control MyEgress(inout parsed_headers_t hdr,
                 inout local_metadata_t meta,
                 inout standard_metadata_t standard_metadata) {
    apply {
        /*
         * [E9] INT Karma Telemetry Stamping
         *
         * We reuse the IPv4 DSCP field (top 6 bits of diffserv) to
         * encode the flow's karma color and queue assignment for
         * external monitoring via Wireshark or a metrics collector.
         *
         * Encoding (DSCP bits [7:2]):
         *   bits [7:6] = flow_color (0=RED, 1=YELLOW, 2=GREEN, 3=PLATINUM)
         *   bits [5:3] = queue_id (0–3)
         *   bits [2:0] = reserved (ECN bits [1:0] already set by ingress)
         *
         * Note: This only stamps observability data; the ECN CE bits
         * set in ingress for YELLOW flows are preserved by masking.
         */
        if (hdr.ipv4.isValid()) {
            // Preserve ECN bits [1:0], overwrite DSCP bits [7:2] with telemetry
            bit<8> ecn_bits   = hdr.ipv4.diffserv & 0x03;       // keep ECN
            bit<8> color_dscp = (bit<8>)meta.flow_color << 6;    // top 2 bits
            bit<8> qid_dscp   = (bit<8>)meta.queue_id  << 3;    // next 3 bits
            hdr.ipv4.diffserv = color_dscp | qid_dscp | ecn_bits;
        }
    }
}

/* ================================================================== */
/* Deparser                                                             */
/* ================================================================== */
control MyDeparser(packet_out packet, in parsed_headers_t hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.tcp);
    }
}

/* ================================================================== */
/* Checksum Verification                                                */
/* ================================================================== */
control MyVerifyChecksum(inout parsed_headers_t hdr, inout local_metadata_t meta) {
    apply {
        verify_checksum(hdr.ipv4.isValid(),
            { hdr.ipv4.version,
              hdr.ipv4.ihl,
              hdr.ipv4.diffserv,
              hdr.ipv4.totalLen,
              hdr.ipv4.identification,
              hdr.ipv4.flags,
              hdr.ipv4.fragOffset,
              hdr.ipv4.ttl,
              hdr.ipv4.protocol,
              hdr.ipv4.srcAddr,
              hdr.ipv4.dstAddr },
            hdr.ipv4.hdrChecksum, HashAlgorithm.csum16);
    }
}

/* ================================================================== */
/* Checksum Recomputation                                               */
/* (Required because YELLOW flows have diffserv/window modified)        */
/* ================================================================== */
control MyComputeChecksum(inout parsed_headers_t hdr, inout local_metadata_t meta) {
    apply {
        // Recompute IPv4 header checksum (diffserv modified by ECN marking + E9)
        update_checksum(hdr.ipv4.isValid(),
            { hdr.ipv4.version,
              hdr.ipv4.ihl,
              hdr.ipv4.diffserv,
              hdr.ipv4.totalLen,
              hdr.ipv4.identification,
              hdr.ipv4.flags,
              hdr.ipv4.fragOffset,
              hdr.ipv4.ttl,
              hdr.ipv4.protocol,
              hdr.ipv4.srcAddr,
              hdr.ipv4.dstAddr },
            hdr.ipv4.hdrChecksum, HashAlgorithm.csum16);

        // Recompute TCP checksum (window may be halved for YELLOW flows [E3])
        update_checksum_with_payload(hdr.tcp.isValid(),
            { hdr.ipv4.srcAddr,
              hdr.ipv4.dstAddr,
              8w0,
              hdr.ipv4.protocol,
              hdr.ipv4.totalLen,
              hdr.tcp.srcPort,
              hdr.tcp.dstPort,
              hdr.tcp.seqNo,
              hdr.tcp.ackNo,
              hdr.tcp.dataOffset,
              hdr.tcp.res,
              hdr.tcp.ecn,
              hdr.tcp.ctrl,
              hdr.tcp.window,
              hdr.tcp.urgentPtr },
            hdr.tcp.checksum, HashAlgorithm.csum16);
    }
}

#endif
