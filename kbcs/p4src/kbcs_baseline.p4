/* kbcs_baseline.p4 - Main P4 program WITHOUT karma (for baseline comparison) */
#include <core.p4>
#include <v1model.p4>

#include "headers.p4"
#include "parser.p4"
#include "ingress_baseline.p4"
#include "egress.p4"

V1Switch(
    MyParser(),
    MyVerifyChecksum(),
    MyIngress(),
    MyEgress(),
    MyComputeChecksum(),
    MyDeparser()
) main;
