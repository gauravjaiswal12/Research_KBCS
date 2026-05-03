import paramiko
import json
import base64

def fix_grafana():
    print("Connecting to VM...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=5)
    
    file_path = '/home/p4/kbcs_v2/grafana-provisioning/dashboards/kbcs_v2.json'
    
    print("Downloading dashboard json...")
    sftp = ssh.open_sftp()
    with sftp.open(file_path, 'r') as f:
        d = json.load(f)
        
    print("Injecting rawQuery and fixing bucket sizes...")
    for panel in d.get('panels', []):
        for target in panel.get('targets', []):
            if 'query' in target:
                target['rawQuery'] = True
                target['query'] = target['query'].replace('time(2s)', 'time($__interval)')
                
    print("Uploading fixed JSON...")
    with sftp.open(file_path, 'w') as f:
        json.dump(d, f, indent=2)
    sftp.close()
    
    print("Restarting Grafana...")
    stdin, stdout, stderr = ssh.exec_command('sudo docker restart kbcs_v2_grafana')
    print("Done:", stdout.read().decode())
    ssh.close()

if __name__ == "__main__":
    fix_grafana()
