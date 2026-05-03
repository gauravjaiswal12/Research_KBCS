import paramiko

def fix_vm():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('localhost', port=2222, username='p4', password='p4', timeout=5)
    sftp = ssh.open_sftp()

    # ── Fix p4_mininet.py ────────────────────────────────────────────────────
    # This file uses simple_switch (not grpc). The format is:
    #   simple_switch [args] <json>
    # After json, we need to append:  -- --priority-queues 8
    # Currently my old bad patch added "--priority-queues 8" as a plain arg
    # after json_path with no -- separator, which breaks the binary.
    path1 = '/home/p4/tutorials/utils/p4_mininet.py'
    with sftp.open(path1, 'r') as f:
        content = f.read().decode('utf-8')

    # 1. Remove any old bad patch
    content = content.replace('\n        args.extend(["--priority-queues", "8"])', '')
    content = content.replace('\n        args.extend(["--priority-queues", "8"])  # PFQ patch', '')

    # 2. Now inject correctly: after json_path, add -- --priority-queues 8
    # The target line is: args.append(self.json_path)
    OLD = '        args.append(self.json_path)'
    NEW = ('        args.append(self.json_path)\n'
           '        args.extend(["--", "--priority-queues", "8"])  # PFQ: 8 hardware queues')
    if OLD in content and '# PFQ: 8 hardware queues' not in content:
        content = content.replace(OLD, NEW, 1)
        print(f'Patched {path1} correctly')
    elif '# PFQ: 8 hardware queues' in content:
        print(f'{path1} already correctly patched')
    else:
        print(f'ERROR: could not find injection point in {path1}')

    with sftp.open(path1, 'w') as f:
        f.write(content)

    # ── Fix p4runtime_switch.py ──────────────────────────────────────────────
    # This file uses simple_switch_grpc. The format is:
    #   simple_switch_grpc [args] <json> -- --grpc-server-addr ...
    # We need to inject --priority-queues 8 AFTER the -- separator.
    # Current line: args.append("-- --grpc-server-addr 0.0.0.0:" + str(self.grpc_port))
    path2 = '/home/p4/tutorials/utils/p4runtime_switch.py'
    with sftp.open(path2, 'r') as f:
        content2 = f.read().decode('utf-8')

    # Remove any old bad patch
    content2 = content2.replace('\n        args.extend(["--priority-queues", "8"])', '')

    # The grpc switch appends "-- --grpc-server-addr ..." as ONE string.
    # We need to change it so --priority-queues 8 comes right after the --:
    OLD2 = 'args.append("-- --grpc-server-addr 0.0.0.0:" + str(self.grpc_port))'
    NEW2 = ('args.append("-- --priority-queues 8 --grpc-server-addr 0.0.0.0:" + str(self.grpc_port))')
    if OLD2 in content2 and '-- --priority-queues 8' not in content2:
        content2 = content2.replace(OLD2, NEW2, 1)
        print(f'Patched {path2} correctly')
    elif '-- --priority-queues 8' in content2:
        print(f'{path2} already correctly patched')
    else:
        print(f'WARNING: Could not find grpc injection point in {path2} — checking alternate pattern')
        # Some versions use a list for target args
        for line in content2.split('\n'):
            if 'grpc-server-addr' in line or 'target_args' in line or 'args.append' in line:
                print(f'  Found: {line}')

    with sftp.open(path2, 'w') as f:
        f.write(content2)

    sftp.close()
    ssh.close()
    print('Done.')

if __name__ == "__main__":
    fix_vm()
