#!/usr/bin/env python3
"""
run_multiple.py — Automate Multiple P4air Experiment Runs and Plot Graphs
========================================================================
Because emulated networking in Mininet/BMv2 suffers from CPU jitter and 
hash collisions, a single 30-second run is often not representative.
This script automates running the experiment N times, collects all results,
calculates the average (mean) and standard deviation, and outputs a 
bar chart graph.

Usage:
    sudo python3 experiments/run_multiple.py --runs 5 --duration 30
"""

import subprocess
import os
import json
import argparse
import statistics
import time

try:
    import matplotlib.pyplot as plt
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    print("Warning: matplotlib or numpy not installed. Graphs will not be generated.")
    MATPLOTLIB_AVAILABLE = False


def main():
    parser = argparse.ArgumentParser(description='Run P4air baseline comparison multiple times.')
    parser.add_argument('--runs', type=int, default=5, help='Number of experiment iterations to run')
    parser.add_argument('--duration', type=int, default=30, help='Duration of each traffic test (seconds)')
    parser.add_argument('--num-clients', type=int, default=4, help='Number of Mininet hosts')
    args = parser.parse_args()

    configs = ['no_aqm', 'diff_queues', 'p4air']
    
    # Data storage structure
    # all_data['no_aqm']['jfi'] = [run1_jfi, run2_jfi, ...]
    all_data = {
        c: {
            'jfi': [], 
            'total_mbps': [],
            'config_name': c
        } for c in configs
    }

    os.makedirs('results', exist_ok=True)

    print("\n" + "=" * 70)
    print(f"  STARTING MULTIPLE EXPERIMENT RUNS: {args.runs} iterations")
    print(f"  Duration: {args.duration}s per test | Total Est. Time: {args.runs * 3 * (args.duration + 10) / 60:.1f} mins")
    print("=" * 70)

    for run in range(1, args.runs + 1):
        print(f"\n+++ ITERATION {run} of {args.runs} +++")
        
        # Build command for run_comparison.py
        cmd = [
            'sudo', 'PYTHONPATH=utils', 'python3', 'experiments/run_comparison.py',
            '--duration', str(args.duration),
            '--num-clients', str(args.num_clients),
            '--ccas', 'cubic,bbr,vegas,illinois'
        ]
        
        # Execute the full comparison (which internally cleans up Mininet)
        result = subprocess.run(' '.join(cmd), shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  Warning: Iteration {run} had errors (run_comparison.py failed). Skipping this run's data.")
            print(result.stderr[:500])
            continue
            
        # Extract data from the resulting JSON files for this run
        for c in configs:
            fpath = f'results/{c}_results.json'
            if os.path.exists(fpath):
                try:
                    with open(fpath, 'r') as f:
                        data = json.load(f)
                        all_data[c]['jfi'].append(data.get('jain_index', 0.0))
                        all_data[c]['total_mbps'].append(data.get('total_mbps', 0.0))
                except Exception as e:
                    print(f"  Error reading {c} results for run {run}: {e}")
            else:
                print(f"  Warning: Results for {c} not found in run {run}.")
    
    # Save the raw aggregated data
    with open('results/multiple_runs_data.json', 'w') as f:
        json.dump(all_data, f, indent=2)

    # -------------------------------------------------------------
    # Summary Table
    # -------------------------------------------------------------
    print("\n" + "=" * 70)
    print(f"  FINAL AVERAGES ACROSS {args.runs} RUNS")
    print("=" * 70)
    print(f"  {'Configuration':<20} | {'Avg JFI':<15} | {'Avg Total Mbps':<15}")
    print("  " + "-" * 55)

    plot_data = []

    for c in configs:
        jfi_list = all_data[c]['jfi']
        mbps_list = all_data[c]['total_mbps']
        
        # Only compute mean/stdev if we have data
        if not jfi_list or not mbps_list:
            print(f"  {c:<20} | {'No Data':<15} | {'No Data':<15}")
            continue
            
        avg_jfi = statistics.mean(jfi_list)
        std_jfi = statistics.stdev(jfi_list) if len(jfi_list) > 1 else 0.0
        
        avg_mbps = statistics.mean(mbps_list)
        std_mbps = statistics.stdev(mbps_list) if len(mbps_list) > 1 else 0.0
        
        desc = c
        if c == 'no_aqm': desc = 'No AQM (FIFO)'
        if c == 'diff_queues': desc = 'Diff Queues (Hash)'
        if c == 'p4air': desc = 'P4air (CCA Aware)'
        
        print(f"  {desc:<20} | {avg_jfi:.4f} (±{std_jfi:.2f}) | {avg_mbps:6.2f} (±{std_mbps:.2f})")
        
        plot_data.append({
            'name': desc,
            'avg_jfi': avg_jfi, 'std_jfi': std_jfi,
            'avg_mbps': avg_mbps, 'std_mbps': std_mbps
        })

    print("=" * 70)

    # -------------------------------------------------------------
    # Plot Graph
    # -------------------------------------------------------------
    if MATPLOTLIB_AVAILABLE and plot_data:
        print("\n  Generating comparison graph...")
        labels = [d['name'] for d in plot_data]
        jfi_means = [d['avg_jfi'] for d in plot_data]
        jfi_stds = [d['std_jfi'] for d in plot_data]
        mbps_means = [d['avg_mbps'] for d in plot_data]
        mbps_stds = [d['std_mbps'] for d in plot_data]

        x = np.arange(len(labels))
        width = 0.35

        fig, ax1 = plt.subplots(figsize=(9, 6))

        # Bar chart for JFI
        color = 'tab:blue'
        ax1.set_xlabel('Queue Configuration')
        ax1.set_ylabel("Average Jain's Fairness Index", color=color, fontweight='bold')
        ax1.bar(x - width/2, jfi_means, width, yerr=jfi_stds, capsize=5, 
                color=color, alpha=0.7, label="Jain's FI (Higher is Fairer)")
        ax1.tick_params(axis='y', labelcolor=color)
        ax1.set_ylim(0, 1.1)

        # Bar chart for Total Throughput on secondary Y axis
        ax2 = ax1.twinx()
        color = 'tab:green'
        ax2.set_ylabel('Average Total Throughput (Mbps)', color=color, fontweight='bold')
        ax2.bar(x + width/2, mbps_means, width, yerr=mbps_stds, capsize=5, 
                color=color, alpha=0.7, label='Total Throughput')
        ax2.tick_params(axis='y', labelcolor=color)
        
        # 10 Mbps bottleneck link is the theoretical max, but give it 12 limit for padding
        ax2.set_ylim(0, 12) 

        # Add legends
        fig.legend(loc="upper right", bbox_to_anchor=(0.95, 0.95))

        ax1.set_xticks(x)
        ax1.set_xticklabels(labels)
        plt.title(f'P4air vs Baselines: Average Performance over {args.runs} runs\n(Error bars indicate standard deviation due to hash collisions & VM jitter)')
        
        fig.tight_layout()
        plot_path = 'results/comparison_graph.png'
        plt.savefig(plot_path, dpi=150)
        print(f"  Graph saved successfully to: {plot_path}")
        print("=" * 70)


if __name__ == '__main__':
    main()
