/* headers.p4 */
#ifndef _HEADERS_P4_
#define _HEADERS_P4_

#include <core.p4>
#include <v1model.p4>

typedef bit<9>  egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;

header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}

header ipv4_t {
    bit<4>    version;
    bit<4>    ihl;
    bit<8>    diffserv;
    bit<16>   totalLen;
    bit<16>   identification;
    bit<3>    flags;
    bit<13>   fragOffset;
    bit<8>    ttl;
    bit<8>    protocol;
    bit<16>   hdrChecksum;
    ip4Addr_t srcAddr;
    ip4Addr_t dstAddr;
}

header tcp_t {
    bit<16> srcPort;
    bit<16> dstPort;
    bit<32> seqNo;
    bit<32> ackNo;
    bit<4>  dataOffset;
    bit<3>  res;
    bit<3>  ecn;
    bit<6>  ctrl;
    bit<16> window;
    bit<16> checksum;
    bit<16> urgentPtr;
}

header kbcs_telemetry_t {
    bit<8>  karma_score;
    bit<2>  color;
    bit<3>  queue_id;
    bit<19> enq_qdepth;
    bit<1>  is_dropped;
    bit<7>  padding;
}

struct parsed_headers_t {
    ethernet_t       ethernet;
    ipv4_t           ipv4;
    tcp_t            tcp;
    kbcs_telemetry_t kbcs_telemetry;
}

struct local_metadata_t {
    bit<16> flow_id;
    bit<32> flow_bytes;
    bit<16> karma_score;
    bit<2>  flow_color;
    bit<2>  prev_color;
    bit<3>  queue_id;
    bit<1>  is_dropped;
    bit<1>  should_clone_e2e;
    bit<19> saved_qdepth;
}

#endif
