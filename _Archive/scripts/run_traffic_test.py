"""Build baseline + KBCS and run both traffic tests to isolate the issue."""
import paramiko
import scp as scp_module
import time

host, port, user, pwd = "localhost", 2222, "p4", "p4"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(host, port, user, pwd)
print("Connected to VM.")

def run(cmd, timeout=30):
    print(f"  $ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out.strip():
        print(out.strip())
    if err.strip():
        for line in err.strip().split('\n'):
            if 'Warning' not in line and 'quantum' not in line and 'password' not in line:
                if line.strip():
                    print(f"  err: {line}")
    return out

# Clean up
print("\n--- Cleanup ---")
run("echo 'p4' | sudo -S mn -c 2>/dev/null; echo 'p4' | sudo -S killall simple_switch iperf3 2>/dev/null; sleep 2; echo done")

# Upload
print("\n--- Uploading ---")
run("rm -rf /home/p4/kbcs/p4src /home/p4/kbcs/build")
with scp_module.SCPClient(ssh.get_transport()) as scp_client:
    scp_client.put("kbcs", remote_path="/home/p4", recursive=True)
print("Upload done.")

# Build BOTH versions
print("\n--- Building BASELINE ---")
run("cd /home/p4/kbcs && make clean 2>/dev/null; make build-baseline 2>&1", timeout=60)

print("\n--- Building KBCS ---")
run("cd /home/p4/kbcs && make build 2>&1", timeout=60)

# Quick test: can h3 start iperf3 manually outside Mininet?
print("\n--- Testing iperf3 directly ---")
run("iperf3 -s -p 5201 -D && sleep 1 && iperf3 -c localhost -p 5201 -t 1 -J 2>&1 | head -5; killall iperf3 2>/dev/null")

ssh.close()
print("\nDone. Files are built on VM.")
print("Now run these tests manually on the VM:")
print()
print("TEST 1 (BASELINE — should work):")
print("  sudo mn -c 2>/dev/null; sudo killall simple_switch iperf3 2>/dev/null; sleep 2")
print("  sudo PYTHONPATH=$PYTHONPATH:$(pwd)/utils python3 topology.py \\")
print("    --behavioral-exe simple_switch --json build/kbcs_baseline.json \\")
print("    --traffic --duration 30")
print()
print("TEST 2 (KBCS — debug no-drop):")
print("  sudo mn -c 2>/dev/null; sudo killall simple_switch iperf3 2>/dev/null; sleep 2")
print("  sudo PYTHONPATH=$PYTHONPATH:$(pwd)/utils python3 topology.py \\")
print("    --behavioral-exe simple_switch --json build/kbcs.json \\")
print("    --traffic --duration 30")
