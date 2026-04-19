import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=5)
sftp = ssh.open_sftp()

for path in ['/home/p4/tutorials/utils/p4_mininet.py', '/home/p4/tutorials/utils/p4runtime_switch.py']:
    with sftp.open(path, 'r') as f:
        content = f.read().decode('utf-8')
    name = path.split('/')[-1]
    print('=== ' + name + ' ===')
    for i, line in enumerate(content.split('\n')):
        if 'priority-queues' in line or 'grpc-server-addr' in line:
            print('  L%d: %s' % (i+1, line))
    print()

ssh.close()
