import json
import matplotlib.pyplot as plt
import numpy as np
import statistics
import os

def main():
    data_path = 'results/multiple_runs_data.json'
    if not os.path.exists(data_path):
        print(f"Error: {data_path} not found.")
        return

    with open(data_path, 'r') as f:
        all_data = json.load(f)

    configs = ['no_aqm', 'diff_queues', 'p4air']
    plot_data = []

    for c in configs:
        if c not in all_data:
            continue
        jfi_list = all_data[c]['jfi']
        mbps_list = all_data[c]['total_mbps']
        
        avg_jfi = statistics.mean(jfi_list) if jfi_list else 0
        std_jfi = statistics.stdev(jfi_list) if len(jfi_list) > 1 else 0.0
        
        avg_mbps = statistics.mean(mbps_list) if mbps_list else 0
        std_mbps = statistics.stdev(mbps_list) if len(mbps_list) > 1 else 0.0
        
        desc = c
        if c == 'no_aqm': desc = 'No AQM (FIFO)'
        if c == 'diff_queues': desc = 'Diff Queues (Hash)'
        if c == 'p4air': desc = 'P4air (CCA Aware)'
        
        plot_data.append({
            'name': desc,
            'avg_jfi': avg_jfi, 'std_jfi': std_jfi,
            'avg_mbps': avg_mbps, 'std_mbps': std_mbps
        })

    if not plot_data:
        print("No plot data found.")
        return

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
    
    ax2.set_ylim(0, 12) 

    # Add legends
    fig.legend(loc="upper right", bbox_to_anchor=(0.95, 0.95))

    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=11)
    
    num_runs = len(all_data['p4air']['jfi'])
    plt.title(f'P4air vs Baselines: Average Performance over {num_runs} runs\n(Error bars = ±1 Standard Deviation)', fontsize=14)
    
    fig.tight_layout()
    plot_path = 'results/comparison_graph.png'
    os.makedirs('results', exist_ok=True)
    plt.savefig(plot_path, dpi=150)
    print(f"Graph successfully generated and saved to: {plot_path}")

if __name__ == '__main__':
    main()
