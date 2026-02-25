import paramiko
import scp
import os
import sys

def run_cmd(ssh, cmd, show=True):
    """Run a command over SSH and return stdout, stderr, exit_status."""
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    exit_status = stdout.channel.recv_exit_status()
    if show and out.strip():
        print(out.strip())
    if show and err.strip():
        print(err.strip())
    return out, err, exit_status

def upload_and_run():
    host = "localhost"
    port = 2222
    username = "p4"
    password = "p4"
    local_dir = "kbcs"
    remote_dir = "/home/p4/kbcs"

    print("Connecting to VM...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, port, username, password)
        print("Connected.")

        # Clean old P4 source files and topology to avoid stale versions
        print("Cleaning old files on VM...")
        run_cmd(ssh, f"rm -f {remote_dir}/topology.py {remote_dir}/Makefile {remote_dir}/runtime.json")
        run_cmd(ssh, f"rm -rf {remote_dir}/p4src")
        run_cmd(ssh, f"mkdir -p {remote_dir}/p4src {remote_dir}/results {remote_dir}/build {remote_dir}/logs {remote_dir}/pcaps")

        print("Uploading files...")
        with scp.SCPClient(ssh.get_transport()) as scp_client:
            scp_client.put(local_dir, remote_path="/home/p4", recursive=True)
        print("Upload complete.")

        # Verify the uploaded topology.py doesn't have pcap
        print("\n--- Verifying uploaded topology.py ---")
        run_cmd(ssh, f"grep -n 'pcap\\|addSwitch' {remote_dir}/topology.py")

        # Build P4 program
        print("\n--- Building P4 program ---")
        out, err, status = run_cmd(ssh, f"cd {remote_dir} && make build")
        if status != 0:
            print(f"Build FAILED (exit {status})")
            sys.exit(status)
        print("Build successful!")

        # Run the test
        print("\n--- Running pingall test ---")
        out, err, status = run_cmd(ssh, f"cd {remote_dir} && echo 'p4' | sudo -S PYTHONPATH=$PYTHONPATH:{remote_dir}/utils python3 topology.py --behavioral-exe simple_switch --json build/kbcs.json --test-only 2>&1")
        
        if "0% dropped" in out:
            print("\n*** PINGALL TEST PASSED! ***")
        else:
            print(f"\n*** Test finished (exit {status}) ***")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        ssh.close()

if __name__ == "__main__":
    upload_and_run()
