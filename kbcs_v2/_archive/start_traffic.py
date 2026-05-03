#!/usr/bin/env python3
"""
KBCS v2 — Traffic Starter
==========================
This script connects to a running Mininet instance and starts
iperf traffic on all 8 sender hosts.

It uses subprocess to find Mininet host PIDs and execute commands
inside their network namespaces using nsenter.

Usage: sudo python3 start_traffic.py [--duration 300]
"""

import subprocess
import sys
import time
import os
import re

DURATION = 300
for i, arg in enumerate(sys.argv):
    if arg == "--duration" and i + 1 < len(sys.argv):
        DURATION = int(sys.argv[i + 1])

def find_mininet_pids():
    """Find PIDs of Mininet host bash processes."""
    result = subprocess.run(
        ["ps", "aux"], capture_output=True, text=True
    )
    pids = {}
    for line in result.stdout.split('\n'):
        # Mininet hosts show as: bash --norc --noediting -is mininet:h1
        m = re.search(r'(\d+).*bash.*mininet:(h\d+)', line)
        if m:
            pid = m.group(1)
            host = m.group(2)
            pids[host] = pid
    return pids

def run_in_host(host_pid, cmd, background=False):
    """Run a command inside a Mininet host's network namespace."""
    full_cmd = f"nsenter -t {host_pid} -n -- {cmd}"
    if background:
        full_cmd += " &"
    try:
        result = subprocess.run(
            full_cmd, shell=True, capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return True  # Background commands may not return

def main():
    print("=" * 60)
    print("  KBCS v2 — Traffic Starter")
    print(f"  Duration: {DURATION}s")
    print("=" * 60)

    # Find Mininet host PIDs
    pids = find_mininet_pids()
    print(f"\n  Found {len(pids)} Mininet hosts:")
    for host, pid in sorted(pids.items()):
        print(f"    {host}: PID {pid}")

    if len(pids) < 12:
        print(f"\n  ⚠ Expected 12 hosts, found {len(pids)}. Some may be missing.")

    # Check required hosts
    required = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8', 'h9', 'h10', 'h11', 'h12']
    missing = [h for h in required if h not in pids]
    if missing:
        print(f"  ✗ Missing hosts: {missing}")
        sys.exit(1)

    # Start iperf servers on receiver hosts (h9, h10, h11, h12)
    print("\n  Starting iperf servers...")
    for server in ['h9', 'h10', 'h11', 'h12']:
        subprocess.Popen(
            f"nsenter -t {pids[server]} -n -- iperf -s -D",
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print(f"    ✓ {server} iperf server started")

    time.sleep(1)

    # Start client flows
    # S1 flows: h1-h4 → h9/h10 (10.0.3.x) via S1→S3
    # S2 flows: h5-h8 → h11/h12 (10.0.4.x) via S2→S4
    print("\n  Starting client flows...")

    flows = [
        # (host, server_ip, parallel_streams, label)
        ("h1", "10.0.3.1", 1, "CUBIC (gentle)"),
        ("h2", "10.0.3.1", 4, "BBR-sim (aggressive)"),
        ("h3", "10.0.3.2", 1, "Vegas (gentle)"),
        ("h4", "10.0.3.2", 3, "Illinois-sim (aggressive)"),
        ("h5", "10.0.4.1", 1, "CUBIC (gentle)"),
        ("h6", "10.0.4.1", 4, "BBR-sim (aggressive)"),
        ("h7", "10.0.4.2", 1, "Vegas (gentle)"),
        ("h8", "10.0.4.2", 3, "Illinois-sim (aggressive)"),
    ]

    for host, server_ip, parallel, label in flows:
        log_file = f"/tmp/kbcs_{host}.log"
        cmd = f"nsenter -t {pids[host]} -n -- iperf -c {server_ip} -t {DURATION} -P {parallel}"
        proc = subprocess.Popen(
            cmd, shell=True,
            stdout=open(log_file, 'w'),
            stderr=subprocess.STDOUT
        )
        print(f"    ✓ {host} ({label}, {parallel}P) → {server_ip} [PID: {proc.pid}]")

    print(f"\n  All 8 flows started! Duration: {DURATION}s")
    print(f"  Logs: /tmp/kbcs_h{{1..8}}.log")

if __name__ == "__main__":
    main()
