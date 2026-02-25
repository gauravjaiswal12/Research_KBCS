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
    def __init__(self, name, priority_queues=0, **kwargs):
        P4Switch.__init__(self, name, **kwargs)
        self.priority_queues = priority_queues

    def start(self, controllers):
        """Start with --priority-queues injected into the command."""
        if self.priority_queues > 0:
            # Temporarily modify sw_path to include the priority queues flag
            original_sw_path = self.sw_path
            self.sw_path = self.sw_path + ' --priority-queues %d' % self.priority_queues
            P4Switch.start(self, controllers)
            self.sw_path = original_sw_path
        else:
            P4Switch.start(self, controllers)


class KBCSTopo(Topo):
    def __init__(self, sw_path, json_path, priority_queues=0, **opts):
        Topo.__init__(self, **opts)

        switch = self.addSwitch('s1',
                                sw_path = sw_path,
                                json_path = json_path,
                                thrift_port = 9090,
                                priority_queues = priority_queues,
                                cls = KBCSSwitch)

        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:01:01')
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:02:02')
        h3 = self.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:03:03')

        self.addLink(h1, switch, port2=1, cls=TCLink, bw=100)
        self.addLink(h2, switch, port2=2, cls=TCLink, bw=100)
        self.addLink(h3, switch, port2=3, cls=TCLink, bw=10, delay='5ms', max_queue_size=200)


def configure_hosts(net):
    h1, h2, h3 = net.get('h1'), net.get('h2'), net.get('h3')

    for h in [h1, h2, h3]:
        h.cmd('sysctl -w net.ipv6.conf.all.disable_ipv6=1')
        h.cmd('sysctl -w net.ipv6.conf.default.disable_ipv6=1')
        h.cmd('sysctl -w net.ipv6.conf.lo.disable_ipv6=1')

    h1.cmd('arp -s 10.0.0.2 00:00:00:00:02:02')
    h1.cmd('arp -s 10.0.0.3 00:00:00:00:03:03')
    h2.cmd('arp -s 10.0.0.1 00:00:00:00:01:01')
    h2.cmd('arp -s 10.0.0.3 00:00:00:00:03:03')
    h3.cmd('arp -s 10.0.0.1 00:00:00:00:01:01')
    h3.cmd('arp -s 10.0.0.2 00:00:00:00:02:02')

    h1.cmd('sysctl -w net.ipv4.tcp_congestion_control=cubic')
    h2.cmd('modprobe tcp_bbr 2>/dev/null; sysctl -w net.ipv4.tcp_congestion_control=bbr')
    h3.cmd('sysctl -w net.ipv4.tcp_congestion_control=reno')

    info("*** Congestion Control configured:\n")
    info("    h1 (CUBIC): %s" % h1.cmd('sysctl net.ipv4.tcp_congestion_control').strip() + "\n")
    info("    h2 (BBR):   %s" % h2.cmd('sysctl net.ipv4.tcp_congestion_control').strip() + "\n")
    return h1, h2, h3


def install_forwarding_rules():
    print("Populating forwarding rules...")
    os.system('echo "table_add MyIngress.ipv4_lpm MyIngress.ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 1" | simple_switch_CLI --thrift-port 9090')
    os.system('echo "table_add MyIngress.ipv4_lpm MyIngress.ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 2" | simple_switch_CLI --thrift-port 9090')
    os.system('echo "table_add MyIngress.ipv4_lpm MyIngress.ipv4_forward 10.0.0.3/32 => 00:00:00:00:03:03 3" | simple_switch_CLI --thrift-port 9090')


