#!/usr/bin/env python3
"""
KBCS Experiment Runner
Runs baseline (no KBCS) and KBCS-enabled experiments sequentially,
collects results, and computes Jain's Fairness Index.

Usage (on the VM):
    sudo python3 run_experiment.py
"""

import subprocess
import json
import os
import sys
import time

RESULTS_DIR = 'results'
DURATION = 30  # seconds per test
PYTHONPATH_PREFIX = 'PYTHONPATH=$PYTHONPATH:{}/utils'.format(os.getcwd())

def run_cmd(cmd, timeout=None):
    """Run a shell command and return output."""
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        # Filter out non-critical stderr
        for line in result.stderr.strip().split('\n'):
            if 'Warning' not in line and 'quantum' not in line:
                print(f"  stderr: {line}")
    return result


def build(target='build'):
    """Compile the P4 program."""
    print(f"\n{'='*60}")
    print(f"  BUILDING: {target}")
    print(f"{'='*60}")
    result = run_cmd(f'make {target}')
    if result.returncode != 0:
        print(f"BUILD FAILED for {target}")
        sys.exit(1)
    print("  Build successful!")


def run_traffic_test(json_file, label, results_subdir):
    """Run a traffic test and return the results."""
    print(f"\n{'='*60}")
    print(f"  RUNNING: {label}")
    print(f"  Duration: {DURATION}s | JSON: {json_file}")
    print(f"{'='*60}")

    os.makedirs(results_subdir, exist_ok=True)

    # Run topology with traffic flag
    cmd = (f'sudo {PYTHONPATH_PREFIX} python3 topology.py '
           f'--behavioral-exe simple_switch '
           f'--json {json_file} '
           f'--traffic --duration {DURATION}')

    # This will take DURATION + ~10 seconds
    result = run_cmd(cmd, timeout=DURATION + 60)
    return result


def parse_iperf_results(results_subdir):
    """Parse iperf3 JSON results and return throughputs."""
    results = {}
    for fname, label in [('h1_cubic.json', 'CUBIC (h1)'), ('h2_bbr.json', 'BBR (h2)')]:
        fpath = os.path.join(results_subdir, fname)
        try:
            with open(fpath, 'r') as f:
                data = json.load(f)
            bps = data['end']['sum_sent']['bits_per_second']
            mbps = bps / 1e6
            retransmits = data['end']['sum_sent'].get('retransmits', 'N/A')
            results[label] = {'mbps': mbps, 'retransmits': retransmits}
        except FileNotFoundError:
            print(f"  WARNING: {fpath} not found")
            results[label] = {'mbps': 0, 'retransmits': 'N/A'}
        except Exception as e:
            print(f"  WARNING: Could not parse {fpath}: {e}")
            results[label] = {'mbps': 0, 'retransmits': 'N/A'}

    return results


def jain_index(t1, t2):
    """Calculate Jain's Fairness Index for two flows."""
    if t1 == 0 and t2 == 0:
        return 0
    return ((t1 + t2) ** 2) / (2 * (t1**2 + t2**2))


