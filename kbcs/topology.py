#!/usr/bin/env python3
"""
topology.py — KBCS Multi-Switch Dumbbell Topology
==================================================
Topology layout (4 switches):

    h1 (CUBIC) ─── s1 ──┐
    h2 (BBR)   ─── s2 ──┤─── s3 ─── s4 ─── h3 (Receiver)
    h4 (Vegas) ─── s1 ──┘            │
    h5 (Illinois) ─ s2 ───────────── ┘

Concretely:
  ┌─────────────────────────────────────────────────────────┐
  │ Access layer: s1 (left), s2 (right)                     │
  │ Core layer:   s3 (aggregation), s4 (bottleneck egress)  │
  │ Bottleneck:   s4 ─── h3  @10 Mbps, 5ms               │
  └─────────────────────────────────────────────────────────┘

This extends the original single-switch design with:
  - 4 P4-enabled switches all running kbcs.p4
  - Two classes of senders on separate access switches
  - A shared bottleneck that forces CCA competition

KBCS runs on every switch so karma is maintained across hops.

Usage (inside Ubuntu VM):
    sudo PYTHONPATH=$PYTHONPATH:utils python3 topology.py \\
        --behavioral-exe simple_switch                    \\
        --json build/kbcs.json                            \\
        --traffic --duration 30 --priority-queues 4
"""

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.log import setLogLevel, info
from mininet.cli import CLI
from mininet.link import TCLink
import argparse
from time import sleep
import os
import json
import threading

import sys
sys.path.append('utils')
from p4_mininet import P4Switch, P4Host


# ================================================================== #
# P4Switch subclass that enables priority queues                       #
# ================================================================== #
class KBCSSwitch(P4Switch):
    """P4Switch that passes --priority-queues N to simple_switch."""
    def __init__(self, name, priority_queues=4, **kwargs):
        P4Switch.__init__(self, name, **kwargs)
        self.priority_queues = priority_queues

    def start(self, controllers):
        if self.priority_queues > 0:
            original = self.sw_path
            self.sw_path = f'{self.sw_path} --priority-queues {self.priority_queues}'
            P4Switch.start(self, controllers)
            self.sw_path = original
        else:
            P4Switch.start(self, controllers)


# ================================================================== #
# 4-Switch Dumbbell Topology                                           #
# ================================================================== #
class KBCSDumbbellTopo(Topo):
    """
    Four-switch dumbbell topology:
      Senders → s1/s2 → s3 → s4 → Receiver
      s1: access switch for h1 (CUBIC), h4 (Vegas)
      s2: access switch for h2 (BBR),   h5 (Illinois)
      s3: aggregation switch (core)
      s4: egress switch with the 10-Mbps bottleneck link to h3
    """

    def __init__(self, sw_path, json_path, priority_queues=4, **opts):
        Topo.__init__(self, **opts)

        def make_switch(name, thrift_port):
            return self.addSwitch(
                name,
                sw_path=sw_path,
                json_path=json_path,
                thrift_port=thrift_port,
                priority_queues=priority_queues,
                cls=KBCSSwitch
            )

        # Four switches
        s1 = make_switch('s1', 9090)   # left access
        s2 = make_switch('s2', 9091)   # right access
        s3 = make_switch('s3', 9092)   # core aggregation
        s4 = make_switch('s4', 9093)   # bottleneck egress

        # Inter-switch links (high speed, no shaping)
        self.addLink(s1, s3, cls=TCLink, bw=100)
        self.addLink(s2, s3, cls=TCLink, bw=100)
        self.addLink(s3, s4, cls=TCLink, bw=100)

        # Sender hosts — s1 (CUBIC & Vegas)
        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:01:01')
        h4 = self.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:04:04')
        self.addLink(h1, s1, cls=TCLink, bw=100)
        self.addLink(h4, s1, cls=TCLink, bw=100)

        # Sender hosts — s2 (BBR & Illinois)
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:02:02')
        h5 = self.addHost('h5', ip='10.0.0.5/24', mac='00:00:00:00:05:05')
        self.addLink(h2, s2, cls=TCLink, bw=100)
        self.addLink(h5, s2, cls=TCLink, bw=100)

        # Receiver — s4 bottleneck (10 Mbps, 5 ms delay)
        h3 = self.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:03:03')
        self.addLink(h3, s4, cls=TCLink, bw=10, delay='5ms',
                     max_queue_size=200)


