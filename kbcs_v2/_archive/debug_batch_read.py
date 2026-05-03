import paramiko
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=5)

# Test batch register read exactly as rl_controller does
cmd = (
    'register_read MyIngress.reg_total_pkts 1\n'
    'register_read MyIngress.reg_drops 1\n'
    'register_read MyIngress.reg_forwarded_bytes 1\n'
    'register_read MyIngress.reg_total_pkts 2\n'
    'register_read MyIngress.reg_drops 2\n'
    'register_read MyIngress.reg_forwarded_bytes 2\n'
)

stdin, stdout, stderr = ssh.exec_command(
    'echo \'' + cmd + '\' | simple_switch_CLI --thrift-port 9090 2>/dev/null'
)
out = stdout.read().decode('utf-8', errors='replace')
print('Raw output:')
print(out)

import re
values = re.findall(r'=\s*(\d+)', out)
print('\nExtracted values:', values)
print('Expected count (3 per flow * 2 flows):', 3 * 2)
print('Got:', len(values))
if len(values) >= 3 * 2:
    print('PASS - batch read works')
else:
    print('FAIL - batch read broken, RL will skip epochs')

ssh.close()
