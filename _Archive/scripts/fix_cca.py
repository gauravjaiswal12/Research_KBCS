import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', 2222, 'p4', 'p4')

def sudo(cmd):
    stdin, stdout, stderr = ssh.exec_command(f"echo 'p4' | sudo -S bash -c '{cmd}' 2>&1", get_pty=True)
    out = stdout.read().decode()
    lines = [l for l in out.split('\n') if '[sudo]' not in l and l.strip() != 'p4']
    return '\n'.join(lines).strip()

# Test 1: modprobe all
print("=== Loading modules ===")
print(sudo("modprobe tcp_vegas && echo VEGAS_OK || echo VEGAS_FAIL"))
print(sudo("modprobe tcp_illinois && echo ILLINOIS_OK || echo ILLINOIS_FAIL"))
print(sudo("modprobe tcp_bbr && echo BBR_OK || echo BBR_FAIL"))

# Test 2: Check available
print("\n=== Available CCAs (sysctl) ===")
print(sudo("sysctl net.ipv4.tcp_available_congestion_control"))

# Test 3: Check allowed
print("\n=== Allowed CCAs (sysctl) ===")
print(sudo("sysctl net.ipv4.tcp_allowed_congestion_control"))

# Test 4: Try setting allowed
print("\n=== Setting allowed ===")
print(sudo("sysctl -w net.ipv4.tcp_allowed_congestion_control='reno cubic bbr vegas illinois'"))

# Test 5: Try setting vegas directly at global level
print("\n=== Setting vegas globally ===")
print(sudo("sysctl -w net.ipv4.tcp_congestion_control=vegas"))
print(sudo("sysctl net.ipv4.tcp_congestion_control"))

# Test 6: Revert
print("\n=== Reverting to cubic ===")
print(sudo("sysctl -w net.ipv4.tcp_congestion_control=cubic"))

# Test 7: Check lsmod
print("\n=== Loaded modules ===")
print(sudo("lsmod | grep tcp"))

ssh.close()