# ================================================================== #
# Host Configuration                                                   #
# ================================================================== #
def configure_hosts(net):
    """Disable IPv6, set ARP and CCA for each host."""
    hosts = [net.get(h) for h in ('h1', 'h2', 'h3', 'h4', 'h5')]

    for h in hosts:
        h.cmd('sysctl -w net.ipv6.conf.all.disable_ipv6=1')
        h.cmd('sysctl -w net.ipv6.conf.default.disable_ipv6=1')
        h.cmd('sysctl -w net.ipv6.conf.lo.disable_ipv6=1')

    h1, h2, h3, h4, h5 = hosts

    # ARP pre-population for all pairs
    for src in hosts:
        for dst in hosts:
            if src != dst:
                dst_ip  = dst.IP()
                dst_mac = dst.MAC()
                src.cmd(f'arp -s {dst_ip} {dst_mac}')

    # CCA assignment
    h1.cmd('sysctl -w net.ipv4.tcp_congestion_control=cubic')
    h2.cmd('modprobe tcp_bbr 2>/dev/null; '
           'sysctl -w net.ipv4.tcp_congestion_control=bbr')
    h4.cmd('sysctl -w net.ipv4.tcp_congestion_control=vegas')
    h5.cmd('sysctl -w net.ipv4.tcp_congestion_control=illinois 2>/dev/null || '
           'sysctl -w net.ipv4.tcp_congestion_control=cubic')
    # h3 is receiver; CCA irrelevant but set for consistency
    h3.cmd('sysctl -w net.ipv4.tcp_congestion_control=reno')

    info('*** Congestion Controls assigned:\n')
    for name, h in [('h1 CUBIC', h1), ('h2 BBR', h2),
                    ('h4 Vegas', h4), ('h5 Illinois', h5)]:
        cc = h.cmd('sysctl net.ipv4.tcp_congestion_control').strip()
        info(f'    {name}: {cc}\n')

    return h1, h2, h3, h4, h5


# ================================================================== #
# Forwarding rule installation                                         #
# ================================================================== #
def install_forwarding_rules(switch_thrift_map: dict):
    """
    Install L3 forwarding rules on each switch.

    switch_thrift_map: {switch_name: (thrift_port, {ip: (mac, port)})}
    """
    info('*** Installing forwarding rules...\n')
    for sw_name, (thrift_port, fwd_table) in switch_thrift_map.items():
        for ip, (mac, port) in fwd_table.items():
            cmd = (f'echo "table_add MyIngress.ipv4_lpm '
                   f'MyIngress.ipv4_forward {ip}/32 => {mac} {port}" | '
                   f'simple_switch_CLI --thrift-port {thrift_port}')
            os.system(cmd)
    info('*** Forwarding rules installed.\n')


