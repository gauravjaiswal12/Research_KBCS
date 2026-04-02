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
    def __init__(self, name, priority_queues=4, **kwargs):
        P4Switch.__init__(self, name, **kwargs)
        self.priority_queues = priority_queues

    def start(self, controllers):
        if self.priority_queues > 0:
            original_sw_path = self.sw_path
            self.sw_path = self.sw_path + ' --priority-queues %d' % self.priority_queues
            P4Switch.start(self, controllers)
            self.sw_path = original_sw_path
        else:
            P4Switch.start(self, controllers)

class ParkingLotTopo(Topo):
    """
    Parking Lot Topology
    h1 ---- s1 ---- s2 ---- s3 ---- s4 ---- h_dest
            |       |       |       |
           h_n1    h_n2    h_n3    h_n4 
    (Where h_n X hosts generate cross-traffic)
    """
    def __init__(self, sw_path, json_path, priority_queues=4, **opts):
        Topo.__init__(self, **opts)

        switches = []
        for i in range(1, 5):
            switch = self.addSwitch('s%d' % i,
                                    sw_path=sw_path,
                                    json_path=json_path,
                                    thrift_port=9090 + i,
                                    priority_queues=priority_queues,
                                    cls=KBCSSwitch)
            switches.append(switch)

        # Links between switches
        self.addLink(switches[0], switches[1], cls=TCLink, bw=100)
        self.addLink(switches[1], switches[2], cls=TCLink, bw=100)
        self.addLink(switches[2], switches[3], cls=TCLink, bw=100)

        # Long flow hosts
        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:01:01', cls=P4Host)
        h_dest = self.addHost('h_dest', ip='10.0.0.99/24', mac='00:00:00:00:09:99', cls=P4Host)
        
        self.addLink(h1, switches[0], cls=TCLink, bw=100)
        self.addLink(h_dest, switches[3], cls=TCLink, bw=10, delay='5ms', max_queue_size=200)

        # Cross traffic hosts
        for i in range(1, 5):
            h_cross = self.addHost('h_n%d' % i, ip='10.0.0.1%d/24' % i, mac='00:00:00:00:02:0%d' % i, cls=P4Host)
            self.addLink(h_cross, switches[i-1], cls=TCLink, bw=100)

def main():
    parser = argparse.ArgumentParser(description='Parking Lot KBCS Topology')
    parser.add_argument('--behavioral-exe', help='Path to behavioral executable', type=str, action="store", required=True)
    parser.add_argument('--json', help='Path to JSON config file', type=str, action="store", required=True)
    parser.add_argument('--priority-queues', help='Number of priority queues', type=int, default=4)
    args = parser.parse_args()

    topo = ParkingLotTopo(args.behavioral_exe, args.json, priority_queues=args.priority_queues)
    net = Mininet(topo=topo, host=P4Host, switch=KBCSSwitch, controller=None, link=TCLink)
    net.start()

    # Disable IPv6 for cleaner PCAPs...
    for h in net.hosts:
        h.cmd('sysctl -w net.ipv6.conf.all.disable_ipv6=1')
        h.cmd('sysctl -w net.ipv6.conf.default.disable_ipv6=1')
        h.cmd('sysctl -w net.ipv6.conf.lo.disable_ipv6=1')

    print("Network ready. Run eval tests in mininet CLI.")
    CLI(net)
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    main()
