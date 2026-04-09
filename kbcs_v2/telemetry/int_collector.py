#!/usr/bin/env python3
"""
KBCS v2 — INT Telemetry Collector (Live)
=========================================
Listens for cloned telemetry packets from KBCS P4 switches on a
designated mirror interface, parses the custom kbcs_telemetry_t header,
and writes events to:
  1. InfluxDB (for Grafana live dashboard)
  2. A local CSV file (results/telemetry_<timestamp>.csv)
  3. Terminal live table (visible without Grafana)

How it connects to the P4 switch:
  When the P4 switch calls clone() in kbcs_v2.p4 (Stage 8), it
  redirects a copy of the packet to the mirror session port.
  In Mininet this mirror port is typically 'cpu' or a dedicated
  interface like 's1-cpu0'. We sniff ALL interfaces by default.

Telemetry header format (kbcs_telemetry_t after etherType=0x1234):
  Byte 0   : flow_id      (8 bits)
  Byte 1   : karma_score  (8 bits)
  Bytes 2  : color[7:6] + queue_id[5:3] + enq_qdepth[2:0] (MSB)
  Bytes 3  : enq_qdepth [15:8]
  Bytes 4  : enq_qdepth [7:0]
  Byte 5   : is_dropped[7] + padding[6:0]

Color mapping:
  2 = GREEN   (karma 76-100)
  1 = YELLOW  (karma 41-75)
  0 = RED     (karma 0-40)

Usage (run INSIDE the P4 VM as root):
  sudo python3 int_collector.py --iface s1-eth1 --duration 120
  sudo python3 int_collector.py --iface any --duration 120 --influx

Requirements (already in P4 VM):
  pip3 install scapy influxdb-client
"""

import argparse
import csv
import datetime
import os
import struct
import sys
import time
from collections import defaultdict

# Scapy for live packet capture
try:
    from scapy.all import sniff, Ether, raw
    SCAPY_OK = True
except ImportError:
    print("[WARNING] scapy not found. Install with: pip3 install scapy")
    SCAPY_OK = False

# InfluxDB v1 via requests (no external client needed — just HTTP)
try:
    import requests as _requests
    INFLUX_OK = True
except ImportError:
    INFLUX_OK = False

# ─── Configuration ────────────────────────────────────────────────────────────

KBCS_ETHERTYPE = 0x1234     # custom etherType stamped on cloned packets in kbcs_v2.p4

# InfluxDB defaults — matches docker-compose.yml (InfluxDB 1.8)
# Run: cd ../kbcs && docker-compose up -d
INFLUX_URL = "http://localhost:8086"
INFLUX_DB  = "kbcs_telemetry"

# Color names for display
COLOR_MAP = {2: "GREEN", 1: "YELLOW", 0: "RED", 3: "?"}
COLOR_ANSI= {2: "\033[92m", 1: "\033[93m", 0: "\033[91m", 3: "\033[0m"}
RESET_ANSI = "\033[0m"

# Results directory
RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'results')


# ─── Telemetry Header Parser ──────────────────────────────────────────────────

def parse_kbcs_header(payload: bytes) -> dict:
    """
    Parse the kbcs_telemetry_t header from raw packet bytes (after Ethernet header).

    kbcs_telemetry_t layout (6 bytes total):
      [0]      flow_id      (8 bits)
      [1]      karma_score  (8 bits)
      [2][7:6] color        (2 bits)  — 2=GREEN,1=YELLOW,0=RED
      [2][5:3] queue_id     (3 bits)
      [2:4]    enq_qdepth   (19 bits spanning bytes 2,3,4)
      [5][7]   is_dropped   (1 bit)
      [5][6:0] padding      (7 bits, ignore)
    """
    if len(payload) < 6:
        return None

    flow_id     = payload[0]
    karma_score = payload[1]

    # Byte 2: color[1:0] in bits 7:6, queue_id in bits 5:3, qdepth MSB in bits 2:0
    color      = (payload[2] >> 6) & 0x03
    queue_id   = (payload[2] >> 3) & 0x07
    qdepth_msb = (payload[2] & 0x07)

    # Bytes 3 and 4: remaining 16 bits of qdepth
    qdepth = (qdepth_msb << 16) | (payload[3] << 8) | payload[4]

    # Byte 5: is_dropped in bit 7
    is_dropped = (payload[5] >> 7) & 0x01

    return {
        'flow_id'    : flow_id,
        'karma_score': karma_score,
        'color'      : color,
        'color_name' : COLOR_MAP.get(color, '?'),
        'queue_id'   : queue_id,
        'enq_qdepth' : qdepth,
        'is_dropped' : is_dropped,
        'timestamp'  : time.time(),
    }


