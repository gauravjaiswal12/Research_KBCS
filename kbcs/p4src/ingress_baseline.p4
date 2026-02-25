/* ingress_baseline.p4 - Plain forwarding WITHOUT karma logic */
#ifndef _INGRESS_BASELINE_P4_
#define _INGRESS_BASELINE_P4_

#include <core.p4>
#include <v1model.p4>
#include "headers.p4"

control MyIngress(inout parsed_headers_t hdr,
                  inout local_metadata_t meta,
                  inout standard_metadata_t standard_metadata) {

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
            // NO KARMA LOGIC - just forward
            // All flows share the same default priority (FIFO)
            ipv4_lpm.apply();
        } else if (hdr.ethernet.isValid() && hdr.ethernet.etherType == 0x0806) {
            l2_broadcast();
        }
    }
}

#endif
