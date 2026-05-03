import matplotlib.pyplot as plt
import numpy as np
import os

def main():
    # Data manually extracted from user's 16-flow output
    plot_data = [
        {'name': 'No AQM (FIFO)',      'avg_jfi': 0.9123, 'std_jfi': 0.03, 'avg_mbps': 10.23, 'std_mbps': 0.08},
        {'name': 'Diff Queues (Hash)', 'avg_jfi': 0.9390, 'std_jfi': 0.02, 'avg_mbps': 10.35, 'std_mbps': 0.15},
        {'name': 'P4air (CCA Aware)',  'avg_jfi': 0.9483, 'std_jfi': 0.02, 'avg_mbps': 11.02, 'std_mbps': 0.07}
    ]

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
    ax1.set_xlabel('Queue Configuration', fontsize=12)
    ax1.set_ylabel("Average Jain's Fairness Index", color=color, fontweight='bold', fontsize=12)
    ax1.bar(x - width/2, jfi_means, width, yerr=jfi_stds, capsize=5, 
            color=color, alpha=0.7, label="Jain's FI (Higher is Fairer)")
    ax1.tick_params(axis='y', labelcolor=color)
    ax1.set_ylim(0, 1.1)

    # Bar chart for Total Throughput on secondary Y axis
    ax2 = ax1.twinx()
    color = 'tab:green'
    ax2.set_ylabel('Average Total Throughput (Mbps)', color=color, fontweight='bold', fontsize=12)
    ax2.bar(x + width/2, mbps_means, width, yerr=mbps_stds, capsize=5, 
            color=color, alpha=0.7, label='Total Throughput')
    ax2.tick_params(axis='y', labelcolor=color)
    ax2.set_ylim(0, 14) 

    # Add legends
    fig.legend(loc="upper right", bbox_to_anchor=(0.95, 0.95))

    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=11)
    
    plt.title('P4air vs Baselines: 16 Flows (Scale Testing)\n(5 Iteration Averages | Error bars = ±1 Standard Deviation)', fontsize=14)
    
    fig.tight_layout()
    os.makedirs('results', exist_ok=True)
    plot_path = 'results/comparison_graph_16_flows.png'
    plt.savefig(plot_path, dpi=150)
    print(f"Graph successfully generated and saved to: {plot_path}")

if __name__ == '__main__':
    main()
