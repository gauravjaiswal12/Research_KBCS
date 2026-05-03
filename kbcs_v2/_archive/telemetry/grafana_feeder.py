#!/usr/bin/env python3
"""
KBCS v2 — Grafana Telemetry Feeder
====================================
Polls BMv2 switch registers every 500ms via simple_switch_CLI
and writes karma/drops/fwd_bytes/color/JFI to InfluxDB 1.8 (HTTP line protocol).

This feeds the Grafana dashboard with live data for ALL 8 flows
(4 from S1 + 4 from S2).

Usage (while Mininet is running):
  python3 telemetry/grafana_feeder.py
"""

import subprocess
import time
import urllib.request
import urllib.error
import sys
import signal

INFLUX_URL = "http://localhost:8086/write?db=kbcs_telemetry"
POLL_INTERVAL = 0.5  # seconds

# S1 handles flows 1-4, S2 handles flows 5-8
SWITCH_FLOWS = {
    9090: {1: "CUBIC", 2: "BBR", 3: "Vegas", 4: "Illinois"},
    9091: {5: "CUBIC", 6: "BBR", 7: "Vegas", 8: "Illinois"},
}

running = True

def signal_handler(sig, frame):
    global running
    print("\n[feeder] Stopping...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def read_register(thrift_port, register_name, index):
    """Read a single register value from BMv2 via simple_switch_CLI."""
    try:
        cmd = f"echo 'register_read {register_name} {index}' | simple_switch_CLI --thrift-port {thrift_port} 2>/dev/null"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)
        stdout = result.stdout
        for line in stdout.split('\n'):
            if '=' in line:
                short_name = register_name.split('.')[-1]
                if short_name in line:
                    val_str = line.split('=')[-1].strip()
                    if val_str.isdigit():
                        return int(val_str)
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    return 0


def write_influx(lines):
    """Write InfluxDB line protocol data via HTTP POST."""
    data = '\n'.join(lines).encode('utf-8')
    try:
        req = urllib.request.Request(INFLUX_URL, data=data, method='POST')
        req.add_header('Content-Type', 'application/octet-stream')
        resp = urllib.request.urlopen(req, timeout=2)
        return resp.status == 204
    except urllib.error.URLError:
        return False
    except Exception:
        return False


def main():
    print("=" * 60)
    print("  KBCS v2 — Grafana Telemetry Feeder (8 flows)")
    print("  Polling S1 + S2 registers → InfluxDB (kbcs_telemetry)")
    print("  Grafana: http://localhost:3000")
    print("=" * 60)

    # Wait for InfluxDB to be ready
    print("[feeder] Waiting for InfluxDB...")
    for i in range(30):
        try:
            req = urllib.request.Request("http://localhost:8086/ping")
            resp = urllib.request.urlopen(req, timeout=2)
            if resp.status == 204:
                print("[feeder] InfluxDB is ready!")
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        print("[feeder] WARNING: InfluxDB not responding, will retry writes.")

    # Detect which switches are available
    active_switches = {}
    for thrift_port, flows in SWITCH_FLOWS.items():
        first_fid = list(flows.keys())[0]
        karma = read_register(thrift_port, "MyIngress.reg_karma", first_fid)
        # Try a few times
        for attempt in range(5):
            if karma > 0:
                break
            time.sleep(1)
            karma = read_register(thrift_port, "MyIngress.reg_karma", first_fid)
        
        if karma > 0 or attempt >= 3:
            active_switches[thrift_port] = flows
            print(f"[feeder] Switch {thrift_port} connected (karma[{first_fid}]={karma})")
        else:
            print(f"[feeder] Switch {thrift_port} not responding, skipping")

    if not active_switches:
        print("[feeder] ERROR: No switches responding!")
        # Fall back to S1 only
        active_switches = {9090: {1: "CUBIC", 2: "BBR", 3: "Vegas", 4: "Illinois"}}
        print("[feeder] Falling back to S1 only")

    cycle = 0
    while running:
        ts_ns = int(time.time() * 1e9)
        lines = []
        throughputs = []

        for thrift_port, flows in active_switches.items():
            for fid, name in flows.items():
                karma = read_register(thrift_port, "MyIngress.reg_karma", fid)
                drops = read_register(thrift_port, "MyIngress.reg_drops", fid)
                fwd = read_register(thrift_port, "MyIngress.reg_forwarded_bytes", fid)

                # Color zone
                if karma >= 76:
                    color = 2  # GREEN
                elif karma >= 41:
                    color = 1  # YELLOW
                else:
                    color = 0  # RED

                line = f"kbcs_flow,flow_id={fid},flow_name={name} karma={karma}i,color={color}i,drops={drops}i,fwd_bytes={fwd}i {ts_ns}"
                lines.append(line)
                throughputs.append(fwd)

                if cycle % 4 == 0:
                    color_str = ["RED", "YELLOW", "GREEN"][color]
                    print(f"  Flow {fid} ({name:8s}): karma={karma:3d} [{color_str:6s}] drops={drops} fwd={fwd}")

        # JFI over all active flows
        if sum(throughputs) > 0:
            n = len(throughputs)
            sum_x = sum(throughputs)
            sum_x2 = sum(x*x for x in throughputs)
            jfi = (sum_x ** 2) / (n * sum_x2) if sum_x2 > 0 else 1.0
        else:
            jfi = 0.0

        lines.append(f"kbcs_system jfi={jfi:.4f} {ts_ns}")

        # Queue depths from S1
        for port in range(1, 7):
            qdepth = read_register(9090, "MyEgress.reg_qdepth", port)
            lines.append(f"kbcs_queue,switch=s1,port={port} qdepth={qdepth}i {ts_ns}")

        success = write_influx(lines)

        if cycle % 4 == 0:
            print(f"  JFI = {jfi:.4f} | InfluxDB: {'OK' if success else 'FAIL'}")
            print("-" * 50)

        cycle += 1
        time.sleep(POLL_INTERVAL)

    print("[feeder] Done.")


if __name__ == '__main__':
    main()
