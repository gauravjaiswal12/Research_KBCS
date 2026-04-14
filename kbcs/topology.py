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
import sys

sys.path.append('utils')
from p4_mininet import P4Switch, P4Host

class KBCSSwitch(P4Switch):
    """P4Switch subclass that enables priority queues in simple_switch."""
    def __init__(self, name, priority_queues=3, **kwargs):
        P4Switch.__init__(self, name, **kwargs)
        self.priority_queues = priority_queues

    def start(self, controllers):
        if self.priority_queues > 0:
            original_json_path = self.json_path
            self.json_path = self.json_path + ' -- --priority-queues %d' % self.priority_queues
            P4Switch.start(self, controllers)
            self.json_path = original_json_path
        else:
            P4Switch.start(self, controllers)

class KBCSTopo(Topo):
    def __init__(self, sw_path, json_path, priority_queues=0, num_flows=2, **opts):
        Topo.__init__(self, **opts)
        self.num_flows = num_flows

        switch = self.addSwitch('s1',
                                sw_path=sw_path,
                                json_path=json_path,
                                thrift_port=9090,
                                priority_queues=priority_queues,
                                cls=KBCSSwitch)

        self.senders = []
        for i in range(1, num_flows + 1):
            h = self.addHost('h%d' % i, ip='10.0.0.%d/24' % i, mac='00:00:00:00:%02x:%02x' % (1, i))
            self.senders.append(h)
            self.addLink(h, switch, port2=i, cls=TCLink, bw=100)

        # Server
        server_idx = num_flows + 1
        server = self.addHost('h_server', ip='10.0.0.%d/24' % server_idx, mac='00:00:00:00:03:03')
        # NO RATE LIMIT HERE — let BMv2 handle it natively!
        self.addLink(server, switch, port2=server_idx, cls=TCLink, bw=100, delay='5ms')
        
        # Collector
        coll_idx = num_flows + 2
        collector = self.addHost('collector', ip='10.0.0.%d/24' % coll_idx, mac='00:00:00:00:04:04')
        self.addLink(collector, switch, port2=coll_idx, cls=TCLink, bw=1000)

def configure_hosts(net, num_flows, ccas):
    server_ip = '10.0.0.%d' % (num_flows + 1)
    server_mac = '00:00:00:00:03:03'
    server = net.get('h_server')
    collector = net.get('collector')

    senders = [net.get('h%d' % i) for i in range(1, num_flows + 1)]
    all_hosts = senders + [server, collector]

    for h in all_hosts:
        h.cmd('sysctl -w net.ipv6.conf.all.disable_ipv6=1')
        h.cmd('sysctl -w net.ipv6.conf.default.disable_ipv6=1')
        h.cmd('sysctl -w net.ipv6.conf.lo.disable_ipv6=1')
        h.cmd('sysctl -w net.ipv4.tcp_ecn=1')  # Enable ECN for KBCS-AQM

    # Load ALL needed TCP CCA kernel modules with explicit error checking
    cca_list = [c.strip() for c in ccas.split(',')]
    info("*** Loading CCA kernel modules:\n")
    for cca in set(cca_list):
        # Try loading the module
        result = os.system(f'modprobe tcp_{cca}')
        if result != 0:
            info(f"    Warning: Failed to load tcp_{cca}, trying alternative...\n")
        # Verify it's available
        check = os.popen('cat /proc/sys/net/ipv4/tcp_available_congestion_control').read()
        if cca in check:
            info(f"    tcp_{cca}: loaded successfully\n")
        else:
            info(f"    tcp_{cca}: NOT available\n")

    # Set allowed CCAs globally - use all available ones
    available = os.popen('cat /proc/sys/net/ipv4/tcp_available_congestion_control').read().strip()
    os.system(f'echo "{available}" > /proc/sys/net/ipv4/tcp_allowed_congestion_control')
    info(f"*** Available CCAs: {available}\n")

    info("*** Congestion Control configured:\n")
    for i, h in enumerate(senders):
        cca = cca_list[i % len(cca_list)]
        # Set CCA for this host
        h.cmd(f'sysctl -w net.ipv4.tcp_congestion_control={cca}')
        raw = h.cmd(f'sysctl net.ipv4.tcp_congestion_control')
        actual = raw.strip().split('=')[-1].strip() if '=' in raw else raw.strip()
        h.cmd('arp -s %s %s' % (server_ip, server_mac))
        status = "OK" if actual.lower() == cca.lower() else "FALLBACK"
        info(f"    {h.name} ({cca.upper()}): actual={actual} [{status}]\n")

    server.cmd('sysctl -w net.ipv4.tcp_congestion_control=reno')
    for i, h in enumerate(senders):
        server.cmd('arp -s 10.0.0.%d 00:00:00:00:%02x:%02x' % (i + 1, 1, i + 1))
        
    return senders, server, collector

