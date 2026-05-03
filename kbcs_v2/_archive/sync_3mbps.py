import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=5)
sftp = ssh.open_sftp()

files = [
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\dashboard\live_dashboard.py', '/home/p4/kbcs_v2/dashboard/live_dashboard.py'),
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\run_experiment.sh', '/home/p4/kbcs_v2/run_experiment.sh'),
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\controller\rl_controller.py', '/home/p4/kbcs_v2/controller/rl_controller.py')
]

for local, remote in files:
    sftp.put(local, remote)
    print(f'Synced {remote}')
sftp.close()
ssh.close()
