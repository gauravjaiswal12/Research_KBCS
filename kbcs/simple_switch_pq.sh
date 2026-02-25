#!/bin/bash
# Wrapper script for simple_switch with priority queues enabled
# KBCS requires 3 priority queues: Gold (2), Silver (1), Bronze (0)
exec simple_switch --priority-queues 3 "$@"
