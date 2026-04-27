import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=5)
sftp = ssh.open_sftp()

files = [
    # Topology files
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\kbcs-topo\dbell_topology.json',
     '/home/p4/kbcs_v2/kbcs-topo/dbell_topology.json'),
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\kbcs-topo\dbell_s1-runtime.json',
     '/home/p4/kbcs_v2/kbcs-topo/dbell_s1-runtime.json'),
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\kbcs-topo\dbell_s2-runtime.json',
     '/home/p4/kbcs_v2/kbcs-topo/dbell_s2-runtime.json'),
    # Experiment script
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\run_dumbbell_experiment.sh',
     '/home/p4/kbcs_v2/run_dumbbell_experiment.sh'),
    # Dashboard
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\dashboard\dbell_dashboard.py',
     '/home/p4/kbcs_v2/dashboard/dbell_dashboard.py'),
    # Also sync the updated P4 code (with scaled thresholds)
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\p4src\kbcs_v2.p4',
     '/home/p4/kbcs_v2/p4src/kbcs_v2.p4'),
    # Also sync the updated main dashboard (with cumulative PDR fix)
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\dashboard\live_dashboard.py',
     '/home/p4/kbcs_v2/dashboard/live_dashboard.py'),
]

for local, remote in files:
    sftp.put(local, remote)
    print(f'Synced {remote.split("/")[-1]}')

sftp.close()

# Make the experiment script executable
stdin, stdout, stderr = ssh.exec_command('chmod +x /home/p4/kbcs_v2/run_dumbbell_experiment.sh')
stdout.read()
print('\n✓ Made run_dumbbell_experiment.sh executable')

ssh.close()
print('\n✓ All dumbbell topology files deployed to VM')
