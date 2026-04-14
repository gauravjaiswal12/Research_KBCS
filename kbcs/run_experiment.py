#!/usr/bin/env python3
"""
run_experiment.py — KBCS Full Experiment Runner
================================================
Runs three sequential experiments:

  1. Baseline (no KBCS, FIFO)            — dumbbell topology
  2. KBCS Enhanced                        — dumbbell topology
  3. KBCS Enhanced + Parking Lot         — parking lot topology

Each experiment collects per-flow throughput, retransmits, and
saves results to results/experiment_summary.json.

Usage (on the Ubuntu VM):
    sudo python3 run_experiment.py [--duration SECS] [--controller]
"""

import subprocess
import json
import os
import sys
import time
import argparse

RESULTS_DIR = 'results'
PYTHONPATH_PREFIX = f'PYTHONPATH=$PYTHONPATH:{os.getcwd()}/utils'


# ================================================================== #
# Utilities                                                            #
# ================================================================== #
def run_cmd(cmd, timeout=None):
    """Run a shell command and stream its output."""
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True,
                            text=True, timeout=timeout)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        for line in result.stderr.strip().split('\n'):
            if 'Warning' not in line and 'quantum' not in line:
                print(f"  stderr: {line}")
    return result


def build(target='build'):
    """Compile the P4 program via Makefile."""
    print(f"\n{'='*60}")
    print(f"  BUILDING: {target}")
    print(f"{'='*60}")
    result = run_cmd(f'make {target}')
    if result.returncode != 0:
        print(f"BUILD FAILED for target '{target}'")
        sys.exit(1)
    print("  Build OK.")


def jain_index(values: list) -> float:
    """Jain's Fairness Index for any number of flows."""
    n = len(values)
    if n == 0 or all(v == 0 for v in values):
        return 0.0
    s  = sum(values)
    s2 = sum(v**2 for v in values)
    return (s ** 2) / (n * s2)


# ================================================================== #
# Experiment harness                                                    #
# ================================================================== #
def run_topology_test(json_file: str, topo_script: str, label: str,
                      duration: int, results_subdir: str,
                      priority_queues: int = 4,
                      controller: bool = False) -> dict:
    """
    Launch a Mininet topology and collect iperf3 results.
    Returns the parsed summary dict.
    """
    print(f"\n{'='*60}")
    print(f"  EXPERIMENT: {label}")
    print(f"  Topo: {topo_script} | JSON: {json_file} | Duration: {duration}s")
    print(f"{'='*60}")
    os.makedirs(results_subdir, exist_ok=True)

    ctrl_flag = '--controller' if controller else ''
    pq_flag   = f'--priority-queues {priority_queues}'
    # Added /home/p4/src/mininet to python path so it finds mininet on P4 VMs
    cmd = (f'sudo -E PYTHONPATH={os.getenv("PYTHONPATH","")}:{os.getcwd()}/utils:/home/p4/src/mininet python3 {topo_script} '
           f'--behavioral-exe simple_switch '
           f'--json {json_file} '
           f'--traffic --duration {duration} '
           f'{pq_flag} {ctrl_flag}')

    run_cmd(cmd, timeout=duration + 90)

    # Copy result files to the sub-folder
    for fname in ('last_test.json', 'parking_lot_test.json'):
        src = os.path.join('results', fname)
        if os.path.exists(src):
            run_cmd(f'cp -f {src} {results_subdir}/')

    # Read and return the summary that the topology script saved
    for fname in ('last_test.json', 'parking_lot_test.json'):
        summary_path = os.path.join(results_subdir, fname)
        if os.path.exists(summary_path):
            with open(summary_path) as f:
                return json.load(f)

    return {}


