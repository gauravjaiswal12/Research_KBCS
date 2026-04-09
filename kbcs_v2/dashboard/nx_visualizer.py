#!/usr/bin/env python3
"""
KBCS v2 — NetworkX Live Topology Visualizer
=============================================
Desktop GUI visualizer using matplotlib and networkx.
Shows the full 4-switch, 12-host topology with live karma annotations.

Topology:
  h1-h4 (CUBIC/BBR/Vegas/Illinois) → S1 (Access)
  h5-h8 (CUBIC/BBR/Vegas/Illinois) → S2 (Access)
  S1 ↔ S3, S1 ↔ S4  (backbone)
  S2 ↔ S3, S2 ↔ S4  (backbone)
  S3 → h9, h10 (Servers)
  S4 → h11, h12 (Servers)

Usage (requires X11 display or run on VM desktop):
  python3 dashboard/nx_visualizer.py
"""

import matplotlib
matplotlib.use('TkAgg')  # Use Tk backend for desktop GUI
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import subprocess
import sys
from matplotlib.animation import FuncAnimation

# ─── Topology Definition ─────────────────────────────────────────────────────

# Node positions (x, y) — laid out as a tree
NODES = {
    # Left side: S1 hosts (senders)
    'h1':  (0.0,  0.95),
    'h2':  (0.0,  0.75),
    'h3':  (0.0,  0.55),
    'h4':  (0.0,  0.35),
    # Left side: S2 hosts (senders)
    'h5':  (0.0,  0.15),
    'h6':  (0.0, -0.05),
    'h7':  (0.0, -0.25),
    'h8':  (0.0, -0.45),
    # Access switches
    'S1':  (0.35, 0.65),
    'S2':  (0.35, -0.15),
    # Aggregation switches
    'S3':  (0.65, 0.65),
    'S4':  (0.65, -0.15),
    # Right side: servers
    'h9':  (1.0,  0.85),
    'h10': (1.0,  0.50),
    'h11': (1.0,  0.05),
    'h12': (1.0, -0.35),
}

# Physical links
EDGES = [
    # S1 hosts
    ('h1', 'S1'), ('h2', 'S1'), ('h3', 'S1'), ('h4', 'S1'),
    # S2 hosts
    ('h5', 'S2'), ('h6', 'S2'), ('h7', 'S2'), ('h8', 'S2'),
    # Backbone
    ('S1', 'S3'), ('S1', 'S4'), ('S2', 'S3'), ('S2', 'S4'),
    # Servers
    ('S3', 'h9'), ('S3', 'h10'), ('S4', 'h11'), ('S4', 'h12'),
]

# Flow paths (flow_id → list of nodes in path)
FLOW_PATHS = {
    1: ['h1',  'S1', 'S3', 'h9'],    # CUBIC  → h9
    2: ['h2',  'S1', 'S3', 'h9'],    # BBR    → h9
    3: ['h3',  'S1', 'S3', 'h9'],    # Vegas  → h9
    4: ['h4',  'S1', 'S3', 'h9'],    # Illinois→ h9
    5: ['h5',  'S2', 'S3', 'h9'],    # CUBIC  → h9
    6: ['h6',  'S2', 'S3', 'h9'],    # BBR    → h9
    7: ['h7',  'S2', 'S3', 'h9'],    # Vegas  → h9
    8: ['h8',  'S2', 'S3', 'h9'],    # Illinois→ h9
}

FLOW_NAMES = {
    1: 'CUBIC', 2: 'BBR', 3: 'Vegas', 4: 'Illinois',
    5: 'CUBIC', 6: 'BBR', 7: 'Vegas', 8: 'Illinois',
}

FLOW_COLORS = {
    1: '#ff1744',   # red
    2: '#ff6d00',   # orange
    3: '#00e676',   # green
    4: '#b388ff',   # purple
    5: '#00e5ff',   # cyan
    6: '#ffea00',   # yellow
    7: '#76ff03',   # lime
    8: '#e040fb',   # pink
}

# Switch thrift ports for each flow_id
FLOW_SWITCH = {
    1: 9090, 2: 9090, 3: 9090, 4: 9090,
    5: 9091, 6: 9091, 7: 9091, 8: 9091,
}


