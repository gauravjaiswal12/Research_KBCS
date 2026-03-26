#!/usr/bin/env python3
"""
INT Collector for KBCS Phase 4 (N-Flow Support)
Reads offline PCAP captured by tcpdump, extracts custom 40-bit P4 telemetry
headers, and maps IPs to CCA flow names dynamically based on CLI args.
"""
import sys
import os
import json
import struct

def parse_ip_map(ip_map_str):
    """Parse '10.0.0.1:cubic,10.0.0.2:bbr' into a dictionary of {bytes: 'CUBIC_0'}"""
    ip_map = {}
    if not ip_map_str:
        return ip_map
        
    pairs = ip_map_str.split(',')
    for i, pair in enumerate(pairs):
        if ':' not in pair: continue
        ip_str, cca = pair.split(':', 1)
        
        # Convert '10.0.0.1' -> b'\x0a\x00\x00\x01'
        parts = [int(x) for x in ip_str.split('.')]
        if len(parts) == 4:
            ip_bytes = bytes(parts)
            ip_map[ip_bytes] = f"{cca.upper()}_{i}"
            
    return ip_map

def process_pcap(pcap_file, ip_map):
    results = []
    
    with open(pcap_file, 'rb') as f:
        global_header = f.read(24)
        if len(global_header) < 24:
            return results
        
        magic = struct.unpack('<I', global_header[0:4])[0]
        if magic == 0xa1b2c3d4: endian = '<'
        elif magic == 0xd4c3b2a1: endian = '>'
        else: return results
        
        link_type = struct.unpack(endian + 'I', global_header[20:24])[0]
        if link_type == 1:
            ll_offset, ethtype_offset = 14, 12
        elif link_type == 113:
            ll_offset, ethtype_offset = 16, 14
        elif link_type == 276:
            ll_offset, ethtype_offset = 20, 0
        else:
            return results
        
        packet_num = matched = 0
        
        while True:
            pkt_header = f.read(16)
            if len(pkt_header) < 16: break
            
            ts_sec = struct.unpack(endian + 'I', pkt_header[0:4])[0]
            ts_usec = struct.unpack(endian + 'I', pkt_header[4:8])[0]
            incl_len = struct.unpack(endian + 'I', pkt_header[8:12])[0]
            
            pkt_data = f.read(incl_len)
            if len(pkt_data) < incl_len: break
            
            packet_num += 1
            if len(pkt_data) < ll_offset + 25: continue
            
            ether_type = struct.unpack('!H', pkt_data[ethtype_offset:ethtype_offset+2])[0]
            if ether_type != 0x1234 and ether_type != 0x0800: continue
            
            tel_start = ll_offset
            tel_bytes = pkt_data[tel_start:tel_start+5]
            
            karma = tel_bytes[0]
            color = (tel_bytes[1] >> 6) & 0x03
            queue_id = (tel_bytes[1] >> 3) & 0x07
            qdepth = ((tel_bytes[1] & 0x07) << 16) | (tel_bytes[2] << 8) | tel_bytes[3]
            dropped = (tel_bytes[4] >> 7) & 0x01
            
            ip_start = tel_start + 5
            if len(pkt_data) < ip_start + 16: continue
            src_bytes = pkt_data[ip_start+12:ip_start+16]
            
            flow = ip_map.get(src_bytes, "UNKNOWN")
            
            if flow != "UNKNOWN":
                matched += 1
                timestamp_ns = ts_sec * 1_000_000_000 + ts_usec * 1000
                results.append({
                    "flow": flow,
                    "karma": karma,
                    "color": color,
                    "qdepth": qdepth,
                    "dropped": dropped,
                    "ts": timestamp_ns
                })
        
        print(f"Processed {packet_num} packets, matched {matched} telemetry frames.")
    
    return results

def main():
    if len(sys.argv) < 2:
        print("Usage: int_collector.py <pcap_file> [ip_map]")
        sys.exit(1)
    
    pcap_file = sys.argv[1]
    ip_map_str = sys.argv[2] if len(sys.argv) > 2 else ""
    ip_map = parse_ip_map(ip_map_str)
    
    print(f"INT Collector: Parsing {pcap_file} with map {ip_map}")
    results = process_pcap(pcap_file, ip_map)
    
    os.makedirs("results", exist_ok=True)
    with open("results/telemetry.json", 'w') as f:
        json.dump(results, f)

if __name__ == '__main__':
    main()
