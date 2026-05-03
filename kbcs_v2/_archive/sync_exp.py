import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=5)
sftp = ssh.open_sftp()

sftp.put(
    r'e:\Research Methodology\Project-Implementation\kbcs_v2\run_experiment.sh',
    '/home/p4/kbcs_v2/run_experiment.sh'
)
print('Synced run_experiment.sh')
sftp.close()
ssh.close()
