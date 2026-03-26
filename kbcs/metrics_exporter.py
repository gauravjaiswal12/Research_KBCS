import os
import sys
import time
import subprocess
import csv
import re

def parse_registers_batch(num_flows):
    """Read karma + bytes + drops registers for N flows in a single CLI call."""
    cmds = ""
    for i in range(1, num_flows + 1):
        cmds += f"register_read reg_karma {i}\n"
        cmds += f"register_read reg_bytes {i}\n"
        cmds += f"register_read reg_drops {i}\n"
        
    try:
        proc = subprocess.run(
            ['simple_switch_CLI', '--thrift-port', '9090'],
            input=cmds,
            capture_output=True,
            text=True,
            timeout=2
        )
        matches = re.findall(r'=\s*(\d+)', proc.stdout)
        if len(matches) >= 3 * num_flows:
            return [int(m) for m in matches[:3 * num_flows]]
    except Exception:
        pass
    
    # Fallback if switch is busy or dead
    return [0] * (3 * num_flows)

def main():
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    num_flows = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    ccas = sys.argv[3] if len(sys.argv) > 3 else "cubic,bbr"
    
    cca_list = [c.strip() for c in ccas.split(',')]
    if len(cca_list) < num_flows:
        cca_list = (cca_list * (num_flows // len(cca_list) + 1))[:num_flows]
    
    os.makedirs('results', exist_ok=True)
    csv_file = 'results/karma_log.csv'
    
    print(f"Starting exporter for {duration} seconds, tracking {num_flows} flows...")
    
    # Build dynamic headers
    headers = ['time_sec']
    for i in range(num_flows):
        # We index from 1 in the data plane, but 0-indexed in UI
        prefix = f"{cca_list[i].upper()}_{i}" 
        headers.extend([f"{prefix}_karma", f"{prefix}_qdepth", f"{prefix}_drops"])
        
    prev_drops = [0] * num_flows
    
    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        
        start_time = time.time()
        
        while time.time() - start_time < duration:
            current_time = time.time() - start_time
            vals = parse_registers_batch(num_flows)
            
            row = [round(current_time, 2)]
            for i in range(num_flows):
                karma = vals[i*3]
                bytes_val = vals[i*3 + 1]
                drops_tot = vals[i*3 + 2]
                
                # Proxy constraints
                qdepth = bytes_val // 1500
                drops_rate = max(0, drops_tot - prev_drops[i])
                prev_drops[i] = drops_tot
                
                row.extend([karma, qdepth, drops_rate])
                
            writer.writerow(row)
            f.flush()
            time.sleep(0.2)  # Sample 5 times per second
            
    print("Metrics exporter finished.")

if __name__ == "__main__":
    main()
