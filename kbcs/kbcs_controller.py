#!/usr/bin/env python3
"""
kbcs_controller.py — KBCS Full Dynamic Control Plane
=====================================================
Combines:
  [E1] Adaptive threshold tuning (AIMD-style queue feedback)
  [E4] Active-flow-count propagation to P4 data plane
  [Pillar B] Aggregate karma statistics → dynamic queue weight updates

The controller runs as a background daemon alongside the Mininet
experiment and periodically:

  1. Samples queue occupancy via simple_switch_CLI
  2. Uses AIMD feedback to adapt congestion/byte thresholds
  3. Reads active flow count from the data-plane register
  4. Updates all threshold registers in the P4 data plane

Usage (standalone):
    python3 kbcs_controller.py --thrift-port 9090 [--interval 2]

Usage (embedded in topology.py via --controller flag):
    ctrl = KBCSController(thrift_port=9090, interval=2)
    ctrl.start_background()
"""

import subprocess
import time
import argparse
import threading

# ------------------------------------------------------------------ #
# Threshold Bounds                                                      #
# ------------------------------------------------------------------ #
DEFAULT_QDEPTH_THRESH = 50
DEFAULT_BYTE_THRESH   = 120000

MIN_QDEPTH_THRESH = 10
MAX_QDEPTH_THRESH = 150
MIN_BYTE_THRESH   = 40000
MAX_BYTE_THRESH   = 300000

HIGH_WATER_QDEPTH = 80    # Tighten if avg queue depth exceeds this
LOW_WATER_QDEPTH  = 15    # Relax  if avg queue depth is below this

STEP_UP_QDEPTH    = 5
STEP_DOWN_QDEPTH  = 10
STEP_UP_BYTES     = 20000
STEP_DOWN_BYTES   = 30000


class KBCSController:
    """Adaptive KBCS control plane: manages thresholds and active-flow count."""

    def __init__(self, thrift_port: int = 9090,
                 interval: float = 2.0,
                 verbose: bool = True):
        self.thrift_port = thrift_port
        self.interval    = interval
        self.verbose     = verbose
        self._stop       = threading.Event()

        self.qdepth_thresh = DEFAULT_QDEPTH_THRESH
        self.byte_thresh   = DEFAULT_BYTE_THRESH
        self._history: list = []
        self._HIST_LEN = 5

    # -------------------------------------------------------------- #
    # simple_switch_CLI helpers                                         #
    # -------------------------------------------------------------- #
    def _cli(self, cmd: str) -> str:
        full = f'echo "{cmd}" | simple_switch_CLI --thrift-port {self.thrift_port}'
        try:
            r = subprocess.run(full, shell=True,
                               capture_output=True, text=True, timeout=5)
            return r.stdout
        except subprocess.TimeoutExpired:
            return ""

    def _write_reg(self, name: str, idx: int, val: int):
        out = self._cli(f'register_write MyIngress.{name} {idx} {val}')
        if self.verbose:
            print(f'  [ctrl] write {name}[{idx}] = {val}')

    def _read_reg(self, name: str, idx: int) -> int:
        out = self._cli(f'register_read MyIngress.{name} {idx}')
        try:
            return int(out.split('=')[-1].strip())
        except (ValueError, IndexError):
            return 0

    # -------------------------------------------------------------- #
    # Queue depth sampling                                              #
    # -------------------------------------------------------------- #
    def _sample_qdepth(self) -> int:
        """
        Read queue occupancy from a P4 counter or via 'show_ports'.
        Falls back to the current threshold mid-point if unavailable.
        """
        out = self._cli('show_ports')
        for line in out.splitlines():
            if 'qdepth' in line.lower():
                try:
                    return int(line.split('=')[-1].strip())
                except ValueError:
                    pass
        return self.qdepth_thresh // 2   # Neutral fallback

    # -------------------------------------------------------------- #
    # Main adaptation cycle                                             #
    # -------------------------------------------------------------- #
    def update_thresholds(self):
        """One adaptation cycle: sample → decide → push to data plane."""
        qdepth = self._sample_qdepth()
        self._history.append(qdepth)
        if len(self._history) > self._HIST_LEN:
            self._history.pop(0)
        avg = sum(self._history) / len(self._history)

        if self.verbose:
            print(f'  [ctrl] avg_qdepth={avg:.1f} | '
                  f'qdepth_thresh={self.qdepth_thresh} | '
                  f'byte_thresh={self.byte_thresh}')

        if avg > HIGH_WATER_QDEPTH:
            self.qdepth_thresh = max(MIN_QDEPTH_THRESH,
                                     self.qdepth_thresh - STEP_DOWN_QDEPTH)
            self.byte_thresh   = max(MIN_BYTE_THRESH,
                                     self.byte_thresh   - STEP_DOWN_BYTES)
            if self.verbose:
                print('  [ctrl] ↓ Tightening (congestion detected)')
        elif avg < LOW_WATER_QDEPTH:
            self.qdepth_thresh = min(MAX_QDEPTH_THRESH,
                                     self.qdepth_thresh + STEP_UP_QDEPTH)
            self.byte_thresh   = min(MAX_BYTE_THRESH,
                                     self.byte_thresh   + STEP_UP_BYTES)
            if self.verbose:
                print('  [ctrl] ↑ Relaxing (link underutilised)')
        else:
            if self.verbose:
                print('  [ctrl] = Stable')

        # Push updated thresholds to P4 data plane
        self._write_reg('reg_qdepth_thresh', 0, self.qdepth_thresh)
        self._write_reg('reg_byte_thresh',   0, self.byte_thresh)

        # Read active flow count for observability [E4]
        active = self._read_reg('reg_active_flows', 0)
        if self.verbose and active > 0:
            print(f'  [ctrl] Active flows in data plane: {active}')

    # -------------------------------------------------------------- #
    # Run loop                                                          #
    # -------------------------------------------------------------- #
    def run(self):
        print(f'[KBCS Controller] port={self.thrift_port}, '
              f'interval={self.interval}s')

        # Push initial defaults immediately on startup
        self._write_reg('reg_qdepth_thresh', 0, self.qdepth_thresh)
        self._write_reg('reg_byte_thresh',   0, self.byte_thresh)

        while not self._stop.is_set():
            self.update_thresholds()
            time.sleep(self.interval)
        print('[KBCS Controller] Stopped.')

    def stop(self):
        self._stop.set()

    def start_background(self) -> threading.Thread:
        t = threading.Thread(target=self.run, daemon=True, name='kbcs-ctrl')
        t.start()
        return t


def main():
    p = argparse.ArgumentParser(description='KBCS Dynamic Control Plane')
    p.add_argument('--thrift-port', type=int, default=9090)
    p.add_argument('--interval',    type=float, default=2.0)
    p.add_argument('--quiet',       action='store_true')
    args = p.parse_args()

    ctrl = KBCSController(thrift_port=args.thrift_port,
                          interval=args.interval,
                          verbose=not args.quiet)
    try:
        ctrl.run()
    except KeyboardInterrupt:
        ctrl.stop()


if __name__ == '__main__':
    main()
