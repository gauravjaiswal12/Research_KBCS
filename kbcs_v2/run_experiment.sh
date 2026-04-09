#!/bin/bash
# ============================================================================
# KBCS v2 — Full Experiment Runner
# ============================================================================
# Topology (from docs/kbcs_topology.png):
#   8 sender hosts:  h1-h4 → S1 (Access), h5-h8 → S2 (Access)
#   4 server hosts:  h9-h10 → S3 (Aggregation), h11-h12 → S4 (Aggregation)
#   4 switches:      S1, S2 (Access/KBCS), S3, S4 (Aggregation/KBCS)
#   Bottleneck:      S1↔S3, S1↔S4, S2↔S3, S2↔S4 at 10 Mbps
#
# Steps:
#   1. Load TCP kernel modules
#   2. Start Docker (InfluxDB + Grafana)
#   3. Clean old Mininet state
#   4. Start P4 topology
#   5. Start iperf traffic (via Mininet CLI)
#   6. Start Grafana telemetry feeder
#   7. Start RL Q-Learning controller
#   8. Start Flask live dashboard
#
# Usage:
#   cd ~/kbcs_v2 && bash run_experiment.sh [--duration 300]
#
# Ports (inside VM — forward with SSH for Windows access):
#   localhost:3000  — Grafana
#   localhost:5000  — Live ObsCenter
#   localhost:8086  — InfluxDB
# ============================================================================

cd "$(dirname "$0")"
KBCS_DIR="$(pwd)"

# Cache sudo password
echo "p4" | sudo -S true >/dev/null 2>&1

# Duration
DURATION=${1:-300}
if [[ "$1" == "--duration" ]]; then
    DURATION=${2:-300}
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          KBCS v2 — Full Experiment Runner               ║"
echo "║          Duration: ${DURATION}s                                  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Load TCP kernel modules ──────────────────────────────────────────
echo "[1/8] Loading TCP congestion control kernel modules..."
sudo modprobe tcp_bbr      2>/dev/null && echo "  ✓ tcp_bbr"      || echo "  ⚠ tcp_bbr (skip)"
sudo modprobe tcp_vegas    2>/dev/null && echo "  ✓ tcp_vegas"    || echo "  ⚠ tcp_vegas (skip)"
sudo modprobe tcp_illinois 2>/dev/null && echo "  ✓ tcp_illinois" || echo "  ⚠ tcp_illinois (skip)"
echo "  Available: $(cat /proc/sys/net/ipv4/tcp_available_congestion_control)"
echo ""

# ── Step 2: Start Docker (InfluxDB + Grafana) ───────────────────────────────
echo "[2/8] Starting Docker (InfluxDB + Grafana)..."
sudo docker-compose down -v 2>/dev/null || true
sudo docker-compose up -d 2>&1 | tail -3
echo "  Waiting for InfluxDB..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8086/ping > /dev/null 2>&1; then
        echo "  ✓ InfluxDB ready"
        break
    fi
    sleep 1
done
echo ""

