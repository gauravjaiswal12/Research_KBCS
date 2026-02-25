/* egress.p4 */
#ifndef _EGRESS_P4_
#define _EGRESS_P4_

#include <core.p4>
#include <v1model.p4>
#include "headers.p4"

control MyEgress(inout parsed_headers_t hdr,
                 inout local_metadata_t meta,
                 inout standard_metadata_t standard_metadata) {
    apply {
        // Basic egress logic
    }
}

control MyDeparser(packet_out packet, in parsed_headers_t hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.tcp);
    }
}

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

control MyComputeChecksum(inout parsed_headers_t hdr, inout local_metadata_t meta) {
    apply {
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
    }
}

#endif
