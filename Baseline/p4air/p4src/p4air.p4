/* =============================================================================
 * p4air.p4 — Top-Level P4 Program for P4air
 * =============================================================================
 * Assembles all P4air pipeline stages into a V1Switch (BMv2 architecture).
 *
 * Pipeline stages in order:
 *   1. P4airParser:          Extract Ethernet/IPv4/TCP headers
 *   2. P4airVerifyChecksum:  Validate IPv4 checksum
 *   3. P4airIngress:         Fingerprinting, Reallocation, Apply Actions, Forwarding
 *   4. P4airEgress:          Egress fingerprinting, group-change recirculation
 *   5. P4airComputeChecksum: Recompute IPv4 + TCP checksums
 *   6. P4airDeparser:        Reassemble outgoing packet
 *
 * Compile with:
 *   p4c-bm2-ss --p4v 16 -o build/p4air.json p4src/p4air.p4
 * =========================================================================== */

#include <core.p4>
#include <v1model.p4>

/* Include all component files */
#include "headers.p4"     /* Headers, metadata, constants */
#include "parser.p4"      /* Parser, deparser, checksums  */
#include "ingress.p4"     /* Ingress pipeline             */
#include "egress.p4"      /* Egress pipeline              */

/* Instantiate the V1Switch pipeline — order matches BMv2's processing stages */
V1Switch(
    P4airParser(),           /* 1. Parse incoming packet       */
    P4airVerifyChecksum(),   /* 2. Verify IPv4 header checksum */
    P4airIngress(),          /* 3. Ingress processing          */
    P4airEgress(),           /* 4. Egress processing           */
    P4airComputeChecksum(),  /* 5. Recompute checksums         */
    P4airDeparser()          /* 6. Deparse outgoing packet     */
) main;