# ── Step 3: Clean old Mininet state ─────────────────────────────────────────
echo "[3/8] Cleaning old Mininet state..."
sudo mn -c > /dev/null 2>&1 || true
sudo killall -9 simple_switch_grpc 2>/dev/null || true
sudo rm -rf pcaps/* logs/*
sleep 2
echo "  ✓ Clean"
echo ""

# ── Step 4: Start P4 topology ────────────────────────────────────────────────
echo "[4/8] Starting P4 topology (4 switches, 8 hosts + 4 servers)..."
source /home/p4/src/p4dev-python-venv/bin/activate 2>/dev/null || true

# Start Mininet in background — it will remain running and process traffic natively
echo "[4/8 & 5/8] Starting P4 topology and iperf traffic (native Mininet CLI) ..."
cat << EOF | sudo PATH="$PATH" python3 /home/p4/tutorials/utils/run_exercise.py -t kbcs-topo/topology.json -j p4src/kbcs_v2.json -b simple_switch_grpc > /tmp/kbcs_mininet.log 2>&1 &
h9 iperf -s -D
h10 iperf -s -D
h11 iperf -s -D
h12 iperf -s -D
h1 iperf -c 10.0.3.1 -t $DURATION -P 1 &
h2 iperf -c 10.0.3.1 -t $DURATION -P 4 &
h3 iperf -c 10.0.3.2 -t $DURATION -P 1 &
h4 iperf -c 10.0.3.2 -t $DURATION -P 3 &
h5 iperf -c 10.0.4.1 -t $DURATION -P 1 &
h6 iperf -c 10.0.4.1 -t $DURATION -P 4 &
h7 iperf -c 10.0.4.2 -t $DURATION -P 1 &
h8 iperf -c 10.0.4.2 -t $DURATION -P 3 &
sh sleep $((DURATION + 5))
exit
EOF
MININET_PID=$!
echo "  Mininet PID: $MININET_PID"

# Wait for switches
echo "  Waiting for switches to boot..."
for port in 9090 9091 9092 9093; do
    for i in $(seq 1 60); do
        if echo "" | simple_switch_CLI --thrift-port $port > /dev/null 2>&1; then
            echo "  ✓ Switch on port $port ready"
            break
        fi
        sleep 1
    done
done
sleep 3
echo ""

# ── Step 6: Start Grafana telemetry feeder ───────────────────────────────────
echo "[6/8] Starting Grafana telemetry feeder..."
python3 telemetry/grafana_feeder.py > /tmp/kbcs_feeder.log 2>&1 &
FEEDER_PID=$!
echo "  ✓ Feeder PID: $FEEDER_PID"
echo ""

# ── Step 7: Start RL controller ─────────────────────────────────────────────
echo "[7/8] Starting Q-Learning RL controller..."
python3 controller/rl_controller.py \
    --flows 1,2,3,4 \
    --duration $DURATION \
    --switches 9090,9091 \
    --reset > /tmp/kbcs_rl.log 2>&1 &
RL_PID=$!
echo "  ✓ RL controller PID: $RL_PID"
echo ""

# ── Step 8: Start Flask live dashboard ───────────────────────────────────────
echo "[8/8] Starting Flask live dashboard..."
python3 dashboard/live_dashboard.py > /tmp/kbcs_dashboard.log 2>&1 &
DASH_PID=$!
echo "  ✓ Dashboard PID: $DASH_PID"
echo ""

# ── Summary ──────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                 EXPERIMENT RUNNING                      ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Grafana:        http://localhost:3000                  ║"
echo "║  Live ObsCenter: http://localhost:5000                  ║"
echo "║  Duration:       ${DURATION}s                                  ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  PIDs:                                                  ║"
echo "║    Mininet  : $MININET_PID                                    ║"
echo "║    Feeder   : $FEEDER_PID                                     ║"
echo "║    RL Ctrl  : $RL_PID                                     ║"
echo "║    Dashboard: $DASH_PID                                     ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  From Windows (SSH port forward):                       ║"
echo "║    ssh -L 3000:localhost:3000 -L 5000:localhost:5000 \   ║"
echo "║        -p 2222 p4@localhost                             ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Logs:                                                  ║"
echo "║    tail -f /tmp/kbcs_feeder.log                         ║"
echo "║    tail -f /tmp/kbcs_rl.log                             ║"
echo "║    tail -f /tmp/kbcs_dashboard.log                      ║"
echo "║    tail -f /tmp/kbcs_mininet.log                        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Press Ctrl+C to stop, or wait ${DURATION}s..."

# Wait for duration, then cleanup
sleep $DURATION

echo ""
echo "[cleanup] Experiment complete. Collecting results..."

# Print throughput results
echo ""
echo "═══════════════════ THROUGHPUT RESULTS ═══════════════════"
for h in h1 h2 h3 h4 h5 h6 h7 h8; do
    if [ -f /tmp/kbcs_${h}.log ]; then
        echo "--- $h ---"
        tail -3 /tmp/kbcs_${h}.log
    fi
done

# Print final karma values
echo ""
echo "═══════════════════ FINAL KARMA VALUES ═══════════════════"
echo "  --- S1 (Access, h1-h4) ---"
for fid in 1 2 3 4; do
    karma=$(echo "register_read MyIngress.reg_karma $fid" | simple_switch_CLI --thrift-port 9090 2>/dev/null | grep '=' | awk -F'= ' '{print $2}')
    echo "    Flow $fid: karma=$karma"
done
echo "  --- S2 (Access, h5-h8) ---"
for fid in 1 2 3 4; do
    karma=$(echo "register_read MyIngress.reg_karma $fid" | simple_switch_CLI --thrift-port 9091 2>/dev/null | grep '=' | awk -F'= ' '{print $2}')
    echo "    Flow $((fid+4)): karma=$karma"
done

# Cleanup background processes
kill $FEEDER_PID $RL_PID $DASH_PID 2>/dev/null || true

echo ""
echo "Done. Docker containers (Grafana/InfluxDB) still running for review."
echo "Run 'sudo docker-compose down' to stop them."
