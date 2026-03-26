#!/usr/bin/env python3
"""Debug script to hex-dump first packets from collector.pcap"""
import struct

f = open("/tmp/collector.pcap", "rb")
gh = f.read(24)
link_type = struct.unpack('<I', gh[20:24])[0]
print(f"Link type: {link_type}")

for i in range(5):
    ph = f.read(16)
    if len(ph) < 16:
        break
    il = struct.unpack('<I', ph[8:12])[0]
    d = f.read(il)
    et = d[12:14]
    src = d[31:35]
    flag = "CUBIC" if src == b'\x0a\x00\x00\x01' else "BBR" if src == b'\x0a\x00\x00\x02' else f"? ({'.'.join(str(b) for b in src)})"
    print(f"Pkt {i}: len={il}, EtherType=0x{et.hex()}, IP_src_at_31={flag}, tel[14:19]={d[14:19].hex()}")
f.close()
