import paramiko

def patch_vm():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=5)
    sftp = ssh.open_sftp()
    
    print("Patching p4runtime_switch.py...")
    try:
        path = '/home/p4/tutorials/utils/p4runtime_switch.py'
        with sftp.open(path, 'r') as f:
            content = f.read().decode('utf-8')
        if '--priority-queues' not in content:
            content = content.replace('args.append(self.sw_path)', 'args.append(self.sw_path)\n        args.extend(["--priority-queues", "8"])')
            with sftp.open(path, 'w') as f:
                f.write(content)
            print("Successfully patched p4runtime_switch.py")
        else:
            print("Already patched p4runtime_switch.py")
    except Exception as e:
        print("Error patching p4runtime_switch.py:", e)
        
    print("Patching p4_mininet.py...")
    try:
        path2 = '/home/p4/tutorials/utils/p4_mininet.py'
        with sftp.open(path2, 'r') as f:
            content = f.read().decode('utf-8')
        if '--priority-queues' not in content:
            content = content.replace('args.append(self.sw_path)', 'args.append(self.sw_path)\n        args.extend(["--priority-queues", "8"])')
            with sftp.open(path2, 'w') as f:
                f.write(content)
            print("Successfully patched p4_mininet.py")
        else:
            print("Already patched p4_mininet.py")
    except Exception as e:
        print("Error patching p4_mininet.py:", e)

    ssh.close()

if __name__ == "__main__":
    patch_vm()
