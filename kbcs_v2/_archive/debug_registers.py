import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=5)

# Check actual qdepth values and drop counters
commands = [
    # Raw qdepth on all ports
    "echo 'register_read MyEgress.reg_qdepth 0' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
    "echo 'register_read MyEgress.reg_qdepth 1' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
    "echo 'register_read MyEgress.reg_qdepth 2' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
    "echo 'register_read MyEgress.reg_qdepth 3' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
    "echo 'register_read MyEgress.reg_qdepth 4' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
    "echo 'register_read MyEgress.reg_qdepth 5' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
    # Drop counters for all 4 flows
    "echo 'register_read MyEgress.reg_drops 1' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
    "echo 'register_read MyEgress.reg_drops 2' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
    "echo 'register_read MyEgress.reg_drops 3' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
    "echo 'register_read MyEgress.reg_drops 4' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
    # PFQ dynamic thresholds for all 4 flows
    "echo 'register_read MyIngress.reg_pfq_threshold 1' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
    "echo 'register_read MyIngress.reg_pfq_threshold 2' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
    "echo 'register_read MyIngress.reg_pfq_threshold 3' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
    "echo 'register_read MyIngress.reg_pfq_threshold 4' | simple_switch_CLI --thrift-port 9090 2>/dev/null",
]

for cmd in commands:
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    # Extract the register read part
    for line in out.split('\n'):
        if '=' in line and ('reg_' in line):
            print(line.strip())

ssh.close()
