/* parser.p4 */
#ifndef _PARSER_P4_
#define _PARSER_P4_

#include <core.p4>
#include <v1model.p4>
#include "headers.p4"

parser MyParser(packet_in packet,
                out parsed_headers_t hdr,
                inout local_metadata_t meta,
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

#endif