def read_karma(thrift_port, fid):
    """Read karma register from BMv2 switch."""
    try:
        cmd = f"echo 'register_read MyIngress.reg_karma {fid}' | simple_switch_CLI --thrift-port {thrift_port} 2>/dev/null"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2)
        for line in result.stdout.split('\n'):
            if '=' in line and 'reg_karma' in line:
                val = line.split('=')[-1].strip()
                if val.isdigit():
                    return int(val)
    except Exception:
        pass
    return -1  # unknown


def karma_to_color_name(karma):
    if karma < 0:
        return 'UNKNOWN', '#888888'
    elif karma >= 76:
        return 'GREEN', '#00e676'
    elif karma >= 41:
        return 'YELLOW', '#ffab00'
    else:
        return 'RED', '#ff1744'


def update(frame):
    ax.clear()
    ax.set_facecolor('#1a1a2e')
    fig.patch.set_facecolor('#0f0f23')

    G = nx.Graph()
    G.add_nodes_from(NODES.keys())
    G.add_edges_from(EDGES)

    # Draw base links (grey)
    nx.draw_networkx_edges(G, pos=NODES, ax=ax, edge_color='#333355',
                           width=1.5, alpha=0.5)

    # Draw switches
    switch_nodes = [n for n in G.nodes() if n.startswith('S')]
    nx.draw_networkx_nodes(G, pos=NODES, nodelist=switch_nodes, ax=ax,
                           node_color='#16213e', node_size=1200,
                           edgecolors='#00e5ff', linewidths=2, node_shape='s')
    nx.draw_networkx_labels(G, pos=NODES, labels={n: n for n in switch_nodes},
                            ax=ax, font_color='#00e5ff', font_size=11, font_weight='bold')

    # Draw server nodes
    server_nodes = ['h9', 'h10', 'h11', 'h12']
    nx.draw_networkx_nodes(G, pos=NODES, nodelist=server_nodes, ax=ax,
                           node_color='#1b5e20', node_size=700,
                           edgecolors='#66bb6a', linewidths=2)
    nx.draw_networkx_labels(G, pos=NODES, labels={n: n for n in server_nodes},
                            ax=ax, font_color='#a5d6a7', font_size=9, font_weight='bold')

    # Read karma for all flows and draw sender nodes + flow arrows
    legend_patches = []
    for fid in sorted(FLOW_PATHS.keys()):
        path = FLOW_PATHS[fid]
        host = path[0]
        port = FLOW_SWITCH[fid]
        karma = read_karma(port, fid)
        zone, zone_color = karma_to_color_name(karma)
        color = FLOW_COLORS[fid]

        # Draw sender node with karma-based border
        nx.draw_networkx_nodes(G, pos=NODES, nodelist=[host], ax=ax,
                               node_color=color, node_size=600,
                               edgecolors=zone_color, linewidths=3, alpha=0.9)

        # Label with host name + CCA
        label = f"{host}\n{FLOW_NAMES[fid]}"
        x, y = NODES[host]
        ax.text(x - 0.06, y, label, fontsize=7, color='white',
                ha='right', va='center', fontweight='bold')

        # Draw flow path as colored arrow
        path_edges = list(zip(path, path[1:]))
        H = nx.DiGraph(path_edges)
        rad = 0.05 + 0.04 * (fid - 1)  # offset each flow slightly
        nx.draw_networkx_edges(H, pos=NODES, ax=ax, edgelist=path_edges,
                               edge_color=color, width=1.8, alpha=0.7,
                               connectionstyle=f'arc3,rad={rad}',
                               arrows=True, arrowsize=12)

        # Build legend entry
        karma_str = f"{karma}" if karma >= 0 else "?"
        legend_patches.append(
            mpatches.Patch(color=color, label=f"F{fid} {FLOW_NAMES[fid]} K={karma_str} [{zone}]")
        )

    ax.legend(handles=legend_patches, loc='lower left', fontsize=7,
              facecolor='#16213e', edgecolor='#333355', labelcolor='white',
              ncol=2, framealpha=0.9)

    ax.set_title("KBCS v2 — Live Network Topology", fontsize=14,
                 color='#00e5ff', fontweight='bold', pad=15)
    ax.axis('off')
    ax.set_xlim(-0.15, 1.15)
    ax.set_ylim(-0.6, 1.1)


# ─── Main ─────────────────────────────────────────────────────────────────────

fig, ax = plt.subplots(figsize=(12, 8))
fig.canvas.manager.set_window_title('KBCS v2 — Live Topology Visualizer')

ani = FuncAnimation(fig, update, interval=3000, cache_frame_data=False)
plt.tight_layout()
plt.show()