def build_forwarding_tables(net):
    """
    Build per-switch forwarding tables for the 4-switch dumbbell.
    Every switch needs routes to all 5 hosts.
    """
    # Port assignments (set by link order in topology constructor)
    # s1 ports:  1=h1, 2=h4, 3=s3
    # s2 ports:  1=h2, 2=h5, 3=s3
    # s3 ports:  1=s1, 2=s2, 3=s4
    # s4 ports:  1=s3, 2=h3

    s1_fwd = {
        '10.0.0.1': ('00:00:00:00:01:01', 1),  # h1 directly
        '10.0.0.4': ('00:00:00:00:04:04', 2),  # h4 directly
        '10.0.0.2': ('00:00:00:00:02:02', 3),  # h2 via s3
        '10.0.0.5': ('00:00:00:00:05:05', 3),  # h5 via s3
        '10.0.0.3': ('00:00:00:00:03:03', 3),  # h3 via s3
    }
    s2_fwd = {
        '10.0.0.2': ('00:00:00:00:02:02', 1),  # h2 directly
        '10.0.0.5': ('00:00:00:00:05:05', 2),  # h5 directly
        '10.0.0.1': ('00:00:00:00:01:01', 3),  # h1 via s3
        '10.0.0.4': ('00:00:00:00:04:04', 3),  # h4 via s3
        '10.0.0.3': ('00:00:00:00:03:03', 3),  # h3 via s3
    }
    s3_fwd = {
        '10.0.0.1': ('00:00:00:00:01:01', 1),  # h1 via s1
        '10.0.0.4': ('00:00:00:00:04:04', 1),  # h4 via s1
        '10.0.0.2': ('00:00:00:00:02:02', 2),  # h2 via s2
        '10.0.0.5': ('00:00:00:00:05:05', 2),  # h5 via s2
        '10.0.0.3': ('00:00:00:00:03:03', 3),  # h3 via s4
    }
    s4_fwd = {
        '10.0.0.3': ('00:00:00:00:03:03', 2),  # h3 directly
        '10.0.0.1': ('00:00:00:00:01:01', 1),  # h1 via s3
        '10.0.0.2': ('00:00:00:00:02:02', 1),  # h2 via s3
        '10.0.0.4': ('00:00:00:00:04:04', 1),  # h4 via s3
        '10.0.0.5': ('00:00:00:00:05:05', 1),  # h5 via s3
    }

    return {
        's1': (9090, s1_fwd),
        's2': (9091, s2_fwd),
        's3': (9092, s3_fwd),
        's4': (9093, s4_fwd),
    }


# ================================================================== #
# Traffic test (4 senders → h3)                                        #
# ================================================================== #
def run_iperf_test(net, duration=30):
    """
    Run iperf3 from h1(CUBIC), h2(BBR), h4(Vegas), h5(Illinois) to h3.
    Returns dict with per-flow throughput, retransmits, and Jain FI.
    """
    h1 = net.get('h1')
    h2 = net.get('h2')
    h3 = net.get('h3')
    h4 = net.get('h4')
    h5 = net.get('h5')

    result_files = {
        'h1': '/tmp/kbcs_h1_cubic.json',
        'h2': '/tmp/kbcs_h2_bbr.json',
        'h4': '/tmp/kbcs_h4_vegas.json',
        'h5': '/tmp/kbcs_h5_illinois.json',
    }
    ports = {'h1': 5201, 'h2': 5202, 'h4': 5204, 'h5': 5205}

    # Remove stale files
    for f in result_files.values():
        os.system(f'rm -f {f}')

    info(f'\n*** Starting 4-flow iperf3 test (duration={duration}s)\n')
    info(f'    h1(CUBIC), h2(BBR), h4(Vegas), h5(Illinois) → h3\n')
    info(f'    Bottleneck: 10 Mbps @ s4 → h3\n\n')

    # Start servers on h3
    h3.cmd('killall iperf3 2>/dev/null; sleep 0.5')
    for p in ports.values():
        h3.cmd(f'iperf3 -s -p {p} -D')
    sleep(2)

    # Launch clients simultaneously
    info('*** Starting all clients simultaneously...\n')
    h1.sendCmd(f'iperf3 -c 10.0.0.3 -p {ports["h1"]} -t {duration} -J > {result_files["h1"]} 2>&1')
    h2.sendCmd(f'iperf3 -c 10.0.0.3 -p {ports["h2"]} -t {duration} -J > {result_files["h2"]} 2>&1')
    h4.sendCmd(f'iperf3 -c 10.0.0.3 -p {ports["h4"]} -t {duration} -J > {result_files["h4"]} 2>&1')
    h5.sendCmd(f'iperf3 -c 10.0.0.3 -p {ports["h5"]} -t {duration} -J > {result_files["h5"]} 2>&1')

    info(f'*** Waiting {duration + 5}s for tests to complete...\n')
    sleep(duration + 5)

    # Collect outputs
    for h in [h1, h2, h4, h5]:
        try:
            h.waitOutput(verbose=False)
        except Exception:
            pass
    sleep(1)

    # Parse results
    info('\n*** ===== TRAFFIC TEST RESULTS =====\n')
    throughputs = {}
    cca_labels  = {'h1': 'CUBIC', 'h2': 'BBR', 'h4': 'Vegas', 'h5': 'Illinois'}

    for hname, fpath in result_files.items():
        label = cca_labels[hname]
        try:
            with open(fpath) as f:
                data = json.load(f)
            if 'error' in data:
                info(f'    {label}: iperf3 error → {data["error"]}\n')
                continue
            mbps  = data['end']['sum_sent']['bits_per_second'] / 1e6
            retx  = data['end']['sum_sent'].get('retransmits', 'N/A')
            info(f'    {label}: {mbps:.2f} Mbps (retransmits: {retx})\n')
            throughputs[hname] = {'mbps': round(mbps, 2), 'retransmits': retx, 'cca': label}
        except FileNotFoundError:
            info(f'    {label}: result file missing\n')
        except Exception as e:
            info(f'    {label}: parse error — {e}\n')

    # Jain's Fairness Index over all measured flows
    values = [v['mbps'] for v in throughputs.values() if v['mbps'] > 0]
    if len(values) >= 2:
        n = len(values)
        jain = (sum(values) ** 2) / (n * sum(x**2 for x in values))
        total = sum(values)
        info(f"\n    Total Throughput : {total:.2f} Mbps\n")
        info(f"    Jain's FI        : {jain:.4f}  "
             f"(1.0=perfect, {1/n:.2f}=max unfair)\n")
    else:
        jain  = 0
        total = 0
        info('\n    ERROR: Insufficient throughput data.\n')

    # Save to results/
    os.makedirs('results', exist_ok=True)
    summary = {
        'topology': 'dumbbell_4sw',
        'duration': duration,
        'flows': throughputs,
        'total_mbps': round(total, 2),
        'jain_index': round(jain, 4),
    }
    with open('results/last_test.json', 'w') as f:
        json.dump(summary, f, indent=2)

    info('\n*** ===== TEST COMPLETE =====\n')
    h3.cmd('killall iperf3 2>/dev/null')
    return summary


