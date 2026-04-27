#!/usr/bin/env python3
"""
KBCS v2 — Per-Run Metrics Collector
=====================================
Called by test_suite.sh after each run to read all P4 registers
and append one CSV row with the computed metrics.

Usage:
  python3 collect_metrics.py --run 1 --topo cross --duration 60 --csv results/cross_results.csv --thrift-port 9090
"""

import argparse
import subprocess
import csv
import os


def read_register(thrift_port, register_name, index):
    """Read a single register value from a BMv2 switch."""
    try:
        cmd = f"echo 'register_read {register_name} {index}' | simple_switch_CLI --thrift-port {thrift_port} 2>/dev/null"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)
        for line in result.stdout.split('\n'):
            if '=' in line and register_name.split('.')[-1] in line:
                val_str = line.split('=')[-1].strip()
                return int(val_str)
    except Exception:
        pass
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=int, required=True)
    parser.add_argument('--topo', type=str, required=True)
    parser.add_argument('--duration', type=int, required=True)
    parser.add_argument('--csv', type=str, required=True)
    parser.add_argument('--thrift-port', type=int, default=9090)
    args = parser.parse_args()

    port = args.thrift_port

    # Read per-flow metrics from S1 (all flows transit S1 in both topologies)
    karma = []
    fwd = []
    drops = []
    for fid in range(1, 5):
        karma.append(read_register(port, "MyIngress.reg_karma", fid))
        fwd.append(read_register(port, "MyIngress.reg_forwarded_bytes", fid))
        drops.append(read_register(port, "MyEgress.reg_drops", fid))

    # ── Compute metrics ──────────────────────────────────────────────────────

    # Jain's Fairness Index (from forwarded bytes = proxy for throughput)
    n = len(fwd)
    sum_x = sum(fwd)
    sum_x2 = sum(x * x for x in fwd)
    if sum_x2 > 0 and sum_x > 0:
        jfi = (sum_x ** 2) / (n * sum_x2)
    else:
        jfi = 0.0

    # Aggregate throughput (Mbps)
    agg_throughput_mbps = (sum_x * 8) / (args.duration * 1_000_000) if args.duration > 0 else 0.0

    # Link utilization (bottleneck = 3 Mbps)
    link_util_pct = min((agg_throughput_mbps / 3.0) * 100.0, 100.0)

    # Packet Drop Ratio
    total_drops = sum(drops)
    total_drop_bytes = total_drops * 1500
    total_bytes = sum_x + total_drop_bytes
    pdr_pct = (total_drop_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0

    # Average karma
    avg_karma = sum(karma) / len(karma) if karma else 0.0

    # ── Append to CSV ────────────────────────────────────────────────────────
    row = {
        'run': args.run,
        'topology': args.topo,
        'duration': args.duration,
        'jfi': round(jfi, 4),
        'agg_throughput_mbps': round(agg_throughput_mbps, 4),
        'link_util_pct': round(link_util_pct, 2),
        'pdr_pct': round(pdr_pct, 4),
        'avg_karma': round(avg_karma, 2),
        'karma_1': karma[0], 'karma_2': karma[1], 'karma_3': karma[2], 'karma_4': karma[3],
        'fwd_1': fwd[0], 'fwd_2': fwd[1], 'fwd_3': fwd[2], 'fwd_4': fwd[3],
        'drops_1': drops[0], 'drops_2': drops[1], 'drops_3': drops[2], 'drops_4': drops[3],
    }

    fieldnames = list(row.keys())
    file_exists = os.path.exists(args.csv)

    with open(args.csv, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    # Print summary
    print(f"    Run {args.run}: JFI={jfi:.4f}  Throughput={agg_throughput_mbps:.2f} Mbps  "
          f"LinkUtil={link_util_pct:.1f}%  PDR={pdr_pct:.2f}%  "
          f"AvgKarma={avg_karma:.0f}  Karma=[{karma[0]},{karma[1]},{karma[2]},{karma[3]}]")


if __name__ == '__main__':
    main()
