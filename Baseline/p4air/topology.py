"""
topology.py — P4air Mininet Topology Builder
==============================================
Creates a dumbbell topology with N client hosts connected to a single P4air
switch (BMv2 simple_switch), which connects to a server host via a
bandwidth-limited bottleneck link.

This is based on the KBCS topology.py and adapted for P4air experiments.

Topology:
    h1 (CCA1) ──┐                         ┌── server (h_server)
    h2 (CCA2) ──┤   100 Mbps    10 Mbps   │
       ...      ├────── [ s1 ] ────────────┘
    hN (CCAn) ──┘    (P4air)   bottleneck
                     BMv2       5ms delay
                     switch     queue=200 pkts

Usage:
    # Interactive CLI
    sudo python3 topology.py --behavioral-exe simple_switch --json build/p4air.json

    # Run traffic test
    sudo python3 topology.py --behavioral-exe simple_switch --json build/p4air.json \\
                             --traffic --duration 30 --num-clients 4

    # Specify CCAs per host
    sudo python3 topology.py --behavioral-exe simple_switch --json build/p4air.json \\
                             --traffic --ccas cubic,bbr,vegas,illinois
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


class P4airSwitch(P4Switch):
    """P4Switch subclass that enables priority queues in simple_switch.

    BMv2's simple_switch supports up to 8 priority queues per port.
    P4air uses 8 queues: 0=ants, 1=mice, 2-7=CCA groups (Round Robin).
    """
    def __init__(self, name, priority_queues=8, **kwargs):
        P4Switch.__init__(self, name, **kwargs)
        self.priority_queues = priority_queues

    def start(self, controllers):
        """Inject --priority-queues flag into simple_switch command."""
        if self.priority_queues > 0:
            original_sw_path = self.sw_path
            self.sw_path = self.sw_path + ' --priority-queues %d' % self.priority_queues
            P4Switch.start(self, controllers)
            self.sw_path = original_sw_path
        else:
            P4Switch.start(self, controllers)


class P4airTopo(Topo):
    """Dumbbell topology: N clients → P4air switch → 1 server.

    All client links are 100 Mbps (non-bottleneck).
    Server link is 10 Mbps with configurable delay (bottleneck).

    Args:
        sw_path:         Path to simple_switch binary
        json_path:       Path to compiled P4 JSON
        num_clients:     Number of client hosts (default 4)
        bw_bottleneck:   Bottleneck bandwidth in Mbps (default 10)
        delay:           Bottleneck link delay (default '5ms')
        max_queue_size:  Max queue size in packets (default 200)
        priority_queues: Number of priority queues (default 8)
    """
    def __init__(self, sw_path, json_path, num_clients=4,
                 bw_bottleneck=10, delay='5ms', max_queue_size=200,
                 priority_queues=8, **opts):
        Topo.__init__(self, **opts)

        # Add the P4air switch
        switch = self.addSwitch('s1',
                                sw_path=sw_path,
                                json_path=json_path,
                                thrift_port=9090,
                                priority_queues=priority_queues,
                                cls=P4airSwitch)

        # Add client hosts (h1, h2, ..., hN) on ports 1..N
        for i in range(1, num_clients + 1):
            host = self.addHost('h%d' % i,
                                ip='10.0.0.%d/24' % i,
                                mac='00:00:00:00:00:%02x' % i)
            # Client links: 100 Mbps, no artificial delay
            self.addLink(host, switch, port2=i, cls=TCLink, bw=100)

        # Add server host on port (N+1) — the bottleneck link
        server_port = num_clients + 1
        server = self.addHost('server',
                              ip='10.0.0.100/24',
                              mac='00:00:00:00:00:64')
        self.addLink(server, switch, port2=server_port,
                     cls=TCLink, bw=bw_bottleneck,
                     delay=delay, max_queue_size=max_queue_size)


def configure_hosts(net, num_clients, ccas):
    """Configure ARP tables and congestion control algorithms on all hosts.

    Args:
        net:          Mininet network instance
        num_clients:  Number of client hosts
        ccas:         List of CCA names, one per client (e.g., ['cubic','bbr'])

    Returns:
        list of host objects, server object
    """
    hosts = [net.get('h%d' % i) for i in range(1, num_clients + 1)]
    server = net.get('server')
    all_hosts = hosts + [server]

    # Disable IPv6 on all hosts (avoids noise in experiments)
    for h in all_hosts:
        h.cmd('sysctl -w net.ipv6.conf.all.disable_ipv6=1')
        h.cmd('sysctl -w net.ipv6.conf.default.disable_ipv6=1')
        h.cmd('sysctl -w net.ipv6.conf.lo.disable_ipv6=1')

    # Static ARP entries — avoid ARP resolution delays during experiments
    for h in all_hosts:
        for other in all_hosts:
            if h != other:
                other_ip = other.IP()
                other_mac = other.MAC()
                h.cmd('arp -s %s %s' % (other_ip, other_mac))

    # Set congestion control algorithm per client
    info("\n*** Congestion Control configuration:\n")
    for i, host in enumerate(hosts):
        cca = ccas[i] if i < len(ccas) else 'cubic'
        # Try to load the kernel module (some CCAs need explicit loading)
        host.cmd('modprobe tcp_%s 2>/dev/null' % cca)
        host.cmd('sysctl -w net.ipv4.tcp_congestion_control=%s' % cca)
        actual = host.cmd('sysctl -n net.ipv4.tcp_congestion_control').strip()
        info("    h%d: requested=%s, actual=%s\n" % (i + 1, cca, actual))

    # Server uses default CCA (doesn't matter — server only receives)
    info("    server: %s (default)\n" %
         server.cmd('sysctl -n net.ipv4.tcp_congestion_control').strip())

    return hosts, server


def install_forwarding_rules(num_clients):
    """Populate the ipv4_lpm forwarding table via simple_switch_CLI.

    Creates one rule per host: destination IP → (next-hop MAC, output port).
    This runs AFTER the switch starts and the thrift server is ready.

    Args:
        num_clients: Number of client hosts
    """
    info("*** Installing forwarding rules...\n")

    # Rules for client hosts (h1..hN on ports 1..N)
    for i in range(1, num_clients + 1):
        cmd = ('echo "table_add P4airIngress.ipv4_lpm P4airIngress.ipv4_forward '
               '10.0.0.%d/32 => 00:00:00:00:00:%02x %d" '
               '| simple_switch_CLI --thrift-port 9090' % (i, i, i))
        os.system(cmd)

    # Rule for server (10.0.0.100 → port N+1)
    server_port = num_clients + 1
    cmd = ('echo "table_add P4airIngress.ipv4_lpm P4airIngress.ipv4_forward '
           '10.0.0.100/32 => 00:00:00:00:00:64 %d" '
           '| simple_switch_CLI --thrift-port 9090' % server_port)
    os.system(cmd)

    info("    Installed %d forwarding rules\n" % (num_clients + 1))


def run_traffic_test(net, num_clients, duration=30):
    """Run iperf3 traffic test: all clients send TCP to the server simultaneously.

    Each client opens a separate iperf3 stream to the server on a unique port.
    After the test, parses throughput results and computes Jain's Fairness Index.

    Args:
        net:          Mininet network instance
        num_clients:  Number of client hosts
        duration:     Test duration in seconds

    Returns:
        dict with per-flow throughputs, retransmits, and fairness index
    """
    hosts = [net.get('h%d' % i) for i in range(1, num_clients + 1)]
    server = net.get('server')

    # Prepare result file paths
    result_files = ['/tmp/p4air_h%d.json' % i for i in range(1, num_clients + 1)]
    for f in result_files:
        os.system('rm -f %s' % f)

    info("\n*** Starting traffic test (%d clients → server, %ds)\n" % (num_clients, duration))
    info("    Bottleneck: server link (10 Mbps)\n")

    # Kill any leftover iperf3 instances
    server.cmd('killall iperf3 2>/dev/null')
    sleep(1)

    # Start one iperf3 server instance per client on unique ports
    for i in range(num_clients):
        port = 5201 + i
        server.cmd('iperf3 -s -p %d -D' % port)
    sleep(2)

    info("    iperf3 servers started on ports %d-%d\n" % (5201, 5200 + num_clients))

    # Start all clients simultaneously using sendCmd (non-blocking)
    for i, host in enumerate(hosts):
        port = 5201 + i
        result_file = result_files[i]
        host.sendCmd('iperf3 -c 10.0.0.100 -p %d -t %d -J > %s 2>&1' %
                     (port, duration, result_file))

    # Wait for tests to complete
    info("*** Waiting %d seconds...\n" % (duration + 5))
    sleep(duration + 5)

    # Collect results from all hosts
    for host in hosts:
        try:
            host.waitOutput(verbose=False)
        except:
            pass
    sleep(1)

    # Parse results
    info("\n*** ===== TRAFFIC TEST RESULTS ===== ***\n")
    throughputs = []
    results = {}

    for i in range(num_clients):
        label = 'h%d' % (i + 1)
        fpath = result_files[i]
        try:
            with open(fpath, 'r') as f:
                content = f.read().strip()
            if not content:
                info("    %s: Result file EMPTY\n" % label)
                throughputs.append(0.0)
                continue
            data = json.loads(content)
            if 'error' in data:
                info("    %s: iperf3 error: %s\n" % (label, data['error']))
                throughputs.append(0.0)
                continue
            mbps = data['end']['sum_sent']['bits_per_second'] / 1e6
            retx = data['end']['sum_sent'].get('retransmits', 'N/A')
            cca = data.get('start', {}).get('tcp_mss_default', 'N/A')
            info("    %s: %.2f Mbps (retransmits: %s)\n" % (label, mbps, retx))
            throughputs.append(mbps)
            results[label] = {'mbps': round(mbps, 2), 'retransmits': retx}
        except Exception as e:
            info("    %s: Parse error (%s)\n" % (label, str(e)))
            throughputs.append(0.0)

    # Calculate Jain's Fairness Index
    #   J(x) = (Σxᵢ)² / (n × Σxᵢ²)
    #   Range: [1/n, 1] where 1 is perfectly fair
    n = len(throughputs)
    sum_x = sum(throughputs)
    sum_x2 = sum(x ** 2 for x in throughputs)
    if sum_x2 > 0 and n > 0:
        jain = (sum_x ** 2) / (n * sum_x2)
    else:
        jain = 0.0

    info("\n    Jain's Fairness Index: %.4f\n" % jain)
    info("    (1.0 = perfectly fair, %.2f = completely unfair)\n" % (1.0 / n if n > 0 else 0))
    info("    Total throughput: %.2f Mbps\n" % sum_x)

    # Save summary
    os.makedirs('results', exist_ok=True)
    summary = {
        'flows': results,
        'num_clients': num_clients,
        'duration': duration,
        'total_mbps': round(sum_x, 2),
        'jain_index': round(jain, 4),
        'throughputs': [round(t, 2) for t in throughputs]
    }
    with open('results/last_test.json', 'w') as f:
        json.dump(summary, f, indent=2)
    info("    Results saved to results/last_test.json\n")

    info("\n*** ===== TEST COMPLETE ===== ***\n")
    server.cmd('killall iperf3 2>/dev/null')
    return summary


def main():
    """Main entry point. Parse arguments and launch Mininet."""
    parser = argparse.ArgumentParser(description='P4air Mininet Topology')

    # Required arguments
    parser.add_argument('--behavioral-exe',
                        help='Path to simple_switch binary',
                        type=str, required=True)
    parser.add_argument('--json',
                        help='Path to compiled P4 JSON',
                        type=str, required=True)

    # Topology configuration
    parser.add_argument('--num-clients',
                        help='Number of client hosts (default: 4)',
                        type=int, default=4)
    parser.add_argument('--bw',
                        help='Bottleneck bandwidth in Mbps (default: 10)',
                        type=int, default=10)
    parser.add_argument('--delay',
                        help='Bottleneck link delay (default: 5ms)',
                        type=str, default='5ms')
    parser.add_argument('--queue-size',
                        help='Max queue size in packets (default: 200)',
                        type=int, default=200)
    parser.add_argument('--priority-queues',
                        help='Number of priority queues (default: 8)',
                        type=int, default=8)

    # CCA configuration
    parser.add_argument('--ccas',
                        help='Comma-separated list of CCAs per host '
                             '(default: cubic,bbr,vegas,illinois)',
                        type=str, default='cubic,bbr,vegas,illinois')

    # Run modes
    parser.add_argument('--test-only',
                        help='Run pingall and exit',
                        action='store_true')
    parser.add_argument('--traffic',
                        help='Run iperf3 traffic test',
                        action='store_true')
    parser.add_argument('--duration',
                        help='Traffic test duration in seconds (default: 30)',
                        type=int, default=30)

    args = parser.parse_args()

    # Parse CCA list
    ccas = [c.strip() for c in args.ccas.split(',')]
    num_clients = args.num_clients

    # Ensure we have enough CCAs (repeat last one if needed)
    while len(ccas) < num_clients:
        ccas.append(ccas[-1])

    info("*** P4air Topology Configuration:\n")
    info("    Clients: %d\n" % num_clients)
    info("    CCAs: %s\n" % ', '.join(ccas[:num_clients]))
    info("    Bottleneck: %d Mbps, delay=%s, queue=%d pkts\n" %
         (args.bw, args.delay, args.queue_size))
    info("    Priority queues: %d\n" % args.priority_queues)

    # Build topology
    topo = P4airTopo(args.behavioral_exe, args.json,
                     num_clients=num_clients,
                     bw_bottleneck=args.bw,
                     delay=args.delay,
                     max_queue_size=args.queue_size,
                     priority_queues=args.priority_queues)

    # Create network
    net = Mininet(topo=topo, host=P4Host, switch=P4airSwitch,
                  controller=None, link=TCLink)
    net.start()

    # Configure hosts
    hosts, server = configure_hosts(net, num_clients, ccas)
    sleep(1)

    # Install forwarding rules
    install_forwarding_rules(num_clients)
    sleep(1)

    # Execute requested mode
    if args.test_only:
        info("*** Running connectivity test...\n")
        net.pingAll()
    elif args.traffic:
        info("*** Quick connectivity check...\n")
        net.pingAll()
        run_traffic_test(net, num_clients, duration=args.duration)
    else:
        # Interactive CLI (for debugging)
        CLI(net)

    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    main()
