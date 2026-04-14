#!/usr/bin/env python3
"""
plot_results.py — KBCS Evaluation Visualizer
=============================================
Reads results/experiment_summary.json and generates:
  1. Grouped bar chart: per-flow throughput across all experiments
  2. Jain's FI comparison bar chart
  3. [E12] Animated karma timeline simulation (exported as .gif)

Usage (on Ubuntu VM or Windows host):
    python3 plot_results.py [--results results/experiment_summary.json]
                            [--animate]
                            [--output results/]
"""

import json
import os
import argparse
import math
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for headless VM
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


# ================================================================== #
# Color palette                                                         #
# ================================================================== #
CCA_COLORS = {
    'CUBIC':      '#e74c3c',    # Red-ish
    'BBR':        '#2ecc71',    # Green
    'Vegas':      '#3498db',    # Blue
    'Illinois':   '#f39c12',    # Orange
    'long':       '#8e44ad',    # Purple
    'cross@s1':   '#e74c3c',
    'cross@s2':   '#2ecc71',
    'cross@s3':   '#3498db',
    'cross@s4':   '#f39c12',
}

EXPERIMENT_HATCH = ['', '///', 'xxx']
EXPERIMENT_COLORS = ['#2c3e50', '#27ae60', '#e67e22']


# ================================================================== #
# Helpers                                                               #
# ================================================================== #
def load_results(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def flow_label(info: dict, hname: str) -> str:
    """Build a short display label from flow info dict."""
    return info.get('label', info.get('cca', hname))


# ================================================================== #
# Figure 1: Per-flow throughput grouped bar chart                       #
# ================================================================== #
def plot_throughput(experiments: dict, outdir: str):
    """
    For each experiment, show per-flow Mbps as grouped bars.
    All experiments plotted side-by-side for easy comparison.
    """
    fig, axes = plt.subplots(1, len(experiments), figsize=(6*len(experiments), 6),
                              sharey=True)
    if len(experiments) == 1:
        axes = [axes]

    fig.suptitle("KBCS Evaluation — Per-Flow Throughput",
                 fontsize=16, fontweight='bold', y=1.02)

    for ax, (exp_name, data), hatch, col in zip(
            axes, experiments.items(), EXPERIMENT_HATCH, EXPERIMENT_COLORS):

        flows  = data.get('flows', {})
        labels = []
        values = []
        colors = []

        for hname, info in flows.items():
            lbl = flow_label(info, hname)
            labels.append(lbl)
            values.append(info.get('mbps', 0))
            # Match CCA color by substring
            c = '#95a5a6'
            for kw, fc in CCA_COLORS.items():
                if kw.lower() in lbl.lower():
                    c = fc
                    break
            colors.append(c)

        x_pos = np.arange(len(labels))
        bars = ax.bar(x_pos, values, color=colors, edgecolor='white',
                      hatch=hatch, linewidth=1.2, zorder=3)

        # Value labels on top of each bar
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.1,
                    f'{val:.1f}', ha='center', va='bottom',
                    fontsize=9, fontweight='bold')

        jain = data.get('jain_index', 0)
        total = data.get('total_mbps', sum(values))
        ax.set_title(f'{exp_name}\nJain FI={jain:.4f} | Total={total:.1f} Mbps',
                     fontsize=11, pad=8)
        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, rotation=20, ha='right', fontsize=9)
        ax.set_ylabel('Throughput (Mbps)', fontsize=11)
        ax.set_ylim(0, 12.5)
        ax.axhline(y=10, color='#c0392b', linestyle='--',
                   linewidth=1, label='10 Mbps Link', zorder=2)
        ax.grid(axis='y', linestyle=':', alpha=0.5, zorder=1)
        ax.legend(fontsize=8)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

    plt.tight_layout()
    path = os.path.join(outdir, 'throughput_comparison.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    print(f'  [plot] Saved: {path}')
    plt.close()


# ================================================================== #
# Figure 2: Jain's Fairness Index comparison                           #
# ================================================================== #
def plot_jain(experiments: dict, outdir: str):
    names  = list(experiments.keys())
    jains  = [d.get('jain_index', 0) for d in experiments.values()]
    totals = [d.get('total_mbps', 0) for d in experiments.values()]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("KBCS Evaluation Summary", fontsize=15, fontweight='bold')

    # Jain's FI
    bars = ax1.bar(names, jains, color=EXPERIMENT_COLORS[:len(names)],
                   edgecolor='white', linewidth=1.2, zorder=3)
    for bar, val in zip(bars, jains):
        ax1.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() + 0.005,
                 f'{val:.4f}', ha='center', va='bottom',
                 fontsize=10, fontweight='bold')
    ax1.axhline(y=0.95, color='green', linestyle='--', label='Target JFI ≥ 0.95')
    ax1.set_ylim(0.5, 1.05)
    ax1.set_ylabel("Jain's Fairness Index", fontsize=12)
    ax1.set_title("Fairness (higher = better)", fontsize=11)
    ax1.set_xticklabels(names, rotation=15, ha='right')
    ax1.legend(fontsize=9)
    ax1.grid(axis='y', linestyle=':', alpha=0.5, zorder=1)
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)

    # Total throughput
    bars2 = ax2.bar(names, totals, color=EXPERIMENT_COLORS[:len(names)],
                    edgecolor='white', linewidth=1.2, zorder=3)
    for bar, val in zip(bars2, totals):
        ax2.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() + 0.1,
                 f'{val:.1f}', ha='center', va='bottom',
                 fontsize=10, fontweight='bold')
    ax2.axhline(y=10, color='#c0392b', linestyle='--', label='10 Mbps Link')
    ax2.set_ylim(0, 13)
    ax2.set_ylabel('Total Throughput (Mbps)', fontsize=12)
    ax2.set_title('Utilization (higher = better)', fontsize=11)
    ax2.set_xticklabels(names, rotation=15, ha='right')
    ax2.legend(fontsize=9)
    ax2.grid(axis='y', linestyle=':', alpha=0.5, zorder=1)
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)

    plt.tight_layout()
    path = os.path.join(outdir, 'jain_summary.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    print(f'  [plot] Saved: {path}')
    plt.close()


# ================================================================== #
# Figure 3 [E12]: Animated Karma Timeline Simulation                   */
# ================================================================== #
def plot_animated_karma(outdir: str, duration_s: int = 30):
    """
    [E12] Simulate and animate per-flow karma scores over time.
    Shows CUBIC starting high and dropping, BBR staying stable,
    and Vegas / Illinois in between — demonstrating KBCS dynamics.
    This is a simulated demo (not from live register reads).
    For live karma, wire reg_flow_karma reads via simple_switch_CLI.
    """
    try:
        import matplotlib.animation as animation
    except ImportError:
        print('  [plot] matplotlib.animation unavailable — skipping')
        return

    time_axis = np.linspace(0, duration_s, duration_s * 10)
    n_pts = len(time_axis)

    # Simulate karma trajectories (realistic KBCS dynamics)
    def cubic_karma(t):
        # CUBIC: starts ok, congests fast, oscillates between RED and YELLOW
        k = 100 - 70 * (1 - np.exp(-t / 3))
        k += 15 * np.sin(t * 0.8)
        return np.clip(k, 0, 100)

    def bbr_karma(t):
        # BBR: stays mostly GREEN, small dips during slow start
        k = 80 + 15 * np.exp(-t / 5) * np.sin(t)
        k += np.random.normal(0, 2, size=len(t)) if hasattr(t, '__len__') else 0
        return np.clip(k, 60, 100)

    def vegas_karma(t):
        # Vegas: delay-based, stays YELLOW/GREEN
        k = 65 + 20 * np.sin(t * 0.3 + 1)
        return np.clip(k, 35, 90)

    def illinois_karma(t):
        # Illinois: hybrid, intermediate behavior
        k = 55 + 15 * np.cos(t * 0.5 + 0.5)
        return np.clip(k, 20, 85)

    np.random.seed(42)
    karma_data = {
        'CUBIC'    : cubic_karma(time_axis),
        'BBR'      : bbr_karma(time_axis),
        'Vegas'    : vegas_karma(time_axis),
        'Illinois' : illinois_karma(time_axis),
    }
    flow_colors_map = {
        'CUBIC': '#e74c3c', 'BBR': '#2ecc71',
        'Vegas': '#3498db', 'Illinois': '#f39c12'
    }

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')
    ax.set_xlim(0, duration_s)
    ax.set_ylim(-5, 110)
    ax.set_xlabel('Time (seconds)', color='white', fontsize=12)
    ax.set_ylabel('Karma Score', color='white', fontsize=12)
    ax.set_title('KBCS Karma Timeline — Flow Behavior Over Time',
                 color='white', fontsize=14, fontweight='bold')
    ax.tick_params(colors='white')
    for spine in ax.spines.values():
        spine.set_edgecolor('#888')

    # Threshold lines
    ax.axhline(y=80, color='#2ecc71', linestyle='--', alpha=0.6, label='GREEN threshold (80)')
    ax.axhline(y=40, color='#e67e22', linestyle='--', alpha=0.6, label='YELLOW threshold (40)')
    ax.axhline(y=20, color='#e74c3c', linestyle='--', alpha=0.6, label='CRITICAL (20) — AQM drop')

    # Shade regions
    ax.axhspan(80, 105, alpha=0.05, color='green')
    ax.axhspan(40, 80,  alpha=0.05, color='orange')
    ax.axhspan(0,  40,  alpha=0.05, color='red')

    lines = {}
    for cca, col in flow_colors_map.items():
        line, = ax.plot([], [], color=col, linewidth=2.5, label=cca)
        lines[cca] = line

    ax.legend(loc='upper right', fontsize=9,
              facecolor='#16213e', labelcolor='white')

    time_text = ax.text(0.02, 0.95, '', transform=ax.transAxes,
                        color='white', fontsize=10)

    def init():
        for line in lines.values():
            line.set_data([], [])
        time_text.set_text('')
        return list(lines.values()) + [time_text]

    step = 5  # Skip every 5 pts for smoother animation
    frames = range(1, n_pts, step)

    def animate(i):
        t_slice = time_axis[:i]
        for cca, line in lines.items():
            line.set_data(t_slice, karma_data[cca][:i])
        time_text.set_text(f't = {time_axis[min(i, n_pts-1)]:.1f}s')
        return list(lines.values()) + [time_text]

    ani = animation.FuncAnimation(fig, animate, frames=frames,
                                   init_func=init, blit=True,
                                   interval=50)

    gif_path = os.path.join(outdir, 'karma_animation.gif')
    try:
        ani.save(gif_path, writer='pillow', fps=20, dpi=100)
        print(f'  [plot] Saved animated GIF: {gif_path}')
    except Exception as e:
        print(f'  [plot] GIF save failed ({e}). Install pillow: pip install pillow')

    plt.close()


# ================================================================== #
# Main                                                                  #
# ================================================================== #
def main():
    p = argparse.ArgumentParser(description='KBCS Results Visualizer')
    p.add_argument('--results', default='results/experiment_summary.json',
                   help='Path to experiment_summary.json')
    p.add_argument('--animate', action='store_true',
                   help='Generate animated karma timeline GIF [E12]')
    p.add_argument('--output', default='results/',
                   help='Output directory for plots')
    args = p.parse_args()

    os.makedirs(args.output, exist_ok=True)

    if not os.path.exists(args.results):
        print(f'ERROR: {args.results} not found. Run make experiment first.')
        return

    print(f'Loading results from {args.results}...')
    data = load_results(args.results)
    experiments = data.get('experiments', {})

    if not experiments:
        print('No experiment data found in summary JSON.')
        return

    print(f'Found {len(experiments)} experiment(s): {list(experiments.keys())}')

    plot_throughput(experiments, args.output)
    plot_jain(experiments, args.output)

    if args.animate:
        duration = data.get('duration', 30)
        print(f'  [E12] Generating animated karma timeline ({duration}s)...')
        plot_animated_karma(args.output, duration_s=duration)

    print(f'\n✅ All plots saved to {args.output}')


if __name__ == '__main__':
    main()
