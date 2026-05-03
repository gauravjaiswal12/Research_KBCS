# KBCS Phase 1 Enhancements — Walkthrough

## Summary
Implemented all 4 Phase 1 ("Quick Wins") enhancements from the KBCS Enhancement Roadmap.

## Changes Made

### [ingress.p4](file:///e:/Research%20Methodology/Project-Implementation/kbcs/p4src/ingress.p4) — 3 enhancements

**E2 — Congestion-Proportional Karma Penalty**
- Replaced fixed `PENALTY = 5` with a 4-tier dynamic penalty based on how far `flow_bytes` overshoots `BYTE_THRESHOLD`:
  - `> 240,000` (2× threshold) → penalty **15**
  - `> 180,000` (1.5× threshold) → penalty **10**
  - `> 150,000` (just over) → penalty **5**
  - Barely over → penalty **2**

**E3 — Graduated Enforcement Chain**
- GREEN → forward normally
- YELLOW → forward + ECN marking (in egress)
- RED → drop packet

> [!IMPORTANT]
> TCP window halving was **intentionally removed** from E3. Modifying `hdr.tcp.window` without `update_checksum_with_payload` would corrupt TCP checksums (this bug previously caused 0 Mbps). ECN marking in the IPv4 header is safe because its checksum IS recalculated.

**E8 — Idle-Flow Karma Recovery**
- Added `reg_last_seen` register (48-bit timestamps)
- If a flow is idle for > 500ms (~2+ RTTs), restore +5 karma
- Prevents permanent punishment of flows that pause and restart

### [egress.p4](file:///e:/Research%20Methodology/Project-Implementation/kbcs/p4src/egress.p4) — 1 enhancement

**E1 — ECN Marking for YELLOW Flows**
- YELLOW flows get ECN CE bits set: `hdr.ipv4.diffserv | 0x03`
- Sender's TCP stack reduces CWND without packet loss
- IPv4 checksum is recalculated by `MyComputeChecksum` ✅

## Verification

| Check | Status |
|-------|--------|
| P4 type safety (`bit<16>` penalty vs karma) | ✅ |
| IPv4 checksum recalculation covers `diffserv` | ✅ |
| No TCP header modifications (avoids checksum bug) | ✅ |
| `reg_last_seen` 48-bit matches `ingress_global_timestamp` | ✅ |
| Baseline files ([ingress_baseline.p4](file:///e:/Research%20Methodology/Project-Implementation/kbcs/p4src/ingress_baseline.p4), [kbcs_baseline.p4](file:///e:/Research%20Methodology/Project-Implementation/kbcs/p4src/kbcs_baseline.p4)) untouched | ✅ |
| [topology.py](file:///e:/Research%20Methodology/Project-Implementation/kbcs/topology.py) / [run_experiment.py](file:///e:/Research%20Methodology/Project-Implementation/kbcs/run_experiment.py) — no changes needed | ✅ |

## Next Step
Upload to the VM and run `make traffic` to test KBCS with these enhancements against the baseline.
