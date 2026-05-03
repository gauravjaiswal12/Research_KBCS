import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=5)
sftp = ssh.open_sftp()

files = [
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\dashboard\live_dashboard.py', '/home/p4/kbcs_v2/dashboard/live_dashboard.py'),
]

for local, remote in files:
    sftp.put(local, remote)
    print(f'Synced {remote}')
sftp.close()

stdin, stdout, stderr = ssh.exec_command(
    'pkill -f live_dashboard.py 2>/dev/null; '
    'sudo fuser -k 5000/tcp 2>/dev/null; '
    'sleep 1; '
    'cd /home/p4/kbcs_v2 && source /home/p4/src/p4dev-python-venv/bin/activate && '
    'python3 dashboard/live_dashboard.py > /tmp/kbcs_dashboard.log 2>&1 & echo DASH_RESTARTED:$!'
)
print(stdout.read().decode('utf-8'))
ssh.close()
