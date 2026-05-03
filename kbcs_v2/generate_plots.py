#!/usr/bin/env python3
"""
KBCS v2 -- Publication-Quality Plot Generator
=============================================
Generates plots from experimental CSV results for IEEE paper.
"""

import csv
import os
import numpy as np

# Try matplotlib
try:
    import matplotlib
    matplotlib.use('Agg')  # non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.gridspec import GridSpec
except ImportError:
    print("ERROR: matplotlib not installed. Run: pip install matplotlib")
    exit(1)

# ─── Config ───────────────────────────────────────────────────────────────────
RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')
PLOTS_DIR = os.path.join(os.path.dirname(__file__), 'plots')
os.makedirs(PLOTS_DIR, exist_ok=True)

# Professional color palette
KBCS_COLOR = '#2563EB'      # Blue
FIFO_COLOR = '#DC2626'      # Red
CROSS_COLOR = '#7C3AED'     # Purple
DBELL_COLOR = '#059669'     # Green
CCA_COLORS = {
    'CUBIC': '#2563EB',
    'BBR': '#DC2626',
    'Vegas': '#059669',
    'Illinois': '#D97706'
}

# Matplotlib global style
plt.rcParams.update({
    'font.family': 'serif',
    'font.size': 11,
    'axes.titlesize': 13,
    'axes.labelsize': 12,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
    'legend.fontsize': 10,
    'figure.dpi': 300,
    'savefig.dpi': 300,
    'savefig.bbox': 'tight',
    'axes.grid': True,
    'grid.alpha': 0.3,
    'axes.spines.top': False,
    'axes.spines.right': False,
})


def load_csv(filepath):
    """Load CSV, return list of dicts with numeric conversion."""
    rows = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            clean = {}
            for k, v in row.items():
                try:
                    clean[k] = float(v)
                except (ValueError, TypeError):
                    clean[k] = v
            rows.append(clean)
    return rows


def get_metric(rows, key):
    """Extract a list of values for a metric key."""
    return [r[key] for r in rows if key in r]


def get_per_flow_throughput(rows, num_flows):
    """Compute per-flow throughput in Mbps for each run."""
    flow_throughputs = {f'Flow {i+1}': [] for i in range(num_flows)}
    for row in rows:
        duration = row.get('duration', 60)
        for i in range(num_flows):
            fwd_key = f'fwd_{i+1}'
            if fwd_key in row:
                tp = (row[fwd_key] * 8) / (duration * 1_000_000)
                flow_throughputs[f'Flow {i+1}'].append(tp)
    return flow_throughputs


# ─── PLOT 1: JFI Comparison Bar Chart (Hero Chart) ───────────────────────────
def plot_jfi_comparison(kbcs_dbell, fifo_dbell, kbcs_cross, fifo_cross):
    """Side-by-side JFI comparison: KBCS vs FIFO for both topologies."""
    fig, ax = plt.subplots(figsize=(8, 5))

    jfi_data = {
        'Dumbbell\n(4 flows)': {
            'FIFO': get_metric(fifo_dbell, 'jfi'),
            'KBCS': get_metric(kbcs_dbell, 'jfi')
        },
        'Cross\n(8 flows)': {
            'FIFO': get_metric(fifo_cross, 'jfi'),
            'KBCS': get_metric(kbcs_cross, 'jfi')
        }
    }

    x = np.arange(len(jfi_data))
    width = 0.3

    fifo_means = [np.mean(v['FIFO']) for v in jfi_data.values()]
    fifo_stds = [np.std(v['FIFO']) for v in jfi_data.values()]
    kbcs_means = [np.mean(v['KBCS']) for v in jfi_data.values()]
    kbcs_stds = [np.std(v['KBCS']) for v in jfi_data.values()]

    bars1 = ax.bar(x - width/2, fifo_means, width, yerr=fifo_stds,
                   label='FIFO (Baseline)', color=FIFO_COLOR, alpha=0.85,
                   capsize=5, edgecolor='white', linewidth=1)
    bars2 = ax.bar(x + width/2, kbcs_means, width, yerr=kbcs_stds,
                   label='KBCS (Proposed)', color=KBCS_COLOR, alpha=0.85,
                   capsize=5, edgecolor='white', linewidth=1)

    # Add improvement annotations
    for i, (fm, km) in enumerate(zip(fifo_means, kbcs_means)):
        pct = ((km - fm) / fm) * 100
        ax.annotate(f'+{pct:.1f}%',
                    xy=(x[i] + width/2, km + kbcs_stds[i] + 0.01),
                    ha='center', va='bottom', fontweight='bold',
                    fontsize=11, color=KBCS_COLOR)

    ax.set_ylabel("Jain's Fairness Index")
    ax.set_title("Fairness Comparison: KBCS vs FIFO Baseline")
    ax.set_xticks(x)
    ax.set_xticklabels(jfi_data.keys())
    ax.set_ylim(0.5, 1.08)
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.4, label='Perfect Fairness')
    ax.legend(loc='lower right')

    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, 'jfi_comparison.png')
    fig.savefig(path)
    plt.close(fig)
    print(f"  [OK] Saved: {path}")
    return path


