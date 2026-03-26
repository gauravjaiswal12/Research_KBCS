import paramiko
import scp
import os
import sys
import time
import json
import urllib.request
import csv

def run_cmd(ssh, cmd, show=True):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    exit_status = stdout.channel.recv_exit_status()
    if show and out.strip():
        print(out.strip())
    if show and err.strip():
        for line in err.strip().split('\n'):
            if 'Warning' not in line and 'quantum' not in line:
                print("  stderr:", line)
    return out, err, exit_status

def run_sudo(ssh, cmd, show=True, timeout=300):
    print(f"  $ sudo {cmd}")
    stdin, stdout, stderr = ssh.exec_command(
        f"echo 'p4' | sudo -S bash -c '{cmd}'", timeout=timeout, get_pty=True
    )
    out = stdout.read().decode()
    err = stderr.read().decode()
    if show and out.strip():
        for line in out.strip().split('\n'):
            if '[sudo]' not in line and line.strip() != 'p4':
                print(line)
    return out, err, stdout.channel.recv_exit_status()

def push_telemetry_to_influxdb(local_dir):
    now_ns = int(time.time() * 1_000_000_000)
    lines = []
    
    # === SOURCE 1: karma_log.csv (Dynamic N-Flows) ===
    karma_file = os.path.join(local_dir, "results", "karma_log.csv")
    if os.path.exists(karma_file):
        with open(karma_file, 'r') as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            if headers:
                rows = list(reader)
                if rows:
                    max_time_sec = max(float(r[0]) for r in rows)
                    
                    # Map header indices (e.g. CUBIC_0_karma) -> { 'CUBIC_0': {'karma': idx, 'qdepth': idx, ...} }
                    flow_cols = {}
                    for i, h in enumerate(headers):
                        if h == 'time_sec': continue
                        parts = h.split('_')
                        if len(parts) >= 3:
                            flow = f"{parts[0]}_{parts[1]}"
                            metric = '_'.join(parts[2:])
                            if flow not in flow_cols:
                                flow_cols[flow] = {}
                            flow_cols[flow][metric] = i
                    
                    for r in rows:
                        t_sec = float(r[0])
                        point_ts = now_ns - int((max_time_sec - t_sec) * 1_000_000_000)
                        
                        for flow, cols in flow_cols.items():
                            k_idx = cols.get('karma')
                            q_idx = cols.get('qdepth')
                            d_idx = cols.get('drops')
                            if k_idx and q_idx and d_idx:
                                karma = int(float(r[k_idx])) if r[k_idx] else 0
                                qdepth = int(float(r[q_idx])) if r[q_idx] else 0
                                drops = int(float(r[d_idx])) if r[d_idx] else 0
                                lines.append(f"telemetry,flow={flow} karma={karma}i,qdepth={qdepth}i,dropped={drops}i {point_ts}")
                                
                    print(f"  Loaded {len(rows)} karma samples (x {len(flow_cols)} flows) from karma_log.csv")

    # === SOURCE 2: telemetry.json (PCAP hardware INT data) ===
    telemetry_file = os.path.join(local_dir, "results", "telemetry.json")
    if os.path.exists(telemetry_file):
        with open(telemetry_file, 'r') as f:
            records = json.load(f)
        if records:
            timestamps = [r['ts'] for r in records]
            ts_min, ts_max = min(timestamps), max(timestamps)
            ts_range = max(ts_max - ts_min, 1)
            
            for r in records:
                relative_pos = (r['ts'] - ts_min) / ts_range
                spread_seconds = max(len(records) // 2, 10)
                point_ts = now_ns - int((1.0 - relative_pos) * spread_seconds * 1_000_000_000)
                lines.append(f"telemetry,flow={r['flow']} qdepth={r['qdepth']}i,dropped={r['dropped']}i {point_ts}")
            
            print(f"  Loaded {len(records)} hardware INT records from PCAP")

    # === SOURCE 3: last_test.json (Summary metrics) ===
    summary_file = os.path.join(local_dir, "results", "last_test.json")
    if os.path.exists(summary_file):
        with open(summary_file, 'r') as f:
            summary = json.load(f)
        
        jfi = summary.get('jain_index', 0)
        sum_str = f"summary jfi={jfi}"
        
        # Add legacy fallback metrics for static Grafana panels
        sum_str += f",cubic_mbps={summary.get('cubic_mbps', 0)},bbr_mbps={summary.get('bbr_mbps', 0)}"
        
        # Add dynamic N-flow throughputs
        for flow in summary.get('flows', []):
            name = flow['name']
            cca = flow['cca'].upper()
            mbps = flow['mbps']
            sum_str += f",mbps_{name}_{cca}={mbps}"
            
        sum_str += f" {now_ns}"
        lines.append(sum_str)
        print(f"  Loaded summary: JFI={jfi}, {len(summary.get('flows', []))} flows")

    if not lines:
        print("No telemetry data to push.")
        return

    payload = "\n".join(lines).encode('utf-8')

    try:
        urllib.request.urlopen(urllib.request.Request(
            "http://localhost:8086/query", data=b"q=CREATE DATABASE kbcs_telemetry", method='POST'
        ), timeout=5)
    except: pass

    try:
        req = urllib.request.Request("http://localhost:8086/write?db=kbcs_telemetry", data=payload, method='POST')
        resp = urllib.request.urlopen(req, timeout=30)
        print(f"\n*** Pushed {len(lines)} telemetry data points to InfluxDB (HTTP {resp.status}) ***")
    except Exception as e:
        print(f"Failed to push to InfluxDB: {e}")

def upload_and_run(run_traffic=False, duration=30, num_flows=2, ccas="cubic,bbr"):
    host, port = "localhost", 2222
    username, password = "p4", "p4"
    local_dir, remote_dir = "kbcs", "/home/p4/kbcs"

    print("Connecting to VM...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, port, username, password)
        print("Connected.")

        print("\nCleaning up previous state...")
        run_cmd(ssh, "echo 'p4' | sudo -S mn -c 2>/dev/null; echo 'p4' | sudo -S killall simple_switch 2>/dev/null; sleep 1; echo done")

        print("\nCleaning old files on VM...")
        run_cmd(ssh, f"rm -f {remote_dir}/topology.py {remote_dir}/Makefile {remote_dir}/runtime.json")
        run_cmd(ssh, f"echo 'p4' | sudo -S rm -rf {remote_dir}/p4src {remote_dir}/build {remote_dir}/results")
        run_cmd(ssh, f"mkdir -p {remote_dir}/p4src {remote_dir}/results {remote_dir}/build {remote_dir}/logs {remote_dir}/pcaps")

        print("Uploading files...")
        with scp.SCPClient(ssh.get_transport()) as scp_client:
            scp_client.put(local_dir, remote_path="/home/p4", recursive=True)
        print("Upload complete.")

        print("\n--- Installing Dashboard Dependencies on VM ---")
        run_cmd(ssh, "echo 'p4' | sudo -S apt-get update && echo 'p4' | sudo -S apt-get install -y python3-scapy python3-requests python3-pandas python3-flask python3-matplotlib python3-influxdb python3-influxdb-client")
        
        # Install extra TCP CCA kernel modules (vegas, illinois, htcp, etc.)
        print("\n--- Installing Extra TCP CCA Modules ---")
        run_sudo(ssh, "apt-get install -y linux-modules-extra-$(uname -r) 2>/dev/null || true")
        run_sudo(ssh, "modprobe tcp_vegas tcp_illinois tcp_htcp tcp_bbr 2>/dev/null || true")

        print("\n--- Building P4 program (force rebuild) ---")
        out, err, status = run_cmd(ssh, f"cd {remote_dir} && make clean && make build 2>&1")
        if status != 0:
            print(f"Build FAILED (exit {status})")
            sys.exit(status)
        print("Build successful!")

        cmd_args = f"--behavioral-exe simple_switch --json build/kbcs.json --num-flows {num_flows} --ccas {ccas}"
        
        print("\n--- Running pingall test ---")
        out, err, status = run_sudo(ssh, f"cd {remote_dir} && PYTHONPATH={remote_dir}/utils python3 topology.py {cmd_args} --test-only 2>&1", timeout=60)

        if "0% dropped" in out: print("\n*** PINGALL TEST PASSED! ***")
        else: print(f"\n*** Pingall test result (exit {status}) ***")

        if run_traffic:
            time.sleep(2)
            run_cmd(ssh, "echo 'p4' | sudo -S mn -c 2>/dev/null; echo 'p4' | sudo -S killall simple_switch 2>/dev/null; sleep 2; echo done")

            print(f"\n--- Running traffic test ({duration}s, {num_flows} flows) ---")
            out, err, status = run_sudo(ssh, f"cd {remote_dir} && PYTHONPATH={remote_dir}/utils python3 topology.py {cmd_args} --traffic --duration {duration} 2>&1", timeout=300)

            if "Jain" in out: print("\n*** TRAFFIC TEST COMPLETED! ***")
            else: print(f"\n*** Traffic test finished (exit {status}) ***")

        print("\n--- Downloading Results from VM ---")
        try:
            with scp.SCPClient(ssh.get_transport()) as scp_client:
                os.makedirs(f"{local_dir}/results", exist_ok=True)
                scp_client.get(f"{remote_dir}/results", local_path=local_dir, recursive=True)
            print("Successfully downloaded results/ to local kbcs/ folder.")
        except Exception as e:
            print(f"Failed to download results: {e}")

        if run_traffic:
            push_telemetry_to_influxdb(local_dir)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        ssh.close()

if __name__ == "__main__":
    traffic = "--traffic" in sys.argv
    duration = 30
    num_flows = 2
    ccas = "cubic,bbr"
    for i, arg in enumerate(sys.argv):
        if arg == "--duration" and i + 1 < len(sys.argv): duration = int(sys.argv[i + 1])
        if arg == "--num-flows" and i + 1 < len(sys.argv): num_flows = int(sys.argv[i + 1])
        if arg == "--ccas" and i + 1 < len(sys.argv): ccas = sys.argv[i + 1]
        
    upload_and_run(run_traffic=traffic, duration=duration, num_flows=num_flows, ccas=ccas)
