#!/usr/bin/env python3
"""
run_comparison.py — Run All P4air Baseline Comparisons
=======================================================
Automates running traffic experiments across all 4 configurations:
  1. No AQM (simple forwarding, FIFO)
  2. Different Queues (hash-based 5-tuple queue assignment)
  3. Idle P4air (Fingerprinting + Reallocation only, no Apply Actions)
  4. P4air (full: Fingerprinting + Reallocation + Apply Actions)

Each configuration is compiled, run through Mininet with the same CCA mix,
and results are saved for comparison.

Usage (run inside the P4 VM):
    sudo python3 experiments/run_comparison.py --duration 30 --num-clients 4
    sudo python3 experiments/run_comparison.py --duration 60 --num-clients 8 --ccas cubic,bbr,vegas,illinois,cubic,bbr,vegas,illinois

Note: This script must be run from the Baseline/p4air/ directory.
"""

import subprocess
import os
import sys
import json
import time
import argparse


# --------------------------------------------------------------------------
# Configuration: paths to P4 JSON for each variant
# These will be compiled before running experiments
# --------------------------------------------------------------------------
CONFIGS = {
    'no_aqm': {
        'p4_source': 'p4src/no_aqm.p4',
        'json_path': 'build/no_aqm.json',
        'description': 'No AQM (simple forwarding, single FIFO queue)',
        'priority_queues': 0
    },
    'diff_queues': {
        'p4_source': 'p4src/diff_queues.p4',
        'json_path': 'build/diff_queues.json',
        'description': 'Different Queues (hash-based static queue assignment)',
        'priority_queues': 8
    },
    'p4air': {
        'p4_source': 'p4src/p4air.p4',
        'json_path': 'build/p4air.json',
        'description': 'P4air (Full: Fingerprinting + Reallocation + Apply Actions)',
        'priority_queues': 8
    },
}


def compile_p4(p4_source, json_output):
    """Compile a P4 program to BMv2 JSON using p4c-bm2-ss.

    Args:
        p4_source:   path to .p4 source file
        json_output: path to output .json file

    Returns:
        True if compilation succeeded, False otherwise
    """
    os.makedirs(os.path.dirname(json_output), exist_ok=True)
    cmd = [
        'p4c-bm2-ss', '--p4v', '16',
        '-o', json_output,
        p4_source
    ]
    print("  Compiling: %s" % ' '.join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("  ERROR: Compilation failed!")
        print("  STDERR: %s" % result.stderr)
        return False
    print("  OK: %s → %s" % (p4_source, json_output))
    return True


def run_experiment(config_name, config, num_clients, ccas, duration, bw, delay):
    """Run a single traffic experiment with a given P4 configuration.

    Launches Mininet with the specified P4 JSON, runs iperf3 traffic,
    and saves results.

    Args:
        config_name: short name for this configuration (e.g., 'p4air')
        config:      dict with 'json_path', 'priority_queues', 'description'
        num_clients: number of client hosts
        ccas:        comma-separated CCA list
        duration:    test duration in seconds
        bw:          bottleneck bandwidth in Mbps
        delay:       bottleneck link delay (e.g., '5ms')

    Returns:
        path to saved result file, or None on failure
    """
    print("\n" + "=" * 60)
    print("  Running: %s" % config['description'])
    print("  Config:  %d clients, CCAs=%s, %ds" % (num_clients, ccas, duration))
    print("=" * 60)

    # Clean up any leftover Mininet/switch state from previous experiments
    print("  Cleaning up previous Mininet state...")
    subprocess.run(['sudo', 'mn', '-c'], capture_output=True, timeout=15)
    subprocess.run(['sudo', 'killall', '-9', 'simple_switch'], capture_output=True)
    time.sleep(3)

    cmd = [
        'sudo', 'python3', 'topology.py',
        '--behavioral-exe', 'simple_switch',
        '--json', config['json_path'],
        '--traffic',
        '--duration', str(duration),
        '--num-clients', str(num_clients),
        '--ccas', ccas,
        '--bw', str(bw),
        '--delay', delay,
        '--priority-queues', str(config['priority_queues'])
    ]

    print("  Command: %s" % ' '.join(cmd))

    # Set PYTHONPATH for p4_mininet import
    env = os.environ.copy()
    env['PYTHONPATH'] = env.get('PYTHONPATH', '') + ':' + os.path.join(os.getcwd(), 'utils')

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)

    # Print output for debugging
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print("  ERROR: Experiment failed!")
        if result.stderr:
            print("  STDERR: %s" % result.stderr[:500])
        return None

    # Copy results to a named file
    src_result = 'results/last_test.json'
    dst_result = 'results/%s_results.json' % config_name
    if os.path.exists(src_result):
        with open(src_result, 'r') as f:
            data = json.load(f)
        data['config_name'] = config_name
        data['description'] = config['description']
        with open(dst_result, 'w') as f:
            json.dump(data, f, indent=2)
        print("  Results saved: %s" % dst_result)
        return dst_result
    else:
        print("  WARNING: No results file generated")
        return None


