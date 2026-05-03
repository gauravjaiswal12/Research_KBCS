import paramiko
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

DURATION = 3000
for i, arg in enumerate(sys.argv):
    if arg == '--duration' and i+1 < len(sys.argv):
        DURATION = int(sys.argv[i+1])

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=10)
sftp = ssh.open_sftp()

# ── Step 1: Sync all dumbbell files ──────────────────────────────────────────
print("=" * 60)
print("  KBCS v2 — Dumbbell Topology Launcher")
print(f"  Duration: {DURATION}s")
print("=" * 60)
print()

files = [
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\kbcs-topo\dbell_topology.json',
     '/home/p4/kbcs_v2/kbcs-topo/dbell_topology.json'),
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\kbcs-topo\dbell_s1-runtime.json',
     '/home/p4/kbcs_v2/kbcs-topo/dbell_s1-runtime.json'),
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\kbcs-topo\dbell_s2-runtime.json',
     '/home/p4/kbcs_v2/kbcs-topo/dbell_s2-runtime.json'),
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\run_dumbbell_experiment.sh',
     '/home/p4/kbcs_v2/run_dumbbell_experiment.sh'),
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\dashboard\dbell_dashboard.py',
     '/home/p4/kbcs_v2/dashboard/dbell_dashboard.py'),
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\p4src\kbcs_v2.p4',
     '/home/p4/kbcs_v2/p4src/kbcs_v2.p4'),
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\dashboard\live_dashboard.py',
     '/home/p4/kbcs_v2/dashboard/live_dashboard.py'),
]

print("[1/3] Syncing files to VM...")
for local, remote in files:
    sftp.put(local, remote)
    print(f"  ✓ {remote.split('/')[-1]}")
sftp.close()

ssh.exec_command('chmod +x /home/p4/kbcs_v2/run_dumbbell_experiment.sh')
time.sleep(1)
print()

# ── Step 2: Compile P4 ──────────────────────────────────────────────────────
print("[2/3] Compiling P4...")
stdin, stdout, stderr = ssh.exec_command(
    'cd /home/p4/kbcs_v2 && '
    'p4c --target bmv2 --arch v1model --std p4-16 '
    '-o p4src/ p4src/kbcs_v2.p4 2>&1'
)
time.sleep(15)
out = stdout.read().decode('utf-8', errors='replace')
if out.strip():
    print(f"  {out.strip()[:200]}")

stdin2, stdout2, _ = ssh.exec_command('ls -la /home/p4/kbcs_v2/p4src/kbcs_v2.json && echo JSON_OK')
time.sleep(3)
check = stdout2.read().decode('utf-8', errors='replace')
if 'JSON_OK' in check:
    print("  ✓ P4 compiled successfully")
else:
    print("  ✗ P4 compilation FAILED")
    ssh.close()
    sys.exit(1)
print()

# ── Step 3: Launch experiment ────────────────────────────────────────────────
print(f"[3/3] Launching dumbbell experiment ({DURATION}s)...")
print("  Dashboard will be at: http://localhost:5001")
print()

ssh.exec_command(
    f'cd /home/p4/kbcs_v2 && '
    f'nohup bash run_dumbbell_experiment.sh --duration {DURATION} '
    f'> /tmp/kbcs_dbell_launcher.log 2>&1 &'
)
time.sleep(2)

print("╔══════════════════════════════════════════════════════════╗")
print("║            DUMBBELL EXPERIMENT LAUNCHED                 ║")
print("╠══════════════════════════════════════════════════════════╣")
print("║  Dumbbell ObsCenter: http://localhost:5001              ║")
print(f"║  Duration:           {DURATION}s                               ║")
print("╠══════════════════════════════════════════════════════════╣")
print("║  Monitor:  ssh p4@localhost -p 2222                     ║")
print("║            tail -f /tmp/kbcs_dbell_launcher.log         ║")
print("╚══════════════════════════════════════════════════════════╝")

ssh.close()