# ─── PLOT 2: Multi-Metric Comparison (Grouped Bar) ──────────────────────────
def plot_multi_metric(kbcs_dbell, fifo_dbell, kbcs_cross, fifo_cross):
    """4-panel comparison of all key metrics."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))

    metrics = [
        ("Jain's Fairness Index", 'jfi', (0, 0)),
        ('Aggregate Throughput (Mbps)', 'agg_throughput_mbps', (0, 1)),
        ('Link Utilization (%)', 'link_util_pct', (1, 0)),
        ('Packet Drop Ratio (%)', 'pdr_pct', (1, 1)),
    ]

    configs = [
        ('FIFO\nDumbbell', fifo_dbell, FIFO_COLOR, '///'),
        ('KBCS\nDumbbell', kbcs_dbell, KBCS_COLOR, None),
        ('FIFO\nCross', fifo_cross, FIFO_COLOR, '\\\\\\'),
        ('KBCS\nCross', kbcs_cross, KBCS_COLOR, '...'),
    ]

    for title, key, (r, c) in metrics:
        ax = axes[r][c]
        means = []
        stds = []
        labels = []
        colors = []

        for label, data, color, hatch in configs:
            vals = get_metric(data, key)
            means.append(np.mean(vals))
            stds.append(np.std(vals))
            labels.append(label)
            colors.append(color)

        x = np.arange(len(configs))
        bars = ax.bar(x, means, yerr=stds, capsize=4,
                      color=[c[3] for c in configs],  # Use config color
                      alpha=0.85, edgecolor='white', linewidth=1)

        # Color bars properly
        for bar, (lbl, _, color, hatch) in zip(bars, configs):
            bar.set_facecolor(color)
            bar.set_alpha(0.7 if 'FIFO' in lbl else 0.9)
            if hatch:
                bar.set_hatch(hatch)

        ax.set_ylabel(title.split('(')[0].strip())
        ax.set_title(title, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=9)

    fig.suptitle('KBCS Performance Evaluation -- All Metrics', fontsize=14, fontweight='bold', y=1.02)
    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, 'multi_metric_comparison.png')
    fig.savefig(path)
    plt.close(fig)
    print(f"  [OK] Saved: {path}")
    return path


# ─── PLOT 3: Per-Flow Throughput (FIFO vs KBCS Dumbbell) ─────────────────────
def plot_per_flow_throughput(kbcs_dbell, fifo_dbell):
    """Box plot showing per-flow throughput distribution: FIFO starves some flows, KBCS equalizes."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5), sharey=True)

    cca_labels = ['CUBIC', 'BBR', 'Vegas', 'Illinois']
    cca_colors = [CCA_COLORS[c] for c in cca_labels]

    # FIFO
    fifo_flows = get_per_flow_throughput(fifo_dbell, 4)
    fifo_data = [fifo_flows[f'Flow {i+1}'] for i in range(4)]
    bp1 = ax1.boxplot(fifo_data, patch_artist=True, labels=cca_labels,
                      widths=0.5, showfliers=True,
                      flierprops=dict(marker='o', markersize=3, alpha=0.5))
    for patch, color in zip(bp1['boxes'], cca_colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    ax1.set_title('FIFO Baseline -- Per-Flow Throughput', fontweight='bold')
    ax1.set_ylabel('Throughput (Mbps)')
    ax1.set_xlabel('Congestion Control Algorithm')

    # KBCS
    kbcs_flows = get_per_flow_throughput(kbcs_dbell, 4)
    kbcs_data = [kbcs_flows[f'Flow {i+1}'] for i in range(4)]
    bp2 = ax2.boxplot(kbcs_data, patch_artist=True, labels=cca_labels,
                      widths=0.5, showfliers=True,
                      flierprops=dict(marker='o', markersize=3, alpha=0.5))
    for patch, color in zip(bp2['boxes'], cca_colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    ax2.set_title('KBCS -- Per-Flow Throughput', fontweight='bold')
    ax2.set_xlabel('Congestion Control Algorithm')

    # Add fairness annotations
    fifo_jfi = np.mean(get_metric(fifo_dbell, 'jfi'))
    kbcs_jfi = np.mean(get_metric(kbcs_dbell, 'jfi'))
    ax1.text(0.95, 0.95, f'JFI = {fifo_jfi:.3f}', transform=ax1.transAxes,
             ha='right', va='top', fontweight='bold', fontsize=12,
             bbox=dict(boxstyle='round,pad=0.3', facecolor=FIFO_COLOR, alpha=0.15))
    ax2.text(0.95, 0.95, f'JFI = {kbcs_jfi:.3f}', transform=ax2.transAxes,
             ha='right', va='top', fontweight='bold', fontsize=12,
             bbox=dict(boxstyle='round,pad=0.3', facecolor=KBCS_COLOR, alpha=0.15))

    fig.suptitle('Per-Flow Throughput Distribution -- Dumbbell Topology (30 runs)',
                 fontsize=13, fontweight='bold')
    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, 'per_flow_throughput_dumbbell.png')
    fig.savefig(path)
    plt.close(fig)
    print(f"  [OK] Saved: {path}")
    return path


# ─── PLOT 4: JFI Box Plot Distribution ──────────────────────────────────────
def plot_jfi_boxplot(kbcs_dbell, fifo_dbell, kbcs_cross, fifo_cross):
    """Box plots showing JFI distribution across all 30 runs for each config."""
    fig, ax = plt.subplots(figsize=(9, 5))

    data = [
        get_metric(fifo_dbell, 'jfi'),
        get_metric(kbcs_dbell, 'jfi'),
        get_metric(fifo_cross, 'jfi'),
        get_metric(kbcs_cross, 'jfi'),
    ]
    labels = ['FIFO\nDumbbell', 'KBCS\nDumbbell', 'FIFO\nCross', 'KBCS\nCross']
    colors = [FIFO_COLOR, KBCS_COLOR, FIFO_COLOR, KBCS_COLOR]

    bp = ax.boxplot(data, patch_artist=True, labels=labels, widths=0.5,
                    showmeans=True,
                    meanprops=dict(marker='D', markerfacecolor='white',
                                   markeredgecolor='black', markersize=6),
                    flierprops=dict(marker='o', markersize=4, alpha=0.5))

    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)

    # Add mean labels
    for i, d in enumerate(data):
        m = np.mean(d)
        ax.text(i + 1, m + 0.015, f'{m:.3f}', ha='center', va='bottom',
                fontweight='bold', fontsize=10)

    ax.set_ylabel("Jain's Fairness Index")
    ax.set_title("JFI Distribution Across 30 Runs -- KBCS vs FIFO", fontweight='bold')
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.4, label='Perfect Fairness')
    ax.set_ylim(0.4, 1.1)

    # Custom legend
    fifo_patch = mpatches.Patch(color=FIFO_COLOR, alpha=0.6, label='FIFO Baseline')
    kbcs_patch = mpatches.Patch(color=KBCS_COLOR, alpha=0.6, label='KBCS (Proposed)')
    ax.legend(handles=[fifo_patch, kbcs_patch], loc='lower left')

    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, 'jfi_boxplot.png')
    fig.savefig(path)
    plt.close(fig)
    print(f"  [OK] Saved: {path}")
    return path