def print_comparison_table(result_files):
    """Print a side-by-side comparison table of all experiment results.

    Args:
        result_files: list of (config_name, filepath) tuples
    """
    print("\n" + "=" * 70)
    print("  COMPARISON TABLE: P4air vs Baselines")
    print("=" * 70)
    print("  %-20s %12s %12s %8s" % ("Configuration", "Jain's FI", "Total Mbps", "Flows"))
    print("  " + "-" * 56)

    for name, fpath in result_files:
        try:
            with open(fpath, 'r') as f:
                data = json.load(f)
            print("  %-20s %12.4f %12.2f %8d" % (
                name, data['jain_index'], data['total_mbps'], data['num_clients']))
        except Exception as e:
            print("  %-20s ERROR: %s" % (name, str(e)))

    print("=" * 70)


def main():
    """Main entry point: compile all configs, run experiments, compare results."""
    parser = argparse.ArgumentParser(description='P4air Comparison Experiments')
    parser.add_argument('--num-clients', type=int, default=4,
                        help='Number of client hosts (default: 4)')
    parser.add_argument('--ccas', type=str, default='cubic,bbr,vegas,illinois',
                        help='Comma-separated CCA list (default: cubic,bbr,vegas,illinois)')
    parser.add_argument('--duration', type=int, default=30,
                        help='Test duration in seconds (default: 30)')
    parser.add_argument('--bw', type=int, default=10,
                        help='Bottleneck bandwidth in Mbps (default: 10)')
    parser.add_argument('--delay', type=str, default='5ms',
                        help='Bottleneck link delay (default: 5ms)')
    parser.add_argument('--configs', nargs='+', default=None,
                        help='Specific configs to run (default: all)')
    args = parser.parse_args()

    os.makedirs('results', exist_ok=True)

    # Select which configs to run
    if args.configs:
        configs_to_run = {k: v for k, v in CONFIGS.items() if k in args.configs}
    else:
        configs_to_run = CONFIGS

    # Step 1: Compile all P4 programs
    print("\n*** STEP 1: Compiling P4 programs ***\n")
    for name, config in configs_to_run.items():
        if not compile_p4(config['p4_source'], config['json_path']):
            print("FATAL: Could not compile %s. Aborting." % name)
            sys.exit(1)

    # Step 2: Run experiments
    print("\n*** STEP 2: Running experiments ***")
    result_files = []
    for name, config in configs_to_run.items():
        fpath = run_experiment(name, config, args.num_clients, args.ccas,
                               args.duration, args.bw, args.delay)
        if fpath:
            result_files.append((name, fpath))
        # Brief pause between experiments for cleanup
        time.sleep(3)

    # Step 3: Compare results
    if len(result_files) > 1:
        print("\n*** STEP 3: Comparing results ***")
        print_comparison_table(result_files)
    elif len(result_files) == 1:
        print("\n*** Only one configuration tested — no comparison possible ***")
        print("    Add more baselines in Phase 6 for full comparison.")

    print("\n*** ALL EXPERIMENTS COMPLETE ***\n")


if __name__ == '__main__':
    main()