def install_forwarding_rules(num_flows):
    print("Populating forwarding rules and native BMv2 settings...")
    cmds = []
    
    # Forwarding rules for senders and exact flow IDs for telemetry
    for i in range(1, num_flows + 1):
        cmds.append(f'table_add MyIngress.ipv4_lpm MyIngress.ipv4_forward 10.0.0.{i}/32 => 00:00:00:00:01:{i:02x} {i}')
        cmds.append(f'table_add MyIngress.flow_id_exact MyIngress.set_flow_id 10.0.0.{i} => {i}')
    
    # Forwarding rule for server
    server_idx = num_flows + 1
    cmds.append(f'table_add MyIngress.ipv4_lpm MyIngress.ipv4_forward 10.0.0.{server_idx}/32 => 00:00:00:00:03:03 {server_idx}')
    
    # Mirroring to collector
    coll_idx = num_flows + 2
    cmds.append(f'mirroring_add 4 {coll_idx}')
    
    # TRUE BMv2 BOTTLENECK ENFORCEMENT
    # 833 packets/sec * 1500B = ~10 Mbps limit on server egress port
    cmds.append(f'set_queue_rate 833 {server_idx}')
    # KBCS FIX: Increased buffer from 10 to 16 packets for 2x BDP headroom
    # At 10 Mbps: 16 pkts * 1500B * 8 / 10M = 19ms max queuing delay
    # Provides headroom for BBR probing while still maintaining low latency
    cmds.append(f'set_queue_depth 16 {server_idx}')
    
    # DYNAMIC FAIR_BYTES CALCULATION (updated for 15ms window)
    # 10 Mbps = 1,250,000 bytes/sec. Window = 15ms = 66.67 per sec.
    # fair_bytes = (1,250,000 / 66.67) / num_flows = 18,750 / num_flows
    # KBCS: 1.5x provides balance between differentiation and utilization
    windows_per_sec = 1000 / 15  # 66.67 windows per second
    fair_bytes = int((1250000 / windows_per_sec) / num_flows * 1.5)  # 1.5x balance
    
    # Write to reg_fair_bytes slot 0
    cmds.append(f'register_write reg_fair_bytes 0 {fair_bytes}')
    
    # Execute commands
    for cmd in cmds:
        os.system(f'echo "{cmd}" | simple_switch_CLI --thrift-port 9090 > /dev/null 2>&1')