# ─── PLOT 5: Per-Flow Karma Score Heatmap (Dumbbell) ─────────────────────────
def plot_karma_heatmap(kbcs_dbell):
    """Heatmap of per-flow karma scores across runs -- shows KBCS actively penalizing."""
    fig, ax = plt.subplots(figsize=(10, 5))

    cca_labels = ['CUBIC', 'BBR', 'Vegas', 'Illinois']
    karma_matrix = []

    for row in kbcs_dbell:
        run_karma = []
        for i in range(4):
            k = row.get(f'karma_{i+1}', 0)
            run_karma.append(k)
        karma_matrix.append(run_karma)

    karma_arr = np.array(karma_matrix).T  # shape: (4 flows, 30 runs)

    im = ax.imshow(karma_arr, aspect='auto', cmap='RdYlGn',
                   vmin=0, vmax=100, interpolation='nearest')
    ax.set_yticks(range(4))
    ax.set_yticklabels(cca_labels)
    ax.set_xlabel('Run Number')
    ax.set_ylabel('Flow (CCA)')
    ax.set_title('Per-Flow Karma Scores -- Dumbbell Topology (30 Runs)', fontweight='bold')

    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label('Karma Score (0=RED, 100=GREEN)')

    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, 'karma_heatmap_dumbbell.png')
    fig.savefig(path)
    plt.close(fig)
    print(f"  [OK] Saved: {path}")
    return path


