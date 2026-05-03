"""Fix the cross_results.csv header to match the actual 8-flow data format."""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', port=2222, username='p4', password='p4')

# Read current CSV
sftp = ssh.open_sftp()
with sftp.open('/home/p4/kbcs_v2/results/cross_results.csv', 'r') as f:
    lines = f.readlines()

print(f"Old header: {lines[0].strip()[:80]}...")
print(f"First data: {lines[1].strip()[:80]}...")
print(f"Total rows: {len(lines)-1}")

# Count columns in data
data_cols = len(lines[1].strip().split(','))
print(f"Data columns: {data_cols}")

# Build correct header for 8-flow data
# Data format from collect_metrics.py: run,topo,dur,num_flows,jfi,agg,link,pdr,avg_karma, then per-flow: karma_i,fwd_i,drops_i
header_parts = ['run', 'topology', 'duration', 'num_flows', 'jfi',
                'agg_throughput_mbps', 'link_util_pct', 'pdr_pct', 'avg_karma']
for i in range(1, 9):
    header_parts.extend([f'karma_{i}', f'fwd_{i}', f'drops_{i}'])

new_header = ','.join(header_parts)
print(f"New header cols: {len(header_parts)}")
print(f"New header: {new_header[:80]}...")

# Write fixed CSV
with sftp.open('/home/p4/kbcs_v2/results/cross_results.csv', 'w') as f:
    f.write(new_header + '\n')
    for line in lines[1:]:
        f.write(line)

print("\n✓ CSV header fixed!")

sftp.close()
ssh.close()
