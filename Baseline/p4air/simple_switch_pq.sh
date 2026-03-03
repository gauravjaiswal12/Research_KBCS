#!/bin/bash
# ==============================================================================
# simple_switch_pq.sh — Wrapper for BMv2 simple_switch with priority queues
# ==============================================================================
# P4air requires 8 priority queues (one per group/flow-type):
#   Q0: Ants        Q1: Mice       Q2-3: Delay-based
#   Q4-5: Loss-delay  Q6: Purely loss-based  Q7: Model-based
#
# Usage: Use this as the --behavioral-exe argument instead of 'simple_switch'
#   sudo python3 topology.py --behavioral-exe ./simple_switch_pq.sh --json ...
# ==============================================================================
exec simple_switch --priority-queues 8 "$@"