# ─── PLOT 6: Comprehensive Summary Table as Figure ──────────────────────────
def plot_summary_table(kbcs_dbell, fifo_dbell, kbcs_cross, fifo_cross):
    """Creates a publication-ready summary table as an image."""
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.axis('off')

    metrics = ['JFI', 'Throughput (Mbps)', 'Link Util. (%)', 'PDR (%)']
    keys = ['jfi', 'agg_throughput_mbps', 'link_util_pct', 'pdr_pct']

    table_data = []
    for name, key in zip(metrics, keys):
        fd = get_metric(fifo_dbell, key)
        kd = get_metric(kbcs_dbell, key)
        fc = get_metric(fifo_cross, key)
        kc = get_metric(kbcs_cross, key)

        dbell_imp = ((np.mean(kd) - np.mean(fd)) / np.mean(fd)) * 100
        cross_imp = ((np.mean(kc) - np.mean(fc)) / np.mean(fc)) * 100

        table_data.append([
            name,
            f'{np.mean(fd):.3f}±{np.std(fd):.3f}',
            f'{np.mean(kd):.3f}±{np.std(kd):.3f}',
            f'{dbell_imp:+.1f}%',
            f'{np.mean(fc):.3f}±{np.std(fc):.3f}',
            f'{np.mean(kc):.3f}±{np.std(kc):.3f}',
            f'{cross_imp:+.1f}%',
        ])

    col_labels = ['Metric', 'FIFO', 'KBCS', 'Δ%',
                  'FIFO', 'KBCS', 'Δ%']

    table = ax.table(cellText=table_data, colLabels=col_labels,
                     cellLoc='center', loc='center')

    # Style the table
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.8)

    # Header styling
    for j in range(len(col_labels)):
        table[(0, j)].set_facecolor('#1E3A5F')
        table[(0, j)].set_text_props(color='white', fontweight='bold')

    # Alternating row colors
    for i in range(1, len(table_data) + 1):
        for j in range(len(col_labels)):
            if i % 2 == 0:
                table[(i, j)].set_facecolor('#E8F0FE')

    # Add topology headers
    ax.text(0.37, 0.95, 'Dumbbell Topology', transform=ax.transAxes,
            ha='center', va='bottom', fontweight='bold', fontsize=12)
    ax.text(0.73, 0.95, 'Cross Topology', transform=ax.transAxes,
            ha='center', va='bottom', fontweight='bold', fontsize=12)

    fig.suptitle('KBCS Performance Summary -- 30 Runs per Configuration',
                 fontsize=14, fontweight='bold', y=1.05)
    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, 'summary_table.png')
    fig.savefig(path)
    plt.close(fig)
    print(f"  [OK] Saved: {path}")
    return path