# ─── InfluxDB Writer ─────────────────────────────────────────────────────────

class InfluxWriter:
    """
    Writes KBCS telemetry events to InfluxDB 1.8 using the
    HTTP line-protocol API. No external client library needed.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled and INFLUX_OK
        self.write_url = f"{INFLUX_URL}/write?db={INFLUX_DB}&precision=ns"
        if self.enabled:
            # Create DB if it doesn't exist
            try:
                _requests.post(f"{INFLUX_URL}/query",
                               params={'q': f'CREATE DATABASE {INFLUX_DB}'},
                               timeout=2)
                print(f"[InfluxDB] Connected → {INFLUX_URL}  db='{INFLUX_DB}'")
            except Exception as e:
                print(f"[InfluxDB] Could not connect: {e} — disabling InfluxDB writes")
                self.enabled = False
        else:
            print("[InfluxDB] Disabled (use --influx to enable)")

    def write(self, event: dict):
        if not self.enabled:
            return
        try:
            # InfluxDB line protocol:
            # measurement,tag=val field=val timestamp_ns
            ts_ns = int(event['timestamp'] * 1e9)
            line  = (f"kbcs_telemetry,flow_id={event['flow_id']},"
                     f"color={event['color_name']},"
                     f"dropped={event['is_dropped']} "
                     f"karma={event['karma_score']}i,"
                     f"queue_id={event['queue_id']}i,"
                     f"qdepth={event['enq_qdepth']}i,"
                     f"drop_flag={event['is_dropped']}i "
                     f"{ts_ns}")
            _requests.post(self.write_url, data=line.encode(), timeout=1)
        except Exception as e:
            pass  # don't crash the collector on InfluxDB hiccup

    def close(self):
        pass  # no persistent connection to close


# ─── CSV Writer ───────────────────────────────────────────────────────────────

class CSVWriter:
    """Writes KBCS telemetry events to a timestamped CSV file."""

    FIELDS = ['timestamp', 'flow_id', 'karma_score', 'color',
              'color_name', 'queue_id', 'enq_qdepth', 'is_dropped']

    def __init__(self):
        os.makedirs(RESULTS_DIR, exist_ok=True)
        ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(RESULTS_DIR, f"telemetry_{ts}.csv")
        self.file = open(self.path, 'w', newline='')
        self.writer = csv.DictWriter(self.file, fieldnames=self.FIELDS)
        self.writer.writeheader()
        print(f"[CSV] Writing to {self.path}")

    def write(self, event: dict):
        row = {k: event.get(k, '') for k in self.FIELDS}
        self.writer.writerow(row)
        self.file.flush()

    def close(self):
        self.file.close()
        print(f"[CSV] Closed. Records written to {self.path}")


# ─── Live Terminal Display ────────────────────────────────────────────────────

class LiveDisplay:
    """
    Maintains a per-flow karma state table and reprints
    it every N events so you can watch karma evolve in the terminal.
    """

    def __init__(self, refresh_every: int = 20):
        self.refresh_every = refresh_every
        self.event_count   = 0
        self.flow_state    = defaultdict(lambda: {
            'karma': 100, 'color': 'GREEN', 'drops': 0, 'events': 0})
        self.start_time    = time.time()

    def update(self, event: dict):
        fid  = event['flow_id']
        self.flow_state[fid]['karma']  = event['karma_score']
        self.flow_state[fid]['color']  = event['color_name']
        self.flow_state[fid]['events'] += 1
        if event['is_dropped']:
            self.flow_state[fid]['drops'] += 1
        self.event_count += 1

        if self.event_count % self.refresh_every == 0:
            self._print_table()

    def _print_table(self):
        elapsed = time.time() - self.start_time
        print(f"\n{'─'*55}")
        print(f" KBCS v2 Live Karma Table   T={elapsed:.1f}s  Events={self.event_count}")
        print(f"{'─'*55}")
        print(f"{'Flow':>4}  {'Karma':>5}  {'Color':>7}  {'Drops':>6}  {'EventCount':>10}")
        print(f"{'─'*55}")

        for fid in sorted(self.flow_state.keys()):
            s     = self.flow_state[fid]
            color = s['color']
            ansi  = COLOR_ANSI.get({'GREEN':2,'YELLOW':1,'RED':0}.get(color, 3), '')
            print(f"{fid:>4}  {s['karma']:>5}  "
                  f"{ansi}{color:>7}{RESET_ANSI}  "
                  f"{s['drops']:>6}  {s['events']:>10}")
        print(f"{'─'*55}")

    def final_summary(self):
        print("\n" + "="*55)
        print(" KBCS v2 — Final Telemetry Summary")
        print("="*55)
        self._print_table()
        print(f"\nTotal telemetry events captured: {self.event_count}")


# ─── Packet Handler ───────────────────────────────────────────────────────────

class PacketHandler:
    """
    Called by scapy for every captured packet.
    Filters KBCS telemetry packets (etherType 0x1234) and routes
    the parsed event to all configured writers.
    """

    def __init__(self, influx: InfluxWriter, csv_w: CSVWriter,
                 display: LiveDisplay):
        self.influx   = influx
        self.csv_w    = csv_w
        self.display  = display
        self.total    = 0
        self.matched  = 0

    def __call__(self, pkt):
        self.total += 1
        try:
            # Check etherType is 0x1234 (our KBCS telemetry marker)
            if not pkt.haslayer(Ether):
                return
            ether = pkt[Ether]
            if ether.type != KBCS_ETHERTYPE:
                return

            # The KBCS telemetry header immediately follows the Ethernet header
            payload = bytes(ether.payload)
            event   = parse_kbcs_header(payload)
            if event is None:
                return

            self.matched += 1

            # Write to all outputs
            self.influx.write(event)
            self.csv_w.write(event)
            self.display.update(event)

        except Exception as e:
            print(f"[Handler] Error processing packet: {e}")

    def stats(self) -> str:
        return f"Total={self.total}  Matched={self.matched}"


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description='KBCS v2 INT Telemetry Collector')
    parser.add_argument('--iface',    type=str, default='any',
                        help='Interface to sniff (default: any). Use s1-cpu0 for Mininet mirror port.')
    parser.add_argument('--duration', type=int, default=120,
                        help='Capture duration in seconds (default: 120)')
    parser.add_argument('--influx',   action='store_true',
                        help='Enable InfluxDB writes (requires running InfluxDB)')
    parser.add_argument('--refresh',  type=int, default=20,
                        help='Refresh terminal table every N events (default: 20)')
    return parser.parse_args()


def main():
    args = parse_args()

    if not SCAPY_OK:
        print("ERROR: scapy is required. Install with: pip3 install scapy")
        sys.exit(1)

    print("="*55)
    print("KBCS v2 INT Telemetry Collector")
    print(f"Interface : {args.iface}")
    print(f"Duration  : {args.duration}s")
    print(f"InfluxDB  : {'enabled' if args.influx else 'disabled'}")
    print("="*55)

    # Initialise writers
    influx = InfluxWriter(enabled=args.influx)

    csv_w    = CSVWriter()
    display  = LiveDisplay(refresh_every=args.refresh)
    handler  = PacketHandler(influx, csv_w, display)

    # BPF filter: only capture custom KBCS etherType 0x1234
    bpf_filter = f"ether proto 0x1234"

    print(f"\nListening on '{args.iface}' with filter '{bpf_filter}'...")
    print("Press Ctrl+C to stop early.\n")

    try:
        sniff(
            iface=args.iface if args.iface != 'any' else None,
            filter=bpf_filter,
            prn=handler,
            timeout=args.duration,
            store=False,     # don't accumulate in memory
        )
    except KeyboardInterrupt:
        print("\n[Collector] Stopped by user.")
    except PermissionError:
        print("\n[ERROR] Permission denied — run with sudo.")
        sys.exit(1)

    # Final summary
    display.final_summary()
    print(f"\nPacket stats: {handler.stats()}")
    csv_w.close()
    if args.influx:
        influx.close()


if __name__ == '__main__':
    main()
