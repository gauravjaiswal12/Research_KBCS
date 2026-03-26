#!/usr/bin/env python3
"""
KBCS Meta-RL Tuner — Phase 6 (Monitor + Conservative Tuning)

Monitors data-plane telemetry and tunes ONLY the penalty/reward
parameters conservatively. Does NOT touch fair_bytes (kept at
mathematical fair share).
"""

import time
import sys
import subprocess
import re

def run_cli_batch(cmds):
    try:
        proc = subprocess.run(
            ['simple_switch_CLI', '--thrift-port', '9090'],
            input=cmds,
            capture_output=True,
            text=True,
            timeout=2
        )
        return proc.stdout
    except Exception as e:
        print(f"CLI Error: {e}")
        return ""

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 rl_controller.py <duration> <num_flows>")
        sys.exit(1)

    duration = int(sys.argv[1])
    num_flows = int(sys.argv[2])

    # KBCS FIX: Balanced penalty/reward ratio (2:1 instead of 5:1)
    # This prevents the RED zone death spiral where karma degrades too fast
    penalty_amt = 8   # Reduced from 10
    reward_amt = 4    # Increased from 2
    EPOCH_SECS = 2.0

    print(f"--- KBCS Meta-RL Tuner Started (Monitor Mode) ---")
    print(f"  Flows: {num_flows}, Epoch: {EPOCH_SECS}s")
    print(f"  penalty={penalty_amt}, reward={reward_amt}")

    # Initialize P4 Registers
    init_cmds  = f"register_write reg_penalty_amt 0 {penalty_amt}\n"
    init_cmds += f"register_write reg_reward_amt 0 {reward_amt}\n"
    run_cli_batch(init_cmds)

    # State tracking
    prev_pkts = {i: 0 for i in range(1, num_flows + 1)}
    prev_drops = {i: 0 for i in range(1, num_flows + 1)}
    prev_ecns = {i: 0 for i in range(1, num_flows + 1)}

    start_time = time.time()
    prev_time = start_time
    epoch = 0
    jfi_history = []

    while time.time() - start_time < duration:
        current_time = time.time()
        dt = current_time - prev_time

        if dt < EPOCH_SECS:
            time.sleep(0.1)
            continue

        prev_time = current_time
        epoch += 1

        # READ Telemetry
        read_cmds = ""
        for i in range(1, num_flows + 1):
            read_cmds += f"register_read reg_total_pkts {i}\n"
            read_cmds += f"register_read reg_drops {i}\n"
            read_cmds += f"register_read reg_ecn_marks {i}\n"

        out = run_cli_batch(read_cmds)
        values = re.findall(r'=\s*(\d+)', out)

        if len(values) < 3 * num_flows:
            continue

        flow_rates = []
        log_parts = []
        for i in range(1, num_flows + 1):
            idx = (i - 1) * 3
            cur_p = int(values[idx])
            cur_d = int(values[idx + 1])
            cur_e = int(values[idx + 2])

            delta_pkts = cur_p - prev_pkts[i]
            delta_drops = cur_d - prev_drops[i]
            delta_ecns = cur_e - prev_ecns[i]

            # Forwarded packets (ingress - drops)
            delta_fwd = max(0, delta_pkts - delta_drops)
            rate_mbps = (delta_fwd * 1500 * 8) / (dt * 1e6)
            flow_rates.append(rate_mbps)

            prev_pkts[i] = cur_p
            prev_drops[i] = cur_d
            prev_ecns[i] = cur_e

            log_parts.append(f"F{i}:{rate_mbps:.2f}M (D:{delta_drops} E:{delta_ecns})")

        # Compute JFI
        sum_r = sum(flow_rates)
        sum_sq = sum(x*x for x in flow_rates)
        jfi = (sum_r * sum_r) / (num_flows * sum_sq) if sum_sq > 0 else 0.0
        jfi_history.append(jfi)

        # Conservative Meta-Tuning:
        # Only adjust penalty if JFI trend is consistently low over 3+ epochs
        action = "MONITOR"
        if len(jfi_history) >= 3:
            avg_jfi = sum(jfi_history[-3:]) / 3
            if avg_jfi < 0.70:
                penalty_amt = min(30, penalty_amt + 2)
                action = f"INCREASE penalty to {penalty_amt}"
                run_cli_batch(f"register_write reg_penalty_amt 0 {penalty_amt}\n")
            elif avg_jfi > 0.90:
                penalty_amt = max(5, penalty_amt - 1)
                action = f"DECREASE penalty to {penalty_amt}"
                run_cli_batch(f"register_write reg_penalty_amt 0 {penalty_amt}\n")

        elapsed = current_time - start_time
        print(f"[E{epoch:02d} T={elapsed:04.1f}s] JFI={jfi:.4f} | {action}")
        print("  " + " | ".join(log_parts))

    if jfi_history:
        avg = sum(jfi_history) / len(jfi_history)
        print(f"\n--- Average JFI across {len(jfi_history)} epochs: {avg:.4f} ---")
    print("--- KBCS Meta-RL Tuner Finished ---")

if __name__ == "__main__":
    main()