def run_iperf_test(net, num_flows, ccas, duration=30):
    senders = [net.get('h%d' % i) for i in range(1, num_flows + 1)]
    server = net.get('h_server')
    collector = net.get('collector')
    server_ip = '10.0.0.%d' % (num_flows + 1)
    
    cca_list = [c.strip() for c in ccas.split(',')]
    
    info(f"\n*** Starting iperf3 traffic test (duration={duration}s, flows={num_flows})\n")
    info("    Bottleneck: Native BMv2 queue on server port (10 Mbps)\n\n")

    server.cmd('killall iperf3 2>/dev/null')
    sleep(1)
    
    # Start N servers using bash backgrounding instead of -D to prevent crashes
    for i in range(num_flows):
        server.cmd(f'iperf3 -s -p {6201 + i} > /tmp/iperf_s{i}.log 2>&1 &')
    sleep(2)

    # Start metrics exporter (passing num_flows and CCAs)
    os.system(f'python3 metrics_exporter.py {duration} {num_flows} {ccas} &')
    
    # Start RL Adaptive Fairness Controller
    os.system(f'python3 rl_controller.py {duration} {num_flows} > /tmp/rl.log 2>&1 &')
    
    collector.cmd('killall tcpdump 2>/dev/null')
    collector.cmd('rm -f /tmp/collector.pcap')
    collector.cmd('tcpdump -U -n -i eth0 -w /tmp/collector.pcap &')
    
    info("\n*** Starting clients with synchronized barrier...\n")

    # KBCS FIX: Barrier synchronization to prevent CUBIC first-mover advantage
    sync_file = '/tmp/kbcs_sync'
    os.system(f'rm -f {sync_file}')

    res_files = []
    for i, h in enumerate(senders):
        r_file = f'/tmp/res_h{i+1}.json'
        err_file = f'/tmp/err_h{i+1}.txt'
        os.system(f'rm -f {r_file} {err_file}')
        cca = cca_list[i % len(cca_list)]
        res_files.append((r_file, h.name, cca))
        # Wait for sync file before starting - ensures all flows start together
        cmd = f'while [ ! -f {sync_file} ]; do sleep 0.01; done; ' \
              f'iperf3 -c {server_ip} -p {6201 + i} -t {duration} --congestion {cca} -J > {r_file} 2> {err_file}'
        h.sendCmd(cmd)

    # Wait for all clients to be ready, then trigger synchronized start
    sleep(0.5)
    os.system(f'touch {sync_file}')
    info("    All flows started simultaneously!\n")

    info("*** Waiting for tests to complete...\n")
    sleep(duration + 10)

    for h in senders:
        try:
            h.waitOutput(verbose=False)
        except:
            pass
    sleep(2)

    server.cmd('killall iperf3 2>/dev/null')

    # PARSE RESULTS
    info("\n*** ===== TRAFFIC TEST RESULTS ===== ***\n")
    throughputs = []
    retransmits = []
    
    for r_file, h_name, cca in res_files:
        try:
            with open(r_file, 'r') as f:
                data = json.loads(f.read().strip())
                mbps = data['end']['sum_sent']['bits_per_second'] / 1e6
                retx = data['end']['sum_sent'].get('retransmits', 'N/A')
                throughputs.append(mbps)
                retransmits.append(retx)
                info(f"    {h_name} ({cca.upper()}): {mbps:.2f} Mbps (retransmits: {retx})\n")
        except Exception:
            info(f"    {h_name} ({cca.upper()}): Parse error or empty file\n")
            throughputs.append(0)
            retransmits.append('N/A')

    # JFI
    if sum(throughputs) > 0:
        jain = (sum(throughputs) ** 2) / (len(throughputs) * sum(x**2 for x in throughputs))
        info(f"\n    Jain's Fairness Index: {jain:.4f}\n")
    else:
        jain = 0

    os.makedirs('results', exist_ok=True)
    summary = {
        'num_flows': num_flows,
        'jain_index': round(jain, 4),
        'duration': duration,
        'flows': []
    }
    
    for i in range(num_flows):
        summary['flows'].append({
            'name': res_files[i][1],
            'cca': res_files[i][2],
            'mbps': round(throughputs[i], 2),
            'retransmits': retransmits[i]
        })
        
    # Legacy compat for old scripts
    if num_flows >= 2:
        summary['cubic_mbps'] = round(throughputs[0], 2)
        summary['bbr_mbps'] = round(throughputs[1], 2)
        summary['cubic_retransmits'] = retransmits[0]
        summary['bbr_retransmits'] = retransmits[1]

    with open('results/last_test.json', 'w') as f:
        json.dump(summary, f, indent=2)

    info("\n*** Pushing Hardware INT Traces to JSON...\n")
    node_ips = ','.join([f'10.0.0.{i+1}:{cca_list[i % len(cca_list)]}' for i in range(num_flows)])
    collector.cmd(f'python3 int_collector.py /tmp/collector.pcap {node_ips} > /tmp/int_collector.log 2>&1')
    
    return summary

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--behavioral-exe', type=str, required=True)
    parser.add_argument('--json', type=str, required=True)
    parser.add_argument('--test-only', action='store_true')
    parser.add_argument('--traffic', action='store_true')
    parser.add_argument('--duration', type=int, default=30)
    parser.add_argument('--priority-queues', type=int, default=3)
    parser.add_argument('--num-flows', type=int, default=2)
    parser.add_argument('--ccas', type=str, default='cubic,bbr')
    args = parser.parse_args()

    # Build CCAs up to num-flows if shorter
    cca_list = [c.strip() for c in args.ccas.split(',')]
    if len(cca_list) < args.num_flows:
        args.ccas = ','.join(cca_list * (args.num_flows // len(cca_list) + 1))

    topo = KBCSTopo(args.behavioral_exe, args.json, priority_queues=args.priority_queues, num_flows=args.num_flows)
    net = Mininet(topo=topo, host=P4Host, switch=KBCSSwitch, controller=None, link=TCLink)
    net.start()

    configure_hosts(net, args.num_flows, args.ccas)
    install_forwarding_rules(args.num_flows)
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
        net.pingAll()
    elif args.traffic:
        run_iperf_test(net, args.num_flows, args.ccas, duration=args.duration)
    else:
        CLI(net)
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    main()
