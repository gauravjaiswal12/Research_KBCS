#!/usr/bin/env python3
"""Quick 5-run KBCS benchmark for demo"""
import subprocess
import json
import os
import sys
import statistics

NUM_RUNS = 5
DURATION = 30
NUM_FLOWS = 4
CCAS = "cubic,reno,illinois,htcp"

print(f"\n{'#'*60}")
print(f"  KBCS QUICK BENCHMARK: {NUM_RUNS} RUNS")
print(f"  Flows: {NUM_FLOWS}, CCAs: {CCAS}")
print(f"{'#'*60}\n")
sys.stdout.flush()

all_jfi = []
all_throughputs = {"h1_CUBIC": [], "h2_RENO": [], "h3_ILLINOIS": [], "h4_HTCP": []}

for run in range(1, NUM_RUNS + 1):
    print(f"\n{'='*50}")
    print(f"  RUN {run}/{NUM_RUNS}")
    print(f"{'='*50}")
    sys.stdout.flush()

    cmd = ["python", "upload_and_run.py", "--traffic", "--duration", str(DURATION),
           "--num-flows", str(NUM_FLOWS), "--ccas", CCAS]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    # Parse results
    if os.path.exists("kbcs/results/last_test.json"):
        with open("kbcs/results/last_test.json", 'r') as f:
            data = json.load(f)
        jfi = data.get('jain_index', 0)
        all_jfi.append(jfi)

        for flow in data.get('flows', []):
            key = f"{flow['name']}_{flow['cca'].upper()}"
            if key in all_throughputs:
                all_throughputs[key].append(flow['mbps'])

        print(f"  JFI = {jfi:.4f}")
        for flow in data.get('flows', []):
            print(f"    {flow['name']} ({flow['cca']}): {flow['mbps']:.2f} Mbps")
    else:
        print(f"  FAILED - no results")
    sys.stdout.flush()

# Final statistics
print(f"\n{'='*60}")
print(f"  BENCHMARK RESULTS ({len(all_jfi)} runs)")
print(f"{'='*60}")

if all_jfi:
    jfi_mean = statistics.mean(all_jfi)
    jfi_std = statistics.stdev(all_jfi) if len(all_jfi) > 1 else 0

    print(f"\n  Jain's Fairness Index:")
    print(f"    Mean:   {jfi_mean:.4f}")
    print(f"    StdDev: {jfi_std:.4f}")
    print(f"    Min:    {min(all_jfi):.4f}")
    print(f"    Max:    {max(all_jfi):.4f}")

    print(f"\n  Per-Flow Throughput (Mbps):")
    for key in sorted(all_throughputs.keys()):
        if all_throughputs[key]:
            mean = statistics.mean(all_throughputs[key])
            std = statistics.stdev(all_throughputs[key]) if len(all_throughputs[key]) > 1 else 0
            print(f"    {key}: {mean:.2f} +/- {std:.2f}")

# Save summary
summary = {
    "num_runs": len(all_jfi),
    "jfi_mean": round(statistics.mean(all_jfi), 4) if all_jfi else 0,
    "jfi_std": round(statistics.stdev(all_jfi), 4) if len(all_jfi) > 1 else 0,
    "jfi_min": round(min(all_jfi), 4) if all_jfi else 0,
    "jfi_max": round(max(all_jfi), 4) if all_jfi else 0,
    "flows": {k: round(statistics.mean(v), 2) for k, v in all_throughputs.items() if v}
}

with open("kbcs/results/benchmark_summary.json", 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\n  Summary saved to kbcs/results/benchmark_summary.json")
print(f"{'='*60}\n")