def print_comparison(baseline_results, kbcs_results):
    """Print a formatted comparison of baseline vs KBCS."""
    print(f"\n{'='*60}")
    print(f"  KBCS EXPERIMENT RESULTS")
    print(f"{'='*60}")

    print(f"\n  {'Metric':<25} {'Baseline (No KBCS)':<20} {'KBCS Enabled':<20}")
    print(f"  {'-'*65}")

    for label in ['CUBIC (h1)', 'BBR (h2)']:
        b_mbps = baseline_results.get(label, {}).get('mbps', 0)
        k_mbps = kbcs_results.get(label, {}).get('mbps', 0)
        b_retx = baseline_results.get(label, {}).get('retransmits', 'N/A')
        k_retx = kbcs_results.get(label, {}).get('retransmits', 'N/A')
        print(f"  {label + ' Throughput':<25} {b_mbps:>8.2f} Mbps      {k_mbps:>8.2f} Mbps")
        print(f"  {label + ' Retransmits':<25} {str(b_retx):>8}           {str(k_retx):>8}")

    b_t1 = baseline_results.get('CUBIC (h1)', {}).get('mbps', 0)
    b_t2 = baseline_results.get('BBR (h2)', {}).get('mbps', 0)
    k_t1 = kbcs_results.get('CUBIC (h1)', {}).get('mbps', 0)
    k_t2 = kbcs_results.get('BBR (h2)', {}).get('mbps', 0)

    b_jain = jain_index(b_t1, b_t2)
    k_jain = jain_index(k_t1, k_t2)

    print(f"\n  {'Jain Fairness Index':<25} {b_jain:>8.4f}             {k_jain:>8.4f}")
    print(f"  (1.0 = perfectly fair, 0.5 = completely unfair)")

    improvement = k_jain - b_jain
    if improvement > 0:
        print(f"\n  ✅ KBCS IMPROVED fairness by {improvement:.4f} ({improvement/b_jain*100:.1f}% relative)")
    elif improvement < 0:
        print(f"\n  ⚠️  KBCS decreased fairness by {abs(improvement):.4f}")
    else:
        print(f"\n  ➖ No change in fairness")

    print(f"\n{'='*60}")

    # Save results to JSON
    summary = {
        'baseline': {
            'cubic_mbps': b_t1, 'bbr_mbps': b_t2,
            'jain_index': b_jain,
            'cubic_retransmits': baseline_results.get('CUBIC (h1)', {}).get('retransmits', 'N/A'),
            'bbr_retransmits': baseline_results.get('BBR (h2)', {}).get('retransmits', 'N/A')
        },
        'kbcs': {
            'cubic_mbps': k_t1, 'bbr_mbps': k_t2,
            'jain_index': k_jain,
            'cubic_retransmits': kbcs_results.get('CUBIC (h1)', {}).get('retransmits', 'N/A'),
            'bbr_retransmits': kbcs_results.get('BBR (h2)', {}).get('retransmits', 'N/A')
        },
        'improvement': improvement,
        'duration_seconds': DURATION
    }

    with open(os.path.join(RESULTS_DIR, 'experiment_summary.json'), 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"  Results saved to {RESULTS_DIR}/experiment_summary.json")


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    print("\n" + "="*60)
    print("  KBCS EXPERIMENT: Baseline vs KBCS-Enabled")
    print("  Test duration: {} seconds per experiment".format(DURATION))
    print("="*60)

    # ---- EXPERIMENT 1: BASELINE (No KBCS) ----
    print("\n\n" + "#"*60)
    print("  EXPERIMENT 1: BASELINE (No Karma, FIFO Scheduling)")
    print("#"*60)

    build('build-baseline')
    baseline_subdir = os.path.join(RESULTS_DIR, 'baseline')
    os.makedirs(baseline_subdir, exist_ok=True)

    # Temporarily change results dir for baseline
    run_traffic_test('build/kbcs_baseline.json', 'Baseline (No KBCS)', baseline_subdir)

    # Copy iperf results from Mininet's working directory
    os.system(f'cp -f results/h1_cubic.json {baseline_subdir}/ 2>/dev/null')
    os.system(f'cp -f results/h2_bbr.json {baseline_subdir}/ 2>/dev/null')
    baseline_results = parse_iperf_results(baseline_subdir)

    # Small delay between experiments
    print("\n  Waiting 5 seconds before next experiment...")
    time.sleep(5)

    # ---- EXPERIMENT 2: KBCS ENABLED ----
    print("\n\n" + "#"*60)
    print("  EXPERIMENT 2: KBCS ENABLED (Karma + Priority Queues)")
    print("#"*60)

    build('build')
    kbcs_subdir = os.path.join(RESULTS_DIR, 'kbcs')
    os.makedirs(kbcs_subdir, exist_ok=True)

    run_traffic_test('build/kbcs.json', 'KBCS Enabled', kbcs_subdir)

    os.system(f'cp -f results/h1_cubic.json {kbcs_subdir}/ 2>/dev/null')
    os.system(f'cp -f results/h2_bbr.json {kbcs_subdir}/ 2>/dev/null')
    kbcs_results = parse_iperf_results(kbcs_subdir)

    # ---- COMPARISON ----
    print_comparison(baseline_results, kbcs_results)


if __name__ == '__main__':
    main()
