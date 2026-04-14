#!/bin/bash
# simple_switch_pq.sh — KBCS Priority Queue Launch Wrapper
#
# KBCS uses 4 priority queues (0–3):
#   Q0 = RED    (Bronze)   — lowest; stochastic / AQM drop zone
#   Q1 = YELLOW (Silver)   — ECN-marked + window-halved flows
#   Q2 = GREEN  (Gold)     — compliant high-priority flows
#   Q3 = PLATINUM          — short-flow (mice) absolute fast lane
#
# Usage: Pass all simple_switch arguments after this script name.
exec simple_switch --priority-queues 4 "$@"
