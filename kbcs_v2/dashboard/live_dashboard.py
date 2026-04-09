#!/usr/bin/env python3
"""
KBCS v2 — Live Dashboard + Topology Visualizer
================================================
Replaces both Grafana and the p4-utils web topology viewer.

Polls BMv2 switch registers every 500ms via Thrift CLI and serves a
premium web dashboard at http://0.0.0.0:5000 showing:
  * Live animated 4-switch cross-linked topology with packet flows
  * Real-time karma scores for all 4 sender CCAs
  * Color zone distribution (GREEN/YELLOW/RED)
  * Drop rate per flow
  * Throughput fairness (JFI) gauge

Usage (while Mininet is running):
  python3 dashboard/live_dashboard.py

Then open http://localhost:5000 in browser (or from Windows via port forward).
"""

import os
import json
import time
import threading
import subprocess
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ── Global state updated by background poller ────────────────────────────────
live_data = {
    "flows": {},
    "history": [],      # list of snapshots — up to 120 entries (60 seconds)
    "jfi": 0.0,
    "total_drops": 0,
    "total_fwd": 0,
    "last_update": 0,
}
data_lock = threading.Lock()

FLOW_NAMES = {
    1: "CUBIC",   2: "BBR",
    3: "Vegas",   4: "Illinois",
}

THRIFT_PORTS = [9090, 9091, 9092, 9093]
SWITCH_NAMES = ["s1", "s2", "s3", "s4"]

# ── Thrift register reader ──────────────────────────────────────────────────

def read_register(thrift_port, register_name, index):
    """Read a single register value from a BMv2 switch via simple_switch_CLI."""
    try:
        cmd = f"echo 'register_read {register_name} {index}' | simple_switch_CLI --thrift-port {thrift_port} 2>/dev/null"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2)
        # Parse output like: "MyIngress.reg_karma[1]= 85"
        for line in result.stdout.split('\n'):
            if '=' in line and register_name.split('.')[-1] in line:
                val_str = line.split('=')[-1].strip()
                return int(val_str)
    except Exception:
        pass
    return 0


def poll_switch_registers():
    """Background thread: poll all switch registers every 500ms."""
    while True:
        try:
            snapshot = {"ts": time.time(), "flows": {}}

            # Read from S1 (thrift 9090) — flows 1-4 (h1-h4)
            total_fwd_bytes = 0
            throughputs = []

            for fid in range(1, 5):
                karma = read_register(9090, "MyIngress.reg_karma", fid)
                drops = read_register(9090, "MyIngress.reg_drops", fid)
                fwd = read_register(9090, "MyIngress.reg_forwarded_bytes", fid)

                # Determine color
                if karma >= 76:
                    color = "GREEN"
                elif karma >= 41:
                    color = "YELLOW"
                else:
                    color = "RED"

                snapshot["flows"][fid] = {
                    "name": FLOW_NAMES.get(fid, f"Flow {fid}"),
                    "karma": karma,
                    "color": color,
                    "drops": drops,
                    "fwd_bytes": fwd,
                }
                total_fwd_bytes += fwd
                throughputs.append(fwd)

            # Compute JFI
            if len(throughputs) > 0 and sum(throughputs) > 0:
                n = len(throughputs)
                sum_x = sum(throughputs)
                sum_x2 = sum(x*x for x in throughputs)
                jfi = (sum_x ** 2) / (n * sum_x2) if sum_x2 > 0 else 1.0
            else:
                jfi = 0.0

            with data_lock:
                live_data["flows"] = snapshot["flows"]
                live_data["jfi"] = round(jfi, 4)
                live_data["total_drops"] = sum(f["drops"] for f in snapshot["flows"].values())
                live_data["total_fwd"] = total_fwd_bytes
                live_data["last_update"] = time.time()

                # History — keep last 120 samples
                live_data["history"].append({
                    "ts": round(time.time(), 1),
                    "flows": {str(k): v["karma"] for k, v in snapshot["flows"].items()},
                })
                if len(live_data["history"]) > 120:
                    live_data["history"] = live_data["history"][-120:]

        except Exception as e:
            print(f"[poller] Error: {e}")

        time.sleep(0.5)


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.route('/api/live')
def api_live():
    with data_lock:
        return jsonify(live_data)


# ── Main page (inline HTML — no external template files needed) ───────────────

DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KBCS v2 — Live ObsCenter</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0a0e17;
            --panel: rgba(16, 22, 36, 0.85);
            --cyan: #00e5ff;
            --green: #00e676;
            --yellow: #ffab00;
            --red: #ff1744;
            --purple: #b388ff;
            --txt1: #e6edf3;
            --txt2: #8b949e;
            --glow-cyan: rgba(0,229,255,0.25);
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Inter', sans-serif;
            background: var(--bg);
            background-image:
                radial-gradient(ellipse at 20% 0%, rgba(0,229,255,0.08) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 100%, rgba(179,136,255,0.06) 0%, transparent 50%);
            color: var(--txt1);
            min-height: 100vh;
            padding: 1.5rem 2rem;
        }

        /* ── Header ── */
        header {
            display:flex; justify-content:space-between; align-items:center;
            margin-bottom:1.5rem; padding-bottom:1rem;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        h1 { font-size:1.75rem; font-weight:700; letter-spacing:-0.03em;
             background: linear-gradient(135deg, var(--cyan), var(--purple));
             -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
        .live-badge {
            display:inline-flex; align-items:center; gap:6px;
            padding:6px 14px; border-radius:999px; font-size:0.8rem; font-weight:600;
            background:rgba(0,230,118,0.1); border:1px solid var(--green);
            box-shadow:0 0 12px rgba(0,230,118,0.15);
        }
        .live-dot { width:8px; height:8px; border-radius:50%; background:var(--green);
                    box-shadow:0 0 6px var(--green); animation: pulse 1.5s infinite; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

        /* ── Panels ── */
        .panel {
            background:var(--panel); backdrop-filter:blur(12px);
            border:1px solid rgba(255,255,255,0.04); border-radius:14px;
            padding:1.2rem 1.5rem; box-shadow:0 6px 24px rgba(0,0,0,0.4);
        }
        .panel-title {
            font-size:0.8rem; font-weight:600; text-transform:uppercase;
            letter-spacing:0.06em; color:var(--txt2); margin-bottom:0.8rem;
        }

        /* ── Layout ── */
        .top-row { display:grid; grid-template-columns:repeat(4,1fr); gap:1rem; margin-bottom:1rem; }
        .mid-row { display:grid; grid-template-columns:1fr 1fr; gap:1rem; margin-bottom:1rem; }
        .bot-row { display:grid; grid-template-columns:1fr; gap:1rem; }

        /* ── Karma cards ── */
        .karma-val { font-size:2.8rem; font-weight:700; line-height:1; }
        .karma-sub { font-size:0.85rem; color:var(--txt2); margin-top:4px; }
        .color-badge {
            display:inline-block; padding:2px 10px; border-radius:999px;
            font-size:0.7rem; font-weight:700; letter-spacing:0.05em; margin-top:6px;
        }
        .cg { color:var(--green); text-shadow:0 0 8px rgba(0,230,118,0.4); }
        .cy { color:var(--yellow); text-shadow:0 0 8px rgba(255,171,0,0.4); }
        .cr { color:var(--red); text-shadow:0 0 8px rgba(255,23,68,0.4); }
        .bg-g { background:rgba(0,230,118,0.15); color:var(--green); }
        .bg-y { background:rgba(255,171,0,0.15); color:var(--yellow); }
        .bg-r { background:rgba(255,23,68,0.15); color:var(--red); }

        /* ── Topology ── */
        .topo-panel { position:relative; height:380px; overflow:hidden;
            background: radial-gradient(circle at center, rgba(16,22,36,0.9) 0%, var(--bg) 100%);
        }
        #topoCanvas { width:100%; height:100%; }

        /* ── Stats strip ── */
        .stats-strip { display:flex; gap:2rem; margin-top:0.5rem; }
        .stat-item { text-align:center; }
        .stat-num { font-size:1.8rem; font-weight:700; }
        .stat-lbl { font-size:0.75rem; color:var(--txt2); text-transform:uppercase; }

        /* ── Chart ── */
        .chart-container { height:280px; }
    </style>
</head>
<body>

<header>
    <h1>KBCS v2 — Live ObsCenter</h1>
    <div class="live-badge"><div class="live-dot"></div>LIVE</div>
</header>

<!-- Row 1: Karma score cards -->
<div class="top-row">
    <div class="panel" id="card-1">
        <div class="panel-title">Flow 1 — CUBIC</div>
        <div class="karma-val cg" id="k1">--</div>
        <div class="karma-sub">karma / 100</div>
        <div class="color-badge bg-g" id="c1">GREEN</div>
    </div>
    <div class="panel" id="card-2">
        <div class="panel-title">Flow 2 — BBR</div>
        <div class="karma-val cg" id="k2">--</div>
        <div class="karma-sub">karma / 100</div>
        <div class="color-badge bg-g" id="c2">GREEN</div>
    </div>
    <div class="panel" id="card-3">
        <div class="panel-title">Flow 3 — Vegas</div>
        <div class="karma-val cg" id="k3">--</div>
        <div class="karma-sub">karma / 100</div>
        <div class="color-badge bg-g" id="c3">GREEN</div>
    </div>
    <div class="panel" id="card-4">
        <div class="panel-title">Flow 4 — Illinois</div>
        <div class="karma-val cg" id="k4">--</div>
        <div class="karma-sub">karma / 100</div>
        <div class="color-badge bg-g" id="c4">GREEN</div>
    </div>
</div>

<!-- Row 2: Topology + Stats -->
<div class="mid-row">
    <div class="panel topo-panel">
        <div class="panel-title" style="position:absolute;top:1.2rem;left:1.5rem;z-index:5">Live Network Topology</div>
        <canvas id="topoCanvas"></canvas>
    </div>
    <div class="panel">
        <div class="panel-title">System Metrics</div>
        <div class="stats-strip" style="margin-top:1.5rem; flex-direction:column; gap:1.5rem;">
            <div class="stat-item" style="text-align:left">
                <div class="stat-num" id="jfi-val" style="color:var(--cyan)">0.000</div>
                <div class="stat-lbl">Jain's Fairness Index</div>
            </div>
            <div class="stat-item" style="text-align:left">
                <div class="stat-num" id="drop-val" style="color:var(--red)">0</div>
                <div class="stat-lbl">Total Drops</div>
            </div>
            <div class="stat-item" style="text-align:left">
                <div class="stat-num" id="fwd-val" style="color:var(--green)">0</div>
                <div class="stat-lbl">Forwarded Bytes</div>
            </div>
            <div class="stat-item" style="text-align:left; margin-top:1rem">
                <div class="stat-num" id="uptime" style="color:var(--purple);font-size:1.2rem;">--</div>
                <div class="stat-lbl">Last Update</div>
            </div>
        </div>
    </div>
</div>

<!-- Row 3: Karma Chart -->
<div class="bot-row">
    <div class="panel">
        <div class="panel-title">Karma Dynamics — Real-Time</div>
        <div class="chart-container">
            <canvas id="karmaChart"></canvas>
        </div>
    </div>
</div>

<script>
// ── Color utilities ──
const COLORS = { 1: '#ff1744', 2: '#00e5ff', 3: '#00e676', 4: '#b388ff' };
function colorClass(k) { return k >= 76 ? 'cg' : k >= 41 ? 'cy' : 'cr'; }
function badgeClass(k) { return k >= 76 ? 'bg-g' : k >= 41 ? 'bg-y' : 'bg-r'; }
function colorLabel(k) { return k >= 76 ? 'GREEN' : k >= 41 ? 'YELLOW' : 'RED'; }

// ── Chart.js setup ──
const chartCtx = document.getElementById('karmaChart').getContext('2d');
const karmaChart = new Chart(chartCtx, {
    type: 'line',
    data: {
        labels: [],
        datasets: [
            { label:'CUBIC',   data:[], borderColor:'#ff1744', backgroundColor:'rgba(255,23,68,0.05)', borderWidth:2.5, tension:0.3, pointRadius:0 },
            { label:'BBR',     data:[], borderColor:'#00e5ff', backgroundColor:'rgba(0,229,255,0.05)', borderWidth:2.5, tension:0.3, pointRadius:0 },
            { label:'Vegas',   data:[], borderColor:'#00e676', backgroundColor:'rgba(0,230,118,0.05)', borderWidth:2.5, tension:0.3, pointRadius:0 },
            { label:'Illinois',data:[], borderColor:'#b388ff', backgroundColor:'rgba(179,136,255,0.05)',borderWidth:2.5, tension:0.3, pointRadius:0 },
        ]
    },
    options: {
        responsive:true, maintainAspectRatio:false, animation:{ duration:0 },
        plugins: {
            legend: { labels: { color:'#8b949e', usePointStyle:true, pointStyle:'circle' } }
        },
        scales: {
            x: { display:true, ticks:{ color:'#555', maxTicksLimit:10 }, grid:{ color:'rgba(255,255,255,0.03)' } },
            y: { min:0, max:110, ticks:{ color:'#555' }, grid:{ color:'rgba(255,255,255,0.03)' } }
        }
    }
});

// ── Topology Canvas ──
const tc = document.getElementById('topoCanvas');
const tctx = tc.getContext('2d');
let particles = [];

function resizeTopo() { tc.width = tc.parentElement.clientWidth; tc.height = tc.parentElement.clientHeight; }
window.addEventListener('resize', resizeTopo); resizeTopo();

// Node positions (fraction of canvas)
const NODES = {
    h1: { x:0.08, y:0.2, label:'H1\nCUBIC',    color:'#ff1744', r:30 },
    h2: { x:0.08, y:0.45, label:'H2\nBBR',      color:'#00e5ff', r:30 },
    h3: { x:0.08, y:0.7, label:'H3\nVegas',     color:'#00e676', r:30 },
    h4: { x:0.08, y:0.95, label:'H4\nIllinois', color:'#b388ff', r:30 },
    s1: { x:0.32, y:0.35, label:'S1\nAccess',   color:'#00e5ff', r:38, isSwitch:true },
    s2: { x:0.32, y:0.75, label:'S2\nAccess',   color:'#00e5ff', r:38, isSwitch:true },
    s3: { x:0.68, y:0.35, label:'S3\nAgg',      color:'#ffab00', r:38, isSwitch:true },
    s4: { x:0.68, y:0.75, label:'S4\nAgg',      color:'#ffab00', r:38, isSwitch:true },
    h9: { x:0.92, y:0.2, label:'H9\nSrv1',     color:'#4caf50', r:28 },
    h10:{ x:0.92, y:0.45, label:'H10\nSrv2',    color:'#4caf50', r:28 },
    h11:{ x:0.92, y:0.7, label:'H11\nSrv3',    color:'#4caf50', r:28 },
    h12:{ x:0.92, y:0.95, label:'H12\nSrv4',    color:'#4caf50', r:28 },
};
const LINKS = [
    ['h1','s1'], ['h2','s1'], ['h3','s1'], ['h4','s1'],
    ['s1','s3'], ['s1','s4'],
    ['s2','s3'], ['s2','s4'],
    ['s3','h9'], ['s3','h10'],
    ['s4','h11'], ['s4','h12'],
];
// Which flow goes where: flow_id -> [path of node keys]
const FLOW_PATHS = {
    1: ['h1','s1','s3','h9'],
    2: ['h2','s1','s3','h10'],
    3: ['h3','s1','s4','h11'],
    4: ['h4','s1','s4','h12'],
};

let currentKarma = {1:100, 2:100, 3:100, 4:100};

class Pkt {
    constructor(path, color, dropped) {
        this.path = path; this.color = color; this.dropped = dropped;
        this.seg = 0; this.t = 0; this.speed = 0.012 + Math.random()*0.008;
        this.size = 3 + Math.random()*2;
    }
    update() {
        this.t += this.speed;
        if (this.t >= 1) { this.t = 0; this.seg++; }
        if (this.dropped && this.seg >= 1 && this.t > 0.5) return true;
        return this.seg >= this.path.length - 1;
    }
    draw(ctx, w, h) {
        if (this.seg >= this.path.length - 1) return;
        let a = NODES[this.path[this.seg]], b = NODES[this.path[this.seg+1]];
        let x = (a.x + (b.x - a.x)*this.t)*w, y = (a.y + (b.y - a.y)*this.t)*h;
        ctx.beginPath(); ctx.arc(x,y,this.size,0,Math.PI*2);
        ctx.fillStyle = this.color; ctx.shadowBlur=8; ctx.shadowColor=this.color;
        ctx.fill(); ctx.shadowBlur=0;
    }
}

function drawTopo() {
    const w = tc.width, h = tc.height;
    tctx.clearRect(0,0,w,h);

    // Draw links
    tctx.strokeStyle = 'rgba(255,255,255,0.08)'; tctx.lineWidth = 1.5;
    for (let [a,b] of LINKS) {
        tctx.beginPath();
        tctx.moveTo(NODES[a].x*w, NODES[a].y*h);
        tctx.lineTo(NODES[b].x*w, NODES[b].y*h);
        tctx.stroke();
    }

    // Spawn particles for active flows
    for (let fid = 1; fid <= 4; fid++) {
        let k = currentKarma[fid] || 100;
        let dropped = (k < 40 && Math.random() < 0.6);
        if (Math.random() < 0.12) {
            particles.push(new Pkt(FLOW_PATHS[fid], COLORS[fid], dropped));
        }
    }

    // Update & draw particles
    for (let i = particles.length-1; i >= 0; i--) {
        if (particles[i].update()) { particles.splice(i,1); continue; }
        particles[i].draw(tctx, w, h);
    }
    if (particles.length > 200) particles = particles.slice(-150);

    // Draw nodes
    for (let [id, n] of Object.entries(NODES)) {
        let x = n.x*w, y = n.y*h;
        if (n.isSwitch) {
            tctx.fillStyle = 'rgba(0,229,255,0.06)';
            tctx.strokeStyle = n.color;
            tctx.lineWidth = 2;
            let rw = 70, rh = 46;
            tctx.beginPath();
            tctx.roundRect(x-rw/2, y-rh/2, rw, rh, 8);
            tctx.fill(); tctx.stroke();
        } else {
            tctx.beginPath(); tctx.arc(x, y, n.r, 0, Math.PI*2);
            tctx.fillStyle = 'rgba(22,27,36,0.9)';
            tctx.strokeStyle = n.color; tctx.lineWidth = 2;
            tctx.fill(); tctx.stroke();
        }
        // Label
        tctx.fillStyle = '#ccc'; tctx.font = '11px Inter'; tctx.textAlign = 'center';
        let lines = n.label.split('\n');
        for (let li = 0; li < lines.length; li++) {
            tctx.fillText(lines[li], x, y - 4 + li*13);
        }
    }

    requestAnimationFrame(drawTopo);
}
drawTopo();

// ── Polling ──
let startTs = null;
async function poll() {
    try {
        const r = await fetch('/api/live');
        const d = await r.json();

        // Update karma cards
        for (let fid = 1; fid <= 4; fid++) {
            let f = d.flows[fid];
            if (!f) continue;
            let k = f.karma;
            currentKarma[fid] = k;
            document.getElementById('k'+fid).textContent = k;
            document.getElementById('k'+fid).className = 'karma-val ' + colorClass(k);
            document.getElementById('c'+fid).textContent = colorLabel(k);
            document.getElementById('c'+fid).className = 'color-badge ' + badgeClass(k);
        }

        // Update stats
        document.getElementById('jfi-val').textContent = d.jfi.toFixed(4);
        document.getElementById('drop-val').textContent = d.total_drops.toLocaleString();
        document.getElementById('fwd-val').textContent = (d.total_fwd/1024/1024).toFixed(2) + ' MB';
        if (d.last_update > 0) {
            if (!startTs) startTs = d.last_update;
            let elapsed = Math.round(d.last_update - startTs);
            document.getElementById('uptime').textContent = elapsed + 's elapsed';
        }

        // Update chart
        if (d.history && d.history.length > 0) {
            if (!startTs) startTs = d.history[0].ts;
            karmaChart.data.labels = d.history.map(h => Math.round(h.ts - startTs) + 's');
            karmaChart.data.datasets[0].data = d.history.map(h => h.flows['1'] || 0);
            karmaChart.data.datasets[1].data = d.history.map(h => h.flows['2'] || 0);
            karmaChart.data.datasets[2].data = d.history.map(h => h.flows['3'] || 0);
            karmaChart.data.datasets[3].data = d.history.map(h => h.flows['4'] || 0);
            karmaChart.update();
        }
    } catch(e) {}
}
setInterval(poll, 500);
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML)


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=" * 60)
    print("  KBCS v2 — Live ObsCenter Dashboard")
    print("  Open in browser: http://localhost:5000")
    print("=" * 60)

    # Start background poller thread
    poller = threading.Thread(target=poll_switch_registers, daemon=True)
    poller.start()

    app.run(host='0.0.0.0', port=5000, debug=False)
