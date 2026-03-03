#!/usr/bin/env python3
"""
calculate_fairness.py — Jain's Fairness Index Calculator & Results Analyzer
=============================================================================
Reads iperf3 JSON result files and calculates Jain's Fairness Index.
Can also generate comparison tables across multiple test runs.

Jain's Fairness Index:
    J(x₁, ..., xₙ) = (Σxᵢ)² / (n × Σxᵢ²)
    Range: [1/n, 1] where 1 = perfectly fair

Usage:
    # Calculate from a list of iperf3 JSON files
    python3 calculate_fairness.py /tmp/p4air_h1.json /tmp/p4air_h2.json ...

    # Calculate from a saved results directory
    python3 calculate_fairness.py --dir results/

    # Compare multiple test runs
    python3 calculate_fairness.py --compare results/no_aqm.json results/p4air.json
"""

import json
import sys
import os
import argparse
import glob


def jains_fairness_index(throughputs):
    """Calculate Jain's Fairness Index for a list of throughput values.

    Formula: J(x) = (Σxᵢ)² / (n × Σxᵢ²)
    From: Jain, Chiu, and Hawe (1984)

    Args:
        throughputs: list of float values (e.g., Mbps per flow)

    Returns:
        float: Jain's Fairness Index in range [1/n, 1]
               Returns 0.0 if all throughputs are zero
    """
    n = len(throughputs)
    if n == 0:
        return 0.0

    sum_x = sum(throughputs)
    sum_x2 = sum(x ** 2 for x in throughputs)

    if sum_x2 == 0:
        return 0.0

    return (sum_x ** 2) / (n * sum_x2)


def parse_iperf3_json(filepath):
    """Extract throughput and retransmit data from an iperf3 JSON result file.

    Args:
        filepath: path to iperf3 JSON output file

    Returns:
        dict with keys: 'mbps', 'retransmits', 'duration', 'bytes_sent'
        Returns None if file is invalid or contains an error
    """
    try:
        with open(filepath, 'r') as f:
            content = f.read().strip()
        if not content:
            print("  WARNING: Empty file: %s" % filepath)
            return None

        data = json.loads(content)
        if 'error' in data:
            print("  WARNING: iperf3 error in %s: %s" % (filepath, data['error']))
            return None

        end = data['end']['sum_sent']
        return {
            'mbps': end['bits_per_second'] / 1e6,
            'retransmits': end.get('retransmits', 0),
            'duration': end.get('seconds', 0),
            'bytes_sent': end.get('bytes', 0)
        }
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print("  WARNING: Could not parse %s: %s" % (filepath, str(e)))
        return None


def analyze_results(result_files):
    """Analyze a set of iperf3 result files and compute fairness metrics.

    Args:
        result_files: list of paths to iperf3 JSON files

    Returns:
        dict with 'flows', 'throughputs', 'jain_index', 'total_mbps', 'utilization'
    """
    flows = {}
    throughputs = []

    for fpath in result_files:
        label = os.path.basename(fpath).replace('.json', '')
        result = parse_iperf3_json(fpath)
        if result:
            flows[label] = result
            throughputs.append(result['mbps'])
        else:
            throughputs.append(0.0)

    jain = jains_fairness_index(throughputs)
    total = sum(throughputs)
    n = len(throughputs)

    return {
        'flows': flows,
        'throughputs': throughputs,
        'num_flows': n,
        'jain_index': round(jain, 4),
        'total_mbps': round(total, 2),
        'avg_mbps': round(total / n, 2) if n > 0 else 0,
        'ideal_mbps': round(total / n, 2) if n > 0 else 0
    }


def print_analysis(analysis, title="P4air Traffic Analysis"):
    """Pretty-print the analysis results to console.

    Args:
        analysis: dict from analyze_results()
        title:    header string
    """
    print("\n" + "=" * 60)
    print("  %s" % title)
    print("=" * 60)

    # Per-flow results
    print("\n  Per-Flow Results:")
    print("  %-15s %10s %12s" % ("Flow", "Mbps", "Retransmits"))
    print("  " + "-" * 40)
    for label, data in analysis['flows'].items():
        print("  %-15s %10.2f %12s" %
              (label, data['mbps'], data['retransmits']))

    # Summary
    print("\n  Summary:")
    print("  Total Throughput:    %.2f Mbps" % analysis['total_mbps'])
    print("  Average per Flow:   %.2f Mbps" % analysis['avg_mbps'])
    print("  Jain's Fairness:    %.4f" % analysis['jain_index'])
    print("  Number of Flows:    %d" % analysis['num_flows'])

    # Interpret fairness
    j = analysis['jain_index']
    if j >= 0.95:
        verdict = "EXCELLENT (near perfect fairness)"
    elif j >= 0.85:
        verdict = "GOOD (minor unfairness)"
    elif j >= 0.70:
        verdict = "MODERATE (noticeable unfairness)"
    elif j >= 0.50:
        verdict = "POOR (significant unfairness)"
    else:
        verdict = "VERY POOR (severe unfairness)"
    print("  Verdict:            %s" % verdict)
    print("=" * 60)


def compare_runs(run_files):
    """Compare Jain's Fairness Index across multiple saved result files.

    Args:
        run_files: list of paths to saved summary JSON files (last_test.json format)
    """
    print("\n" + "=" * 60)
    print("  COMPARISON TABLE")
    print("=" * 60)
    print("  %-20s %10s %10s %8s" % ("Configuration", "Jain's FI", "Total Mbps", "Flows"))
    print("  " + "-" * 52)

    for fpath in run_files:
        try:
            with open(fpath, 'r') as f:
                data = json.load(f)
            label = os.path.basename(fpath).replace('.json', '').replace('_', ' ')
            print("  %-20s %10.4f %10.2f %8d" %
                  (label, data['jain_index'], data['total_mbps'], data['num_clients']))
        except Exception as e:
            print("  %-20s %s" % (fpath, str(e)))

    print("=" * 60)


def main():
    """Main entry point: parse arguments and run analysis."""
    parser = argparse.ArgumentParser(
        description='P4air Jain\'s Fairness Index Calculator')

    parser.add_argument('files', nargs='*',
                        help='iperf3 JSON result files to analyze')
    parser.add_argument('--dir',
                        help='Directory containing iperf3 JSON results')
    parser.add_argument('--compare', nargs='+',
                        help='Compare multiple saved test summaries')
    parser.add_argument('--output',
                        help='Save analysis to JSON file')

    args = parser.parse_args()

    if args.compare:
        # Compare mode: show table of multiple runs
        compare_runs(args.compare)
    elif args.dir:
        # Directory mode: find all iperf3 JSON files in directory
        pattern = os.path.join(args.dir, 'p4air_h*.json')
        files = sorted(glob.glob(pattern))
        if not files:
            # Try alternate pattern
            pattern = os.path.join(args.dir, '*.json')
            files = sorted(glob.glob(pattern))
        if not files:
            print("ERROR: No JSON files found in %s" % args.dir)
            sys.exit(1)

        analysis = analyze_results(files)
        print_analysis(analysis)

        if args.output:
            with open(args.output, 'w') as f:
                json.dump(analysis, f, indent=2)
            print("Results saved to %s" % args.output)
    elif args.files:
        # File list mode: analyze specified files
        analysis = analyze_results(args.files)
        print_analysis(analysis)

        if args.output:
            with open(args.output, 'w') as f:
                json.dump(analysis, f, indent=2)
            print("Results saved to %s" % args.output)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
