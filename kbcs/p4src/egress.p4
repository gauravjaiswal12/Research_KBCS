/* egress.p4 */
#ifndef _EGRESS_P4_
#define _EGRESS_P4_

#include <core.p4>
#include <v1model.p4>
#include "headers.p4"

control MyEgress(inout parsed_headers_t hdr,
                 inout local_metadata_t meta,
                 inout standard_metadata_t standard_metadata) {
    /* Persistent register to expose enq_qdepth to metrics_exporter via CLI */
    register<bit<19>>(8) reg_qdepth;

    apply {
        if (standard_metadata.instance_type == 0) {
            meta.saved_qdepth = standard_metadata.enq_qdepth;
            /* Save qdepth indexed by egress port so exporter can poll it */
            reg_qdepth.write((bit<32>)standard_metadata.egress_port, standard_metadata.enq_qdepth);
            if (meta.should_clone_e2e == 1) {
                clone(CloneType.E2E, 4);
            }
        }

        /* ---- E9 & E10: INT Telemetry Stamping for Mirrored Packets ----
         * We populate INT headers only for cloned packets (instance_type == 1 or 2)
         * to avoid breaking standard IPv4 receivers with unknown headers.
         */
        if (standard_metadata.instance_type == 1 || standard_metadata.instance_type == 2) {
            hdr.kbcs_telemetry.setValid();
            hdr.ethernet.etherType = 0x1234;
            hdr.kbcs_telemetry.karma_score = (bit<8>)meta.karma_score;
            hdr.kbcs_telemetry.color = meta.flow_color;
            hdr.kbcs_telemetry.queue_id = (bit<3>)standard_metadata.priority;
            
            if (standard_metadata.instance_type == 2) {
                // E2E clone from Egress (Admitted packets)
                hdr.kbcs_telemetry.enq_qdepth = meta.saved_qdepth;
            } else {
                // I2E clone from Ingress (Dropped packets)
                hdr.kbcs_telemetry.enq_qdepth = 0;
            }
            
            hdr.kbcs_telemetry.is_dropped = meta.is_dropped;
            hdr.kbcs_telemetry.padding = 0;
        }

        /* ---- E1: ECN Marking for YELLOW Flows ----
         * mark YELLOW flows with ECN Congestion Experienced (CE).
         */
        if (hdr.ipv4.isValid() && meta.flow_color == 1) {  // YELLOW
            hdr.ipv4.diffserv = hdr.ipv4.diffserv | 8w0x03;  // Set CE bits
        }
    }
}

control MyDeparser(packet_out packet, in parsed_headers_t hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.kbcs_telemetry);
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
