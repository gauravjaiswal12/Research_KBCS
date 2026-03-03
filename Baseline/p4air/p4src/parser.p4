/* =============================================================================
 * parser.p4 — P4air Parser, Deparser, and Checksum Controls
 * =============================================================================
 * Parser:          Extracts Ethernet → IPv4 → TCP headers from raw packets.
 * Deparser:        Reassembles headers back into outgoing packets.
 * VerifyChecksum:  Validates IPv4 header checksum on ingress.
 * ComputeChecksum: Recomputes IPv4 + TCP checksums on egress (needed when
 *                  Apply Actions modifies the TCP window field).
 * =========================================================================== */

#ifndef _P4AIR_PARSER_P4_
#define _P4AIR_PARSER_P4_

#include <core.p4>
#include <v1model.p4>
#include "headers.p4"

/* =============================================================================
 * Parser — extracts packet headers in order: Ethernet → IPv4 → TCP
 * Non-IPv4 or non-TCP packets are accepted without full parsing.
 * =========================================================================== */
parser P4airParser(packet_in packet,
                   out parsed_headers_t hdr,
                   inout p4air_metadata_t meta,
                   inout standard_metadata_t standard_metadata) {

    /* Entry state: start extracting from the Ethernet header */
    state start {
        transition parse_ethernet;
    }

    /* Parse Ethernet header, then branch on etherType */
    state parse_ethernet {
        packet.extract(hdr.ethernet);
        transition select(hdr.ethernet.etherType) {
            16w0x0800: parse_ipv4;   /* IPv4 payload */
            default: accept;          /* ARP, other → accept without further parsing */
        }
    }

    /* Parse IPv4 header, then branch on protocol */
    state parse_ipv4 {
        packet.extract(hdr.ipv4);
        transition select(hdr.ipv4.protocol) {
            8w6: parse_tcp;           /* TCP (protocol number 6) */
            default: accept;          /* UDP, ICMP, etc. → accept */
        }
    }

    /* Parse TCP header — this is the main target for P4air */
    state parse_tcp {
        packet.extract(hdr.tcp);
        transition accept;
    }
}

/* =============================================================================
 * VerifyChecksum — validates the IPv4 header checksum on arriving packets
 * This runs BEFORE ingress processing. Corrupted packets get flagged.
 * =========================================================================== */
control P4airVerifyChecksum(inout parsed_headers_t hdr,
                            inout p4air_metadata_t meta) {
    apply {
        verify_checksum(
            hdr.ipv4.isValid(),
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
            hdr.ipv4.hdrChecksum,
            HashAlgorithm.csum16
        );
    }
}

/* =============================================================================
 * ComputeChecksum — recomputes checksums AFTER egress processing
 * Required because:
 *   1) TTL is decremented during forwarding (changes IPv4 checksum)
 *   2) Apply Actions may modify tcp.window (changes TCP checksum)
 * =========================================================================== */
control P4airComputeChecksum(inout parsed_headers_t hdr,
                             inout p4air_metadata_t meta) {
    apply {
        /* Recompute IPv4 header checksum */
        update_checksum(
            hdr.ipv4.isValid(),
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
            hdr.ipv4.hdrChecksum,
            HashAlgorithm.csum16
        );

        /* Recompute TCP checksum (pseudo-header + TCP header + payload).
         * This is CRITICAL when the Apply Actions module modifies tcp.window.
         * Uses the standard TCP pseudo-header fields for checksum calculation. */
        update_checksum_with_payload(
            hdr.tcp.isValid(),
            { hdr.ipv4.srcAddr,       /* Pseudo-header: source IP   */
              hdr.ipv4.dstAddr,       /* Pseudo-header: dest IP     */
              8w0,                     /* Pseudo-header: zero        */
              hdr.ipv4.protocol,      /* Pseudo-header: protocol    */
              /* TCP header fields */
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
            hdr.tcp.checksum,
            HashAlgorithm.csum16
        );
    }
}

/* =============================================================================
 * Deparser — emits headers back onto the outgoing packet
 * Order must match the parser extraction order.
 * Headers that are not valid are silently skipped by emit().
 * =========================================================================== */
control P4airDeparser(packet_out packet, in parsed_headers_t hdr) {
    apply {
        packet.emit(hdr.ethernet);   /* Always emit Ethernet     */
        packet.emit(hdr.ipv4);       /* Emit IPv4 if parsed      */
        packet.emit(hdr.tcp);        /* Emit TCP if parsed       */
    }
}

#endif /* _P4AIR_PARSER_P4_ */
