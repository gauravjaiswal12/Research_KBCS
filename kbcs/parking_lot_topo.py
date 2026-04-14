#!/usr/bin/env python3
"""
parking_lot_topo.py — KBCS Parking Lot Topology (4 Switches)
=============================================================
                                                               
  h1 (long-lived CUBIC) ──── s1 ─── s2 ─── s3 ─── s4 ──── h_dest
                              │      │      │      │
                           h_n1   h_n2   h_n3   h_n4
                        (CUBIC) (BBR) (Vegas) (Illinois)
                                                               
The "parking lot" pattern models a long-lived, multi-hop flow
competing with shortcut cross-traffic injected at EVERY switch.

Each cross-traffic sender (h_n1..h_n4) sends directly to h_dest,
so the cross-traffic accumulates across hops and increasingly
crowds out the long flow — unless KBCS correctly identifies and
throttles the aggressive CUBIC cross-traffic.

Bottleneck: s4 → h_dest = 10 Mbps, 5 ms delay.
Other links: 100 Mbps.

Usage:
    sudo PYTHONPATH=$PYTHONPATH:utils python3 parking_lot_topo.py \\
        --behavioral-exe simple_switch                             \\
        --json build/kbcs.json                                     \\
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

import sys
sys.path.append('utils')
from p4_mininet import P4Switch, P4Host


# ================================================================== #
# P4Switch subclass (same as topology.py)                              #
# ================================================================== #
class KBCSSwitch(P4Switch):
    """P4Switch with --priority-queues injection."""
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
# Parking Lot Topology                                                  #
# ================================================================== #
class ParkingLotTopo(Topo):
    """4-switch linear (parking lot) topology."""

    def __init__(self, sw_path, json_path, priority_queues=4, **opts):
        Topo.__init__(self, **opts)

        # Create 4 inline switches
        switches = []
        for i in range(1, 5):
            sw = self.addSwitch(
                f's{i}',
                sw_path=sw_path,
                json_path=json_path,
                thrift_port=9090 + i,
                priority_queues=priority_queues,
                cls=KBCSSwitch
            )
            switches.append(sw)

        # Chain switches s1 → s2 → s3 → s4
        for i in range(len(switches) - 1):
            self.addLink(switches[i], switches[i + 1], cls=TCLink, bw=100)

        # Long-haul sender h1 — enters at s1, exits at s4 → h_dest
        h1 = self.addHost('h1', ip='10.0.1.1/24', mac='00:00:00:01:01:01')
        self.addLink(h1, switches[0], cls=TCLink, bw=100)

        # Receiver h_dest — attached to s4 with bandwidth bottleneck
        h_dest = self.addHost('h_dest', ip='10.0.1.99/24', mac='00:00:00:01:09:99')
        self.addLink(h_dest, switches[3], cls=TCLink, bw=10, delay='5ms',
                     max_queue_size=200)

        # Cross-traffic senders — one per switch, injecting into h_dest
        # h_n1: CUBIC (aggressive, tests AQM); attached to s1
        # h_n2: BBR (model-based);              attached to s2
        # h_n3: Vegas (delay-based, victim);    attached to s3
        # h_n4: Illinois (hybrid);              attached to s4
        cross_hosts = [
            ('h_n1', '10.0.1.11/24', '00:00:00:01:02:01'),  # s1, CUBIC
            ('h_n2', '10.0.1.12/24', '00:00:00:01:02:02'),  # s2, BBR
            ('h_n3', '10.0.1.13/24', '00:00:00:01:02:03'),  # s3, Vegas
            ('h_n4', '10.0.1.14/24', '00:00:00:01:02:04'),  # s4, Illinois
        ]
        for idx, (name, ip, mac) in enumerate(cross_hosts):
            h = self.addHost(name, ip=ip, mac=mac)
            self.addLink(h, switches[idx], cls=TCLink, bw=100)


# ================================================================== #
# Host configuration                                                   #
# ================================================================== #
def configure_hosts(net):
    """Disable IPv6, pre-populate ARP, assign CCAs."""
    all_hosts = [net.get(n) for n in ('h1', 'h_dest', 'h_n1', 'h_n2', 'h_n3', 'h_n4')]

    for h in all_hosts:
        h.cmd('sysctl -w net.ipv6.conf.all.disable_ipv6=1')
        h.cmd('sysctl -w net.ipv6.conf.default.disable_ipv6=1')
        h.cmd('sysctl -w net.ipv6.conf.lo.disable_ipv6=1')

    # ARP pre-population
    for src in all_hosts:
        for dst in all_hosts:
            if src is not dst:
                src.cmd(f'arp -s {dst.IP()} {dst.MAC()}')

    # CCA assignment
    net.get('h1'   ).cmd('sysctl -w net.ipv4.tcp_congestion_control=cubic')
    net.get('h_n1' ).cmd('sysctl -w net.ipv4.tcp_congestion_control=cubic')
    net.get('h_n2' ).cmd('modprobe tcp_bbr 2>/dev/null; '
                          'sysctl -w net.ipv4.tcp_congestion_control=bbr')
    net.get('h_n3' ).cmd('sysctl -w net.ipv4.tcp_congestion_control=vegas')
    net.get('h_n4' ).cmd('sysctl -w net.ipv4.tcp_congestion_control=illinois 2>/dev/null || '
                          'sysctl -w net.ipv4.tcp_congestion_control=cubic')

    info('*** CCA assignment: h1=CUBIC, h_n1=CUBIC, h_n2=BBR, '
         'h_n3=Vegas, h_n4=Illinois\n')


# ================================================================== #
# Forwarding rule installation                                          #
# ================================================================== #
def install_forwarding_rules():
    """
    Push L3 forwarding entries onto each switch.

    Routing logic:
      All traffic ultimately goes to h_dest (10.0.1.99) out the
      downstream port, and replies go upstream.
    """
    info('*** Installing parking-lot forwarding rules...\n')

    # Switch port assignments (order determined by topology addLink calls):
    # s1 ports: 1=s2, 2=h1, 3=h_n1
    # s2 ports: 1=s1, 2=s3, 3=h_n2
    # s3 ports: 1=s2, 2=s4, 3=h_n3
    # s4 ports: 1=s3, 2=h_dest, 3=h_n4

    # For each switch, rules to reach h1, h_dest, and all cross hosts
    rules = {
        's1': (9091, {
            '10.0.1.1':   ('00:00:00:01:01:01', 2),   # h1 directly
            '10.0.1.11':  ('00:00:00:01:02:01', 3),   # h_n1 directly
            '10.0.1.99':  ('00:00:00:01:09:99', 1),   # h_dest via s2→s3→s4
            '10.0.1.12':  ('00:00:00:01:02:02', 1),   # h_n2 via s2
            '10.0.1.13':  ('00:00:00:01:02:03', 1),   # h_n3 via s2→s3
            '10.0.1.14':  ('00:00:00:01:02:04', 1),   # h_n4 via s2→s3→s4
        }),
        's2': (9092, {
            '10.0.1.12':  ('00:00:00:01:02:02', 3),   # h_n2 directly
            '10.0.1.1':   ('00:00:00:01:01:01', 1),   # h1 via s1
            '10.0.1.11':  ('00:00:00:01:02:01', 1),   # h_n1 via s1
            '10.0.1.99':  ('00:00:00:01:09:99', 2),   # h_dest via s3→s4
            '10.0.1.13':  ('00:00:00:01:02:03', 2),   # h_n3 via s3
            '10.0.1.14':  ('00:00:00:01:02:04', 2),   # h_n4 via s3→s4
        }),
        's3': (9093, {
            '10.0.1.13':  ('00:00:00:01:02:03', 3),   # h_n3 directly
            '10.0.1.1':   ('00:00:00:01:01:01', 1),   # h1 via s2→s1
            '10.0.1.11':  ('00:00:00:01:02:01', 1),   # h_n1 via s2→s1
            '10.0.1.12':  ('00:00:00:01:02:02', 1),   # h_n2 via s2
            '10.0.1.99':  ('00:00:00:01:09:99', 2),   # h_dest via s4
            '10.0.1.14':  ('00:00:00:01:02:04', 2),   # h_n4 via s4
        }),
        's4': (9094, {
            '10.0.1.99':  ('00:00:00:01:09:99', 2),   # h_dest directly
            '10.0.1.14':  ('00:00:00:01:02:04', 3),   # h_n4 directly
            '10.0.1.1':   ('00:00:00:01:01:01', 1),   # h1 via s3→s2→s1
            '10.0.1.11':  ('00:00:00:01:02:01', 1),   # h_n1 via s3→s2→s1
            '10.0.1.12':  ('00:00:00:01:02:02', 1),   # h_n2 via s3→s2
            '10.0.1.13':  ('00:00:00:01:02:03', 1),   # h_n3 via s3
        }),
    }

    for sw, (thrift_port, fwd) in rules.items():
        for ip, (mac, port) in fwd.items():
            cmd = (f'echo "table_add MyIngress.ipv4_lpm '
                   f'MyIngress.ipv4_forward {ip}/32 => {mac} {port}" | '
                   f'simple_switch_CLI --thrift-port {thrift_port}')
            os.system(cmd)

    info('*** Forwarding rules installed on s1-s4.\n')


# ================================================================== #
# Traffic test                                                          #
# ================================================================== #
def run_iperf_test(net, duration=30):
    """
    Run iperf3 from h1 (long flow) and h_n1..h_n4 (cross traffic) to h_dest.
    Returns dict with per-flow metrics and Jain FI.
    """
    h_dest = net.get('h_dest')
    senders = {
        'h1':    (net.get('h1'),   5201, 'CUBIC (long)'),
        'h_n1':  (net.get('h_n1'), 5211, 'CUBIC cross@s1'),
        'h_n2':  (net.get('h_n2'), 5212, 'BBR   cross@s2'),
        'h_n3':  (net.get('h_n3'), 5213, 'Vegas cross@s3'),
        'h_n4':  (net.get('h_n4'), 5214, 'Illi. cross@s4'),
    }
    result_files = {k: f'/tmp/pl_{k}.json' for k in senders}

    for f in result_files.values():
        os.system(f'rm -f {f}')

    info(f'\n*** Parking-lot traffic test — duration={duration}s\n')

    # Start servers
    h_dest.cmd('killall iperf3 2>/dev/null; sleep 0.5')
    for hname, (_, port, _) in senders.items():
        h_dest.cmd(f'iperf3 -s -p {port} -D')
    sleep(2)

    # Launch all clients
    info('*** Launching all senders simultaneously...\n')
    for hname, (h, port, label) in senders.items():
        h.sendCmd(f'iperf3 -c 10.0.1.99 -p {port} -t {duration} -J '
                  f'> {result_files[hname]} 2>&1')

    sleep(duration + 5)
    for _, (h, _, _) in senders.items():
        try:
            h.waitOutput(verbose=False)
        except Exception:
            pass
    sleep(1)

    # Parse
    info('\n*** ===== PARKING LOT TEST RESULTS =====\n')
    throughputs = {}
    for hname, (_, _, label) in senders.items():
        try:
            with open(result_files[hname]) as f:
                data = json.load(f)
            if 'error' in data:
                info(f'    {label}: {data["error"]}\n')
                continue
            mbps = data['end']['sum_sent']['bits_per_second'] / 1e6
            retx = data['end']['sum_sent'].get('retransmits', 'N/A')
            info(f'    {label}: {mbps:.2f} Mbps (retxmits={retx})\n')
            throughputs[hname] = {'mbps': round(mbps, 2), 'label': label, 'retransmits': retx}
        except Exception as e:
            info(f'    {label}: parse error — {e}\n')

    values = [v['mbps'] for v in throughputs.values() if v['mbps'] > 0]
    if len(values) >= 2:
        n    = len(values)
        jain = (sum(values)**2) / (n * sum(x**2 for x in values))
        total = sum(values)
        info(f'\n    Total: {total:.2f} Mbps | Jain FI: {jain:.4f}\n')
    else:
        jain, total = 0, 0

    # Check how much the long flow (h1) gets vs. the cross traffic
    h1_mbps   = throughputs.get('h1', {}).get('mbps', 0)
    cross_mbps = sum(throughputs.get(k, {}).get('mbps', 0)
                     for k in ('h_n1', 'h_n2', 'h_n3', 'h_n4'))
    info(f'    Long-flow h1 : {h1_mbps:.2f} Mbps\n')
    info(f'    Cross-traffic: {cross_mbps:.2f} Mbps total\n')

    os.makedirs('results', exist_ok=True)
    summary = {
        'topology'  : 'parking_lot_4sw',
        'duration'  : duration,
        'flows'     : throughputs,
        'total_mbps': round(total, 2),
        'jain_index': round(jain, 4),
        'h1_mbps'   : h1_mbps,
        'cross_mbps': round(cross_mbps, 2),
    }
    with open('results/parking_lot_test.json', 'w') as f:
        json.dump(summary, f, indent=2)

    info('\n*** ===== PARKING LOT TEST COMPLETE =====\n')
    h_dest.cmd('killall iperf3 2>/dev/null')
    return summary


# ================================================================== #
# Main                                                                  #
# ================================================================== #
def main():
    parser = argparse.ArgumentParser(
        description='KBCS 4-Switch Parking Lot Topology')
    parser.add_argument('--behavioral-exe', required=True,
                        help='Path to simple_switch binary')
    parser.add_argument('--json', required=True,
                        help='Compiled P4 JSON file')
    parser.add_argument('--test-only', action='store_true',
                        help='Pingall and exit')
    parser.add_argument('--traffic', action='store_true',
                        help='Run iperf3 parking-lot traffic test')
    parser.add_argument('--duration', type=int, default=30,
                        help='Duration per test in seconds (default: 30)')
    parser.add_argument('--priority-queues', type=int, default=4,
                        help='Number of BMv2 priority queues (default: 4)')
    args = parser.parse_args()

    pq = args.priority_queues
    info(f'*** Priority queues: {pq if pq > 0 else "DISABLED (FIFO)"}\n')

    topo = ParkingLotTopo(
        sw_path=args.behavioral_exe,
        json_path=args.json,
        priority_queues=pq
    )
    net = Mininet(topo=topo, host=P4Host, switch=KBCSSwitch,
                  controller=None, link=TCLink)
    net.start()

    configure_hosts(net)
    install_forwarding_rules()
    sleep(1)

    if args.test_only:
        info('*** Running pingall...\n')
        net.pingAll()
    elif args.traffic:
        info('*** Connectivity check...\n')
        net.pingAll()
        run_iperf_test(net, duration=args.duration)
    else:
        CLI(net)

    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    main()
