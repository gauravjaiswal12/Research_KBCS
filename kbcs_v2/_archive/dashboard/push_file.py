import paramiko
import os

try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=5)

    sftp = ssh.open_sftp()
    
    local_path = r"e:\Research Methodology\Project-Implementation\kbcs_v2\dashboard\live_dashboard.py"
    remote_path = "/home/p4/kbcs_v2/dashboard/live_dashboard.py"
    
    print("Uploading file via SFTP...")
    sftp.put(local_path, remote_path)
    print("Transfer successful!")
    
    sftp.close()
    ssh.close()
except Exception as e:
    print(f"Error: {e}")
