import paramiko
import struct

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('localhost', 2222, 'p4', 'p4')
sftp = ssh.open_sftp()
sftp.get('/tmp/collector.pcap', 'test_collector.pcap')
sftp.close()
ssh.close()

with open('test_collector.pcap', 'rb') as f:
    global_header = f.read(24)
    magic = struct.unpack('<I', global_header[0:4])[0]
    endian = '<' if magic == 0xa1b2c3d4 else '>'
    link_type = struct.unpack(endian + 'I', global_header[20:24])[0]
    ll_offset = 14 if link_type == 1 else (16 if link_type == 113 else 20)
    ethtype_offset = 12 if link_type == 1 else (14 if link_type == 113 else 0)
    
    counts = {'total':0, 'small':0, 'ether':0, 'ip':0, 'match': 0}
    ether_types = {}
    
    while True:
        pkt_header = f.read(16)
        if len(pkt_header) < 16: break
        incl_len = struct.unpack(endian + 'I', pkt_header[8:12])[0]
        pkt_data = f.read(incl_len)
        counts['total']+=1
        
        if len(pkt_data) < ll_offset + 25:
            counts['small']+=1
            continue
            
        ether_type = struct.unpack('!H', pkt_data[ethtype_offset:ethtype_offset+2])[0]
        ether_types[hex(ether_type)] = ether_types.get(hex(ether_type), 0) + 1
        
        if ether_type != 0x1234 and ether_type != 0x0800:
            counts['ether']+=1
            continue
            
        tel_start = ll_offset
        ip_start = tel_start + 5
        src_bytes = pkt_data[ip_start+12:ip_start+16]
        if src_bytes != b'\x0a\x00\x00\x01' and src_bytes != b'\x0a\x00\x00\x02':
            if counts['ip'] == 0:
                print(f"First Bad IP Hex Dump:")
                print(pkt_data.hex())
            counts['ip']+=1
            bad_ips[src_bytes] = bad_ips.get(src_bytes, 0) + 1
            continue
            
        counts['match'] += 1

print("Counts:", counts)
print("EtherTypes:", ether_types)
print("Bad IPs:", bad_ips)
