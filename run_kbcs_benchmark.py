#!/usr/bin/env python3
"""
KBCS Benchmark Runner - 30 runs with statistical averaging
Similar to P4AIR baseline benchmark methodology
"""

import subprocess
import json
import os
import sys
import time
import statistics
import csv
from datetime import datetime

def run_single_test(run_num, duration, num_flows, ccas):
    """Run a single traffic test and return results"""
    print(f"\n{'='*60}")
    print(f"  RUN {run_num}/30 - {ccas}")
    print(f"{'='*60}")

    cmd = [
        "python", "upload_and_run.py",
        "--traffic",
        "--duration", str(duration),
        "--num-flows", str(num_flows),
        "--ccas", ccas
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    # Parse results from last_test.json
    results_file = "kbcs/results/last_test.json"
    if os.path.exists(results_file):
        with open(results_file, 'r') as f:
            data = json.load(f)
        return data
    return None

def main():
    # Configuration
    NUM_RUNS = 30
    DURATION = 30
    NUM_FLOWS = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    CCAS = sys.argv[2] if len(sys.argv) > 2 else "cubic,bbr,reno,illinois"

    print(f"\n{'#'*60}")
    print(f"  KBCS BENCHMARK: {NUM_RUNS} RUNS")
    print(f"  Flows: {NUM_FLOWS}, CCAs: {CCAS}, Duration: {DURATION}s each")
    print(f"{'#'*60}")

    # Storage for all results
    all_jfi = []
    all_throughputs = {}  # {flow_name_cca: [mbps values]}
    all_drops = {}
    all_karma_data = []

    # Track per-CCA stats
    cca_list = [c.strip() for c in CCAS.split(',')]
    for i, cca in enumerate(cca_list * (NUM_FLOWS // len(cca_list) + 1)):
        if i >= NUM_FLOWS:
            break
        key = f"h{i+1}_{cca.upper()}"
        all_throughputs[key] = []

    start_time = time.time()

    for run in range(1, NUM_RUNS + 1):
        try:
            result = run_single_test(run, DURATION, NUM_FLOWS, CCAS)

            if result:
                jfi = result.get('jain_index', 0)
                all_jfi.append(jfi)

                for flow in result.get('flows', []):
                    key = f"{flow['name']}_{flow['cca'].upper()}"
                    if key not in all_throughputs:
                        all_throughputs[key] = []
                    all_throughputs[key].append(flow['mbps'])

                print(f"  Run {run}: JFI = {jfi:.4f}")
            else:
                print(f"  Run {run}: FAILED - no results")

        except Exception as e:
            print(f"  Run {run}: ERROR - {e}")

        # Brief pause between runs
        time.sleep(5)

    elapsed = time.time() - start_time

    # Calculate statistics
    print(f"\n{'='*60}")
    print(f"  BENCHMARK RESULTS ({NUM_RUNS} runs)")
    print(f"{'='*60}")

    if all_jfi:
        jfi_mean = statistics.mean(all_jfi)
        jfi_std = statistics.stdev(all_jfi) if len(all_jfi) > 1 else 0
        jfi_min = min(all_jfi)
        jfi_max = max(all_jfi)

        print(f"\n  Jain's Fairness Index:")
        print(f"    Mean:   {jfi_mean:.4f}")
        print(f"    StdDev: {jfi_std:.4f}")
        print(f"    Min:    {jfi_min:.4f}")
        print(f"    Max:    {jfi_max:.4f}")
        print(f"    95% CI: [{jfi_mean - 1.96*jfi_std/len(all_jfi)**0.5:.4f}, {jfi_mean + 1.96*jfi_std/len(all_jfi)**0.5:.4f}]")

    print(f"\n  Per-Flow Throughput (Mbps):")
    total_throughputs = []
    for key in sorted(all_throughputs.keys()):
        values = all_throughputs[key]
        if values:
            mean = statistics.mean(values)
            std = statistics.stdev(values) if len(values) > 1 else 0
            total_throughputs.extend(values)
            print(f"    {key}: {mean:.2f} +/- {std:.2f}")

    if total_throughputs:
        total_mean = statistics.mean(total_throughputs)
        print(f"\n  Total Throughput: {sum([statistics.mean(v) for v in all_throughputs.values() if v]):.2f} Mbps")

    print(f"\n  Benchmark completed in {elapsed/60:.1f} minutes")

    # Save results to CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = "kbcs/results"
    os.makedirs(results_dir, exist_ok=True)

    # Summary CSV
    summary_file = f"{results_dir}/benchmark_{NUM_FLOWS}flows_{timestamp}.csv"
    with open(summary_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['run', 'jfi'] + list(sorted(all_throughputs.keys())))
        for i, jfi in enumerate(all_jfi):
            row = [i+1, jfi]
            for key in sorted(all_throughputs.keys()):
                row.append(all_throughputs[key][i] if i < len(all_throughputs[key]) else '')
            writer.writerow(row)

        # Statistics row
        writer.writerow([])
        writer.writerow(['MEAN', statistics.mean(all_jfi) if all_jfi else 0] +
                       [statistics.mean(all_throughputs[k]) if all_throughputs[k] else 0
                        for k in sorted(all_throughputs.keys())])
        writer.writerow(['STDEV', statistics.stdev(all_jfi) if len(all_jfi) > 1 else 0] +
                       [statistics.stdev(all_throughputs[k]) if len(all_throughputs[k]) > 1 else 0
                        for k in sorted(all_throughputs.keys())])

    print(f"\n  Results saved to: {summary_file}")

    # Save summary JSON for Grafana
    summary_json = {
        'timestamp': timestamp,
        'num_runs': len(all_jfi),
        'num_flows': NUM_FLOWS,
        'ccas': CCAS,
        'jfi_mean': round(statistics.mean(all_jfi), 4) if all_jfi else 0,
        'jfi_std': round(statistics.stdev(all_jfi), 4) if len(all_jfi) > 1 else 0,
        'flows': {}
    }

    for key in sorted(all_throughputs.keys()):
        if all_throughputs[key]:
            summary_json['flows'][key] = {
                'mean_mbps': round(statistics.mean(all_throughputs[key]), 2),
                'std_mbps': round(statistics.stdev(all_throughputs[key]), 2) if len(all_throughputs[key]) > 1 else 0
            }

    with open(f"{results_dir}/benchmark_summary.json", 'w') as f:
        json.dump(summary_json, f, indent=2)

    print(f"  Summary JSON saved to: {results_dir}/benchmark_summary.json")

    return 0 if all_jfi and statistics.mean(all_jfi) >= 0.90 else 1

if __name__ == "__main__":
    sys.exit(main())