def run_iperf_test(net, duration=30):
    """Run iperf3 traffic test: h1(CUBIC) and h2(BBR) both send to h3."""
    h1, h2, h3 = net.get('h1'), net.get('h2'), net.get('h3')

    r1_file = '/tmp/kbcs_h1_cubic.json'
    r2_file = '/tmp/kbcs_h2_bbr.json'
    os.system('rm -f %s %s' % (r1_file, r2_file))

    info("\n*** Starting iperf3 traffic test (duration=%ds)\n" % duration)
    info("    h1 (CUBIC) -> h3  &  h2 (BBR) -> h3\n")
    info("    Bottleneck: 10 Mbps link to h3\n\n")

    # Verify iperf3 exists
    info("    iperf3 path: %s\n" % h1.cmd('which iperf3').strip())

    # Start iperf3 servers on h3
    h3.cmd('killall iperf3 2>/dev/null')
    sleep(1)
    h3.cmd('iperf3 -s -p 5201 -D')
    h3.cmd('iperf3 -s -p 5202 -D')
    sleep(2)
    info("    Servers: %s\n" % h3.cmd('pgrep -a iperf3').strip().replace('\n', ' | '))

    # Run h1 and h2 clients using sendCmd for true parallel execution
    info("\n*** Starting clients simultaneously...\n")
    h1.sendCmd('iperf3 -c 10.0.0.3 -p 5201 -t %d -J > %s 2>&1' % (duration, r1_file))
    h2.sendCmd('iperf3 -c 10.0.0.3 -p 5202 -t %d -J > %s 2>&1' % (duration, r2_file))

    info("*** Waiting %d seconds for tests to complete...\n" % (duration + 5))
    sleep(duration + 5)

    # waitOutput() is REQUIRED after sendCmd to reset the host shell state
    try:
        h1.waitOutput(verbose=False)
    except:
        pass
    try:
        h2.waitOutput(verbose=False)
    except:
        pass
    sleep(1)

    # Check file sizes
    r1_size = os.path.getsize(r1_file) if os.path.exists(r1_file) else 0
    r2_size = os.path.getsize(r2_file) if os.path.exists(r2_file) else 0
    info("    Result files: h1=%d bytes, h2=%d bytes\n" % (r1_size, r2_size))

    # ===== PARSE RESULTS =====
    info("\n*** ===== TRAFFIC TEST RESULTS ===== ***\n")
    t1, t2, r1_retx, r2_retx = 0.0, 0.0, 'N/A', 'N/A'

    for fpath, label, is_h1 in [(r1_file, 'h1 (CUBIC)', True), (r2_file, 'h2 (BBR)', False)]:
        try:
            with open(fpath, 'r') as f:
                content = f.read().strip()
            if not content:
                info("    %s: Result file is EMPTY\n" % label)
                continue
            data = json.loads(content)
            if 'error' in data:
                info("    %s: iperf3 error: %s\n" % (label, data['error']))
                continue
            mbps = data['end']['sum_sent']['bits_per_second'] / 1e6
            retx = data['end']['sum_sent'].get('retransmits', 'N/A')
            info("    %s: %.2f Mbps (retransmits: %s)\n" % (label, mbps, retx))
            if is_h1:
                t1, r1_retx = mbps, retx
            else:
                t2, r2_retx = mbps, retx
        except Exception as e:
            info("    %s: Parse error (%s)\n" % (label, str(e)))

    # Jain's Fairness Index
    if t1 > 0 or t2 > 0:
        jain = ((t1 + t2) ** 2) / (2 * (t1**2 + t2**2))
        info("\n    Jain's Fairness Index: %.4f\n" % jain)
        info("    (1.0 = perfectly fair, 0.5 = completely unfair)\n")
    else:
        jain = 0
        info("\n    ERROR: No throughput data collected.\n")
        info("    Debug: Check if iperf3 clients could connect to servers.\n")

    # Save summary
    os.makedirs('results', exist_ok=True)
    summary = {'cubic_mbps': round(t1, 2), 'bbr_mbps': round(t2, 2),
               'cubic_retransmits': r1_retx, 'bbr_retransmits': r2_retx,
               'jain_index': round(jain, 4), 'duration': duration}
    with open('results/last_test.json', 'w') as f:
        json.dump(summary, f, indent=2)

    info("\n*** ===== TEST COMPLETE ===== ***\n")
    h3.cmd('killall iperf3 2>/dev/null')
    return summary


def main():
    parser = argparse.ArgumentParser(description='KBCS Mininet topology')
    parser.add_argument('--behavioral-exe', help='Path to behavioral executable',
                        type=str, action="store", required=True)
    parser.add_argument('--json', help='Path to JSON config file',
                        type=str, action="store", required=True)
    parser.add_argument('--test-only', help='Run pingall and exit',
                        action='store_true')
    parser.add_argument('--traffic', help='Run iperf3 traffic test',
                        action='store_true')
    parser.add_argument('--duration', help='Traffic test duration (seconds)',
                        type=int, default=30)
    parser.add_argument('--priority-queues', help='Number of priority queues',
                        type=int, default=0)
    args = parser.parse_args()

    pq = args.priority_queues
    info("*** Priority queues: %s\n" % (str(pq) if pq > 0 else 'DISABLED (FIFO)'))

    topo = KBCSTopo(args.behavioral_exe, args.json, priority_queues=pq)
    net = Mininet(topo=topo, host=P4Host, switch=KBCSSwitch, controller=None, link=TCLink)
    net.start()

    h1, h2, h3 = configure_hosts(net)
    install_forwarding_rules()
    sleep(1)

    if args.test_only:
        print("Running automated pingall test...")
        net.pingAll()
    elif args.traffic:
        info("*** Quick connectivity check...\n")
        net.pingAll()
        run_iperf_test(net, duration=args.duration)
    else:
        CLI(net)

    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    main()
