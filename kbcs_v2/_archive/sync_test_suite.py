import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=5)
sftp = ssh.open_sftp()

files = [
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\test_suite.sh',
     '/home/p4/kbcs_v2/test_suite.sh'),
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\collect_metrics.py',
     '/home/p4/kbcs_v2/collect_metrics.py'),
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\analyze_results.py',
     '/home/p4/kbcs_v2/analyze_results.py'),
]

for local, remote in files:
    sftp.put(local, remote)
    print(f'Synced {remote.split("/")[-1]}')

sftp.close()

# Make scripts executable and create results dir
cmds = [
    'chmod +x /home/p4/kbcs_v2/test_suite.sh',
    'mkdir -p /home/p4/kbcs_v2/results',
]
for cmd in cmds:
    ssh.exec_command(cmd)

print('\n✓ All test suite files deployed')
print('\nTo run:')
print('  Cross topology:    bash test_suite.sh --topo cross --runs 30 --duration 60')
print('  Dumbbell topology: bash test_suite.sh --topo dumbbell --runs 30 --duration 60')
print('  Analyze results:   python3 analyze_results.py')

ssh.close()