# ================================================================== #
# Comparison output                                                     #
# ================================================================== #
def print_comparison(experiments: dict):
    """Pretty-print the side-by-side comparison of all experiments."""
    print(f"\n{'='*70}")
    print(f"  FINAL COMPARISON: Baseline vs KBCS (Dumbbell & Parking Lot)")
    print(f"{'='*70}")

    for exp_name, data in experiments.items():
        flows  = data.get('flows', {})
        jain   = data.get('jain_index', 0)
        total  = data.get('total_mbps', 0)
        topo   = data.get('topology', '')
        print(f"\n  ── {exp_name} ({'topology: ' + topo}) ──")
        print(f"  {'Flow':<22} {'Mbps':>8}  {'Retxmits':>10}")
        print(f"  {'-'*42}")
        for hname, info in flows.items():
            lbl  = info.get('label', info.get('cca', hname))
            mbps = info.get('mbps', 0)
            retx = info.get('retransmits', 'N/A')
            print(f"  {lbl:<22} {mbps:>8.2f}  {str(retx):>10}")
        print(f"  {'─'*42}")
        print(f"  {'Total throughput':<22} {total:>8.2f} Mbps")
        jain_lbl = "Jain's FI"
        print(f"  {jain_lbl:<22} {jain:>8.4f}")

    print(f"\n{'='*70}")


# ================================================================== #
# Main                                                                  #
# ================================================================== #
def main():
    parser = argparse.ArgumentParser(
        description='KBCS Full Experiment Runner')
    parser.add_argument('--duration', type=int, default=30,
                        help='Duration per experiment in seconds (default: 30)')
    parser.add_argument('--priority-queues', type=int, default=4,
                        help='BMv2 priority queues (default: 4)')
    parser.add_argument('--controller', action='store_true',
                        help='Enable adaptive controller in KBCS runs')
    parser.add_argument('--skip-baseline', action='store_true',
                        help='Skip the baseline experiment')
    parser.add_argument('--skip-parking', action='store_true',
                        help='Skip the parking lot experiment')
    args = parser.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)
    duration = args.duration
    pq       = args.priority_queues

    experiments = {}

    # ---- EXPERIMENT 1: BASELINE (no KBCS) ----
    if not args.skip_baseline:
        print("\n" + "#"*60)
        print("  EXPERIMENT 1: BASELINE — FIFO, No Karma")
        print("#"*60)
        build('build-baseline')
        sub = os.path.join(RESULTS_DIR, 'baseline_dumbbell')
        experiments['Baseline (FIFO)'] = run_topology_test(
            json_file='build/kbcs_baseline.json',
            topo_script='topology.py',
            label='Baseline FIFO Dumbbell',
            duration=duration,
            results_subdir=sub,
            priority_queues=0,          # FIFO — no prio queues
            controller=False
        )
        print("\n  Waiting 5s before next experiment...")
        time.sleep(5)

    # ---- EXPERIMENT 2: KBCS DUMBBELL ----
    print("\n" + "#"*60)
    print("  EXPERIMENT 2: KBCS ENHANCED — 4-Switch Dumbbell")
    print("#"*60)
    build('build')
    sub = os.path.join(RESULTS_DIR, 'kbcs_dumbbell')
    experiments['KBCS (Dumbbell)'] = run_topology_test(
        json_file='build/kbcs.json',
        topo_script='topology.py',
        label='KBCS Enhanced Dumbbell',
        duration=duration,
        results_subdir=sub,
        priority_queues=pq,
        controller=args.controller
    )

    print("\n  Waiting 5s before next experiment...")
    time.sleep(5)

    # ---- EXPERIMENT 3: KBCS PARKING LOT ----
    if not args.skip_parking:
        print("\n" + "#"*60)
        print("  EXPERIMENT 3: KBCS ENHANCED — 4-Switch Parking Lot")
        print("#"*60)
        sub = os.path.join(RESULTS_DIR, 'kbcs_parking_lot')
        experiments['KBCS (Parking Lot)'] = run_topology_test(
            json_file='build/kbcs.json',
            topo_script='parking_lot_topo.py',
            label='KBCS Enhanced Parking Lot',
            duration=duration,
            results_subdir=sub,
            priority_queues=pq,
            controller=args.controller
        )

    # ---- FINAL COMPARISON ----
    print_comparison(experiments)

    # Save comparison to JSON
    out_path = os.path.join(RESULTS_DIR, 'experiment_summary.json')
    with open(out_path, 'w') as f:
        json.dump({'experiments': experiments, 'duration': duration}, f, indent=2)
    print(f"\n  Full results saved → {out_path}")


if __name__ == '__main__':
    main()