# ================================================================== #
# Main                                                                  #
# ================================================================== #
def main():
    parser = argparse.ArgumentParser(
        description='KBCS 4-Switch Dumbbell Topology')
    parser.add_argument('--behavioral-exe', required=True,
                        help='Path to simple_switch binary')
    parser.add_argument('--json', required=True,
                        help='Compiled P4 JSON file')
    parser.add_argument('--test-only', action='store_true',
                        help='Run pingall only and exit')
    parser.add_argument('--traffic', action='store_true',
                        help='Run 4-flow iperf3 traffic test')
    parser.add_argument('--duration', type=int, default=30,
                        help='Traffic test duration in seconds (default: 30)')
    parser.add_argument('--priority-queues', type=int, default=4,
                        help='Number of BMv2 priority queues (default: 4)')
    parser.add_argument('--controller', action='store_true',
                        help='Enable the KBCS dynamic controller in background')
    args = parser.parse_args()

    pq = args.priority_queues
    info(f'*** Priority queues: {pq if pq > 0 else "DISABLED (FIFO)"}\n')

    topo = KBCSDumbbellTopo(
        sw_path=args.behavioral_exe,
        json_path=args.json,
        priority_queues=pq
    )
    net = Mininet(topo=topo, host=P4Host, switch=KBCSSwitch,
                  controller=None, link=TCLink)
    net.start()

    configure_hosts(net)
    fwd_tables = build_forwarding_tables(net)
    install_forwarding_rules(fwd_tables)
    sleep(1)

    # Optionally start the adaptive control plane [E1]
    ctrl_thread = None
    if args.controller:
        try:
            from kbcs_controller import KBCSController
            # Start one controller per switch (they share the register space)
            ctrl = KBCSController(thrift_port=9090, interval=2, verbose=False)
            ctrl_thread = ctrl.start_background()
            info('*** KBCS Controller started in background\n')
        except ImportError:
            info('*** kbcs_controller.py not found — skipping controller\n')

    if args.test_only:
        info('*** Running pingall test...\n')
        net.pingAll()
    elif args.traffic:
        info('*** Quick connectivity check...\n')
        net.pingAll()
        run_iperf_test(net, duration=args.duration)
    else:
        CLI(net)

    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    main()
