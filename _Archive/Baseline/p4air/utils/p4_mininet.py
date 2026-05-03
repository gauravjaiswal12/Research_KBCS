"""
p4_mininet.py — BMv2 Mininet Integration Helper
=================================================
Provides P4Switch and P4Host classes for running BMv2 simple_switch
inside Mininet topologies.

This is the standard helper used by P4 tutorials and the KBCS project.
It creates a Mininet switch that runs BMv2's simple_switch process
and a host that disables default IP offloading (required for BMv2).

Note: This file goes into Baseline/p4air/utils/ and is imported by topology.py.
      On the P4 VM, you may already have this at a system path — this local copy
      ensures the project is self-contained.
"""

import subprocess
import os
import signal
from time import sleep

from mininet.node import Switch, Host
from mininet.log import setLogLevel, info, error, debug


class P4Host(Host):
    """Mininet host configured for P4 switch experiments.

    Disables IP checksum offloading and ARP/NDP features that
    interfere with BMv2's software packet processing.
    """
    def config(self, **params):
        """Configure the host after it is created.

        Disables TX/RX checksum offloading on all interfaces because
        BMv2 processes packets in software and expects correct checksums
        in every packet (hardware offloading would leave them unfilled).
        """
        r = super(P4Host, self).config(**params)

        # Disable offloading on all interfaces
        for off in ['rx', 'tx', 'sg']:
            cmd = '/sbin/ethtool --offload %s %s off' % (self.defaultIntf().name, off)
            self.cmd(cmd)

        # Set default route (needed for multi-hop if applicable)
        self.cmd('sysctl -w net.ipv4.ip_forward=0')

        return r

    def describe(self):
        """Return a short description string for logging."""
        return '%s: IP=%s, MAC=%s' % (
            self.name, self.IP(), self.MAC())


class P4Switch(Switch):
    """Mininet switch that runs BMv2's simple_switch process.

    Starts the BMv2 simple_switch binary with the compiled P4 JSON,
    manages the process lifecycle, and supports configuring thrift port
    for runtime table management via simple_switch_CLI.

    Args:
        name:        Switch name (e.g., 's1')
        sw_path:     Path to simple_switch binary (default: 'simple_switch')
        json_path:   Path to compiled P4 JSON file
        thrift_port: Port for simple_switch_CLI thrift interface (default: 9090)
        pcap_dump:   Enable PCAP packet capture (default: False)
        log_console: Print switch logs to console (default: False)
        verbose:     Verbose logging (default: False)
        device_id:   Device ID for multi-switch setups (default: None → auto)
    """
    device_id = 0  # Class-level counter for auto-incrementing device IDs

    def __init__(self, name,
                 sw_path='simple_switch',
                 json_path=None,
                 thrift_port=9090,
                 pcap_dump=False,
                 log_console=False,
                 verbose=False,
                 device_id=None,
                 **kwargs):
        Switch.__init__(self, name, **kwargs)
        assert json_path, "P4Switch requires a --json argument (compiled P4 JSON)"

        self.sw_path = sw_path
        self.json_path = json_path
        self.thrift_port = thrift_port
        self.pcap_dump = pcap_dump
        self.log_console = log_console
        self.verbose = verbose

        # Auto-assign device ID if not specified
        if device_id is not None:
            self.device_id = device_id
            P4Switch.device_id = max(P4Switch.device_id, device_id)
        else:
            self.device_id = P4Switch.device_id
            P4Switch.device_id += 1

        self.nanomsg = "ipc:///tmp/bm-%d-log.ipc" % self.device_id

    def check_switch_started(self, pid):
        """Verify that the switch process started successfully.

        Waits briefly then checks if the process is still running.
        Returns True if switch is running, False otherwise.
        """
        sleep(0.5)
        try:
            # os.kill with signal 0 checks if process exists
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def start(self, controllers):
        """Start the BMv2 simple_switch process.

        Builds the command line with all interface mappings, optional
        PCAP, logging, and thrift port configuration.
        """
        info("Starting P4 switch %s.\n" % self.name)

        # Build interface mapping: -i port_num@interface_name
        args = [self.sw_path]
        for port, intf in self.intfs.items():
            if not intf.IP():  # Skip loopback
                args.extend(['-i', '%d@%s' % (port, intf.name)])

        # Add PCAP dump if enabled
        if self.pcap_dump:
            args.append('--pcap')

        # Add thrift port for CLI access
        args.extend(['--thrift-port', str(self.thrift_port)])

        # Add nanomsg IPC for event logging
        args.extend(['--nanolog', self.nanomsg])

        # Add device ID
        args.extend(['--device-id', str(self.device_id)])

        # Add the compiled P4 JSON
        args.append(self.json_path)

        # Log the command for debugging
        if self.verbose:
            info("Switch command: %s\n" % ' '.join(args))

        # Start the process
        logfile = '/tmp/p4s.%s.log' % self.name
        info("Switch log: %s\n" % logfile)

        with open(logfile, 'w') as log:
            pid = None
            if self.log_console:
                # Print to console AND log file
                self.cmd(' '.join(args) + ' > ' + logfile + ' 2>&1 &')
                pid = int(self.cmd('echo $!').strip())
            else:
                # Background with output to log file only
                self.cmd(' '.join(args) + ' > ' + logfile + ' 2>&1 &')
                pid = int(self.cmd('echo $!').strip())

        # Verify switch started
        sleep(1)
        if not self.check_switch_started(pid):
            error("ERROR: P4 switch %s did not start correctly.\n" % self.name)
            error("Check log: %s\n" % logfile)
            return

        info("P4 switch %s running (PID %d, thrift port %d)\n" %
             (self.name, pid, self.thrift_port))

    def stop(self):
        """Stop the BMv2 simple_switch process."""
        self.cmd('kill %simple_switch 2>/dev/null')
        self.cmd('wait')
        self.deleteIntfs()

    def attach(self, intf):
        """Attach an interface to the switch (not needed for P4Switch)."""
        assert 0

    def detach(self, intf):
        """Detach an interface from the switch (not needed for P4Switch)."""
        assert 0
