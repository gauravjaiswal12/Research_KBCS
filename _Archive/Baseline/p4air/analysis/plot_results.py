#!/usr/bin/env python3
"""
plot_results.py — Generate Charts from P4air Experiment Results
================================================================
Creates matplotlib charts comparing fairness, throughput, and utilization
across different P4air configurations, reproducing key figures from the paper.

Charts generated:
  1. Bar chart: Jain's Fairness Index comparison
  2. Bar chart: Per-flow throughput comparison
  3. Stacked chart: Utilization comparison

Usage (from Baseline/p4air/ directory):
    python3 analysis/plot_results.py
    python3 analysis/plot_results.py --results-dir results/ --output-dir results/plots/
"""

import json
import os
import sys
import argparse
import glob

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend (works without display)
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("WARNING: matplotlib not installed. Install with: pip3 install matplotlib")
    print("         Charts will not be generated, but data will still be printed.")


def load_results(results_dir):
    """Load all experiment result JSON files from a directory.

    Args:
        results_dir: path to directory containing *_results.json files

    Returns:
        dict mapping config_name → result data
    """
    results = {}
    pattern = os.path.join(results_dir, '*_results.json')
    for fpath in sorted(glob.glob(pattern)):
        try:
            with open(fpath, 'r') as f:
                data = json.load(f)
            name = data.get('config_name', os.path.basename(fpath).replace('_results.json', ''))
            results[name] = data
            print("  Loaded: %s (Jain=%.4f, %d flows)" %
                  (name, data['jain_index'], data['num_clients']))
        except Exception as e:
            print("  WARNING: Could not load %s: %s" % (fpath, str(e)))
    return results


def plot_fairness_comparison(results, output_dir):
    """Generate bar chart comparing Jain's Fairness Index across configs.

    Reproduces the style of Paper Figure 7f — fairness vs configuration.

    Args:
        results:    dict of config_name → result data
        output_dir: directory to save the chart
    """
    if not HAS_MATPLOTLIB:
        return

    names = list(results.keys())
    jain_values = [results[n]['jain_index'] for n in names]

    # Color scheme: P4air=green, baselines=grey/orange
    colors = []
    for name in names:
        if name == 'p4air':
            colors.append('#4CAF50')      # Green for P4air
        elif name == 'idle_p4air':
            colors.append('#8BC34A')      # Light green for Idle P4air
        elif name == 'diff_queues':
            colors.append('#FF9800')      # Orange for Different Queues
        else:
            colors.append('#9E9E9E')      # Grey for No AQM

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(names, jain_values, color=colors, edgecolor='black', linewidth=0.5)

    # Add value labels on bars
    for bar, val in zip(bars, jain_values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                '%.4f' % val, ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax.set_ylabel("Jain's Fairness Index", fontsize=12)
    ax.set_title("P4air: Fairness Comparison", fontsize=14, fontweight='bold')
    ax.set_ylim(0, 1.1)
    ax.axhline(y=1.0, color='green', linestyle='--', alpha=0.3, label='Perfect fairness')
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    os.makedirs(output_dir, exist_ok=True)
    fpath = os.path.join(output_dir, 'fairness_comparison.png')
    plt.savefig(fpath, dpi=150)
    plt.close()
    print("  Saved: %s" % fpath)


def plot_throughput_per_flow(results, output_dir):
    """Generate grouped bar chart showing throughput per flow for each config.

    Reproduces the style of Paper Figure 7j — throughput distribution.

    Args:
        results:    dict of config_name → result data
        output_dir: directory to save the chart
    """
    if not HAS_MATPLOTLIB:
        return

    configs = list(results.keys())
    if not configs:
        return

    # Get number of flows from first config
    n_flows = results[configs[0]]['num_clients']

    fig, ax = plt.subplots(figsize=(10, 5))

    bar_width = 0.8 / len(configs)
    flow_labels = ['Flow %d' % (i + 1) for i in range(n_flows)]

    for idx, config in enumerate(configs):
        throughputs = results[config].get('throughputs', [0] * n_flows)
        positions = [i + idx * bar_width for i in range(n_flows)]
        ax.bar(positions, throughputs, bar_width, label=config, alpha=0.85)

    # Add ideal throughput line
    total_bw = 10  # Bottleneck bandwidth in Mbps
    ideal = total_bw / n_flows
    ax.axhline(y=ideal, color='red', linestyle='--', alpha=0.5,
               label='Ideal (%.1f Mbps)' % ideal)

    ax.set_xlabel('Flow', fontsize=12)
    ax.set_ylabel('Throughput (Mbps)', fontsize=12)
    ax.set_title('P4air: Per-Flow Throughput Distribution', fontsize=14, fontweight='bold')
    ax.set_xticks([i + bar_width * (len(configs) - 1) / 2 for i in range(n_flows)])
    ax.set_xticklabels(flow_labels)
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    os.makedirs(output_dir, exist_ok=True)
    fpath = os.path.join(output_dir, 'throughput_per_flow.png')
    plt.savefig(fpath, dpi=150)
    plt.close()
    print("  Saved: %s" % fpath)


def plot_utilization(results, output_dir, bottleneck_bw=10):
    """Generate bar chart showing link utilization for each config.

    Utilization = total throughput / bottleneck bandwidth × 100%

    Args:
        results:       dict of config_name → result data
        output_dir:    directory to save the chart
        bottleneck_bw: bottleneck bandwidth in Mbps
    """
    if not HAS_MATPLOTLIB:
        return

    names = list(results.keys())
    utilizations = [(results[n]['total_mbps'] / bottleneck_bw) * 100 for n in names]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(names, utilizations, color='#2196F3', edgecolor='black', linewidth=0.5)

    for bar, val in zip(bars, utilizations):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                '%.1f%%' % val, ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax.set_ylabel('Utilization (%)', fontsize=12)
    ax.set_title('P4air: Link Utilization Comparison', fontsize=14, fontweight='bold')
    ax.set_ylim(0, 110)
    ax.axhline(y=100, color='green', linestyle='--', alpha=0.3, label='100% utilization')
    ax.axhline(y=90, color='orange', linestyle='--', alpha=0.3, label='90% target')
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    os.makedirs(output_dir, exist_ok=True)
    fpath = os.path.join(output_dir, 'utilization_comparison.png')
    plt.savefig(fpath, dpi=150)
    plt.close()
    print("  Saved: %s" % fpath)


def main():
    """Main entry point: load results and generate all charts."""
    parser = argparse.ArgumentParser(description='P4air Results Plotter')
    parser.add_argument('--results-dir', type=str, default='results',
                        help='Directory containing result JSON files (default: results/)')
    parser.add_argument('--output-dir', type=str, default='results/plots',
                        help='Directory to save charts (default: results/plots/)')
    parser.add_argument('--bw', type=int, default=10,
                        help='Bottleneck bandwidth in Mbps (default: 10)')
    args = parser.parse_args()

    print("\n*** Loading experiment results from %s ***\n" % args.results_dir)
    results = load_results(args.results_dir)

    if not results:
        print("\nERROR: No result files found in %s" % args.results_dir)
        print("Run experiments first: sudo python3 experiments/run_comparison.py")
        sys.exit(1)

    print("\n*** Generating charts ***\n")
    plot_fairness_comparison(results, args.output_dir)
    plot_throughput_per_flow(results, args.output_dir)
    plot_utilization(results, args.output_dir, bottleneck_bw=args.bw)

    print("\n*** All charts saved to %s ***\n" % args.output_dir)


if __name__ == '__main__':
    main()