# ─── PLOT 7: Per-Flow Throughput (FIFO vs KBCS Cross) ────────────────────────
def plot_per_flow_throughput_cross(kbcs_cross, fifo_cross):
    """Box plot showing per-flow throughput for 8-flow cross topology."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5), sharey=True)

    # Cross has 8 flows: S1 flows 1-4 + S2 flows 5-8
    cca_labels = ['CUBIC\n(S1)', 'BBR\n(S1)', 'Vegas\n(S1)', 'Illinois\n(S1)',
                  'CUBIC\n(S2)', 'BBR\n(S2)', 'Vegas\n(S2)', 'Illinois\n(S2)']
    cca_colors_8 = ['#2563EB', '#DC2626', '#059669', '#D97706',
                    '#60A5FA', '#F87171', '#34D399', '#FBBF24']

    # FIFO
    fifo_flows = get_per_flow_throughput(fifo_cross, 8)
    fifo_data = [fifo_flows[f'Flow {i+1}'] for i in range(8)]
    bp1 = ax1.boxplot(fifo_data, patch_artist=True, tick_labels=cca_labels,
                      widths=0.5, showfliers=True,
                      flierprops=dict(marker='o', markersize=3, alpha=0.5))
    for patch, color in zip(bp1['boxes'], cca_colors_8):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    ax1.set_title('FIFO Baseline -- Per-Flow Throughput', fontweight='bold')
    ax1.set_ylabel('Throughput (Mbps)')
    ax1.tick_params(axis='x', labelsize=8)

    # KBCS
    kbcs_flows = get_per_flow_throughput(kbcs_cross, 8)
    kbcs_data = [kbcs_flows[f'Flow {i+1}'] for i in range(8)]
    bp2 = ax2.boxplot(kbcs_data, patch_artist=True, tick_labels=cca_labels,
                      widths=0.5, showfliers=True,
                      flierprops=dict(marker='o', markersize=3, alpha=0.5))
    for patch, color in zip(bp2['boxes'], cca_colors_8):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    ax2.set_title('KBCS -- Per-Flow Throughput', fontweight='bold')
    ax2.tick_params(axis='x', labelsize=8)

    # JFI annotations
    fifo_jfi = np.mean(get_metric(fifo_cross, 'jfi'))
    kbcs_jfi = np.mean(get_metric(kbcs_cross, 'jfi'))
    ax1.text(0.95, 0.95, f'JFI = {fifo_jfi:.3f}', transform=ax1.transAxes,
             ha='right', va='top', fontweight='bold', fontsize=12,
             bbox=dict(boxstyle='round,pad=0.3', facecolor=FIFO_COLOR, alpha=0.15))
    ax2.text(0.95, 0.95, f'JFI = {kbcs_jfi:.3f}', transform=ax2.transAxes,
             ha='right', va='top', fontweight='bold', fontsize=12,
             bbox=dict(boxstyle='round,pad=0.3', facecolor=KBCS_COLOR, alpha=0.15))

    fig.suptitle('Per-Flow Throughput Distribution -- Cross Topology, 8 Flows (30 runs)',
                 fontsize=13, fontweight='bold')
    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, 'per_flow_throughput_cross.png')
    fig.savefig(path)
    plt.close(fig)
    print(f"  [OK] Saved: {path}")
    return path


# ─── PLOT 8: Per-Flow Karma Heatmap (Cross Topology) ────────────────────────
def plot_karma_heatmap_cross(kbcs_cross):
    """Heatmap of per-flow karma scores for 8-flow cross topology."""
    fig, ax = plt.subplots(figsize=(12, 5))

    flow_labels = ['CUBIC (S1)', 'BBR (S1)', 'Vegas (S1)', 'Illinois (S1)',
                   'CUBIC (S2)', 'BBR (S2)', 'Vegas (S2)', 'Illinois (S2)']
    karma_matrix = []

    for row in kbcs_cross:
        run_karma = []
        for i in range(8):
            k = row.get(f'karma_{i+1}', 0)
            run_karma.append(k)
        karma_matrix.append(run_karma)

    karma_arr = np.array(karma_matrix).T  # shape: (8 flows, 30 runs)

    im = ax.imshow(karma_arr, aspect='auto', cmap='RdYlGn',
                   vmin=0, vmax=100, interpolation='nearest')
    ax.set_yticks(range(8))
    ax.set_yticklabels(flow_labels, fontsize=9)
    ax.set_xlabel('Run Number')
    ax.set_ylabel('Flow (CCA / Switch)')
    ax.set_title('Per-Flow Karma Scores -- Cross Topology, 8 Flows (30 Runs)', fontweight='bold')

    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label('Karma Score (0=RED, 100=GREEN)')

    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, 'karma_heatmap_cross.png')
    fig.savefig(path)
    plt.close(fig)
    print(f"  [OK] Saved: {path}")
    return path


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("\n===============================================")
    print("  KBCS v2 -- Plot Generator")
    print("===============================================\n")

    # Load all CSVs
    files = {
        'kbcs_dbell': os.path.join(RESULTS_DIR, 'dumbbell_results.csv'),
        'fifo_dbell': os.path.join(RESULTS_DIR, 'fifo_dumbbell_results.csv'),
        'kbcs_cross': os.path.join(RESULTS_DIR, 'cross_results.csv'),
        'fifo_cross': os.path.join(RESULTS_DIR, 'fifo_cross_results.csv'),
    }

    data = {}
    for key, path in files.items():
        if os.path.exists(path):
            data[key] = load_csv(path)
            print(f"  Loaded {key}: {len(data[key])} runs")
        else:
            print(f"  WARNING: {path} not found")
            data[key] = None

    if not all(data.values()):
        print("\n  ERROR: Some CSV files missing. Run all test suites first.")
        return

    print("\n  Generating plots...")

    # Generate all plots
    plot_jfi_comparison(data['kbcs_dbell'], data['fifo_dbell'],
                        data['kbcs_cross'], data['fifo_cross'])

    plot_per_flow_throughput(data['kbcs_dbell'], data['fifo_dbell'])

    plot_per_flow_throughput_cross(data['kbcs_cross'], data['fifo_cross'])

    plot_jfi_boxplot(data['kbcs_dbell'], data['fifo_dbell'],
                     data['kbcs_cross'], data['fifo_cross'])

    plot_karma_heatmap(data['kbcs_dbell'])

    plot_karma_heatmap_cross(data['kbcs_cross'])

    plot_summary_table(data['kbcs_dbell'], data['fifo_dbell'],
                       data['kbcs_cross'], data['fifo_cross'])

    print(f"\n  [OK] All plots saved to: {PLOTS_DIR}/")
    print("  Files:")
    for f in sorted(os.listdir(PLOTS_DIR)):
        if f.endswith('.png'):
            print(f"    • {f}")


if __name__ == '__main__':
    main()
