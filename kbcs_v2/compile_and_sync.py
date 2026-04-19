import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=10)
sftp = ssh.open_sftp()

# Sync fixed files
files = [
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\p4src\kbcs_v2.p4',
     '/home/p4/kbcs_v2/p4src/kbcs_v2.p4'),
    (r'e:\Research Methodology\Project-Implementation\kbcs_v2\run_experiment.sh',
     '/home/p4/kbcs_v2/run_experiment.sh'),
]
for local, remote in files:
    sftp.put(local, remote)
    print('Synced:', remote.split('/')[-1])

sftp.close()

# Recompile P4
print('\nRecompiling kbcs_v2.p4...')
stdin, stdout, stderr = ssh.exec_command(
    'cd /home/p4/kbcs_v2 && '
    'p4c --target bmv2 --arch v1model --std p4-16 '
    '-o p4src/ p4src/kbcs_v2.p4 2>&1'
)
import time
time.sleep(15)
out = stdout.read().decode('utf-8', errors='replace')
err = stderr.read().decode('utf-8', errors='replace')
if out.strip():
    print('Compiler output:', out[:1000])
if err.strip():
    print('Compiler errors:', err[:1000])
print('Done. Exit code check:')
stdin2, stdout2, _ = ssh.exec_command('ls -la /home/p4/kbcs_v2/p4src/kbcs_v2.json && echo JSON_OK')
time.sleep(3)
print(stdout2.read().decode('utf-8', errors='replace'))
ssh.close()
