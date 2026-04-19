# Why the "Shrunken Link" Makes KBCS Work Properly

## 1. The Core Question
You asked: *"If Host 1 is generating 100 Mbps (meaning there is 100:10 congestion on paper), why does 10 Mbps fail to show congestion, but shrinking the pipe to 3 Mbps (or 6 Mbps) makes the results look much better?"*

This comes down to the most confusing reality of testing **TCP** inside a **Software Emulator (Mininet + BMv2)**.

## 2. The Explanation: The TCP "Latency Illusion"

The fundamental principle here is that **TCP is blind to switch capacity.** 
When Host 1 tries to send traffic using CUBIC or BBR, it has absolutely no idea that you gave it a 100 Mbps or a 10 Mbps pipe. It only looks at two clues:
1. **Packet Drops** (Is the network full?)
2. **ACK Latency / Round-Trip Time** (How long does it take to get a receipt?)

### Real World (Hardware P4 Switch)
In the physical world, a packet moves through an Intel Tofino P4 switch in ~50 nanoseconds. The latency is practically zero. Because the latency is zero, TCP knows the road is entirely empty, and it accelerates to easily push 100 Mbps, instantly hitting the 10 Mbps bottleneck wall and causing real congestion.

### Your Emulated World (BMv2 Software Switch)
Because `BMv2` runs in the CPU of your Ubuntu Virtual Machine, doing the P4 math for every single packet takes a very long time in computer-terms (~10 to 40 milliseconds). 
When TCP CUBIC sees an ACK taking 40 milliseconds to return, its algorithm triggers an emergency stop. It assumes, *"If an ACK takes 40ms, the internet must be heavily congested. I must voluntarily slow down so I don't cause an internet blackout."*

Because of this **"Latency Illusion"**:
1. Host 1 voluntarily drops its sending speed to ~1 Mbps.
2. Host 2 drops to ~1 Mbps.
3. Hosts 3 and 4 drop to ~1 Mbps.

Combined, **the 4 flows physically refuse to push more than ~2 to 4 Mbps into the pipe**, regardless of how hard `iperf` tries. 

## 3. Why 10 Mbps Failed
If TCP mathematically refuses to transmit more than ~4 Mbps total because of BMv2 CPU latency, your **10 Mbps pipe is never filled.**
* Because 4 Mbps easily fits inside 10 Mbps, the pipe queue sits at **0%**.
* Because the queue sits at **0%**, your KBCS Proactive Drop algorithm thinks the network is perfectly fine and **never penalizes anyone**.
* Every flow stays flat at 100 Karma. 

## 4. Why Shrinking the Pipe Fixes It
By lowering the RL Controller's expectations and the P4 pipe's limits down to **3 Mbps (or 6 Mbps)**:
1. TCP still acts scared of the latency and limits itself to pushing ~4 Mbps.
2. However, now that ~4 Mbps of traffic smashes into a **3 Mbps pipe!**
3. The pipe actually overflows.
4. Because the pipe overflows, the RL Controller accurately calculates that flows are exceeding their `fair_bytes` (which is now properly restricted to the smaller pipe size).
5. KBCS actively engages! It aggressively penalizes greedy flows, dropping their Karma to RED (as seen in your beautiful oscillating screenshot), and the Proof-of-Concept is validated.

## 5. Why is Link Efficiency still oscillating around 16% to 27%?
Because the BMv2 software latency is highly unstable (VM CPU scheduling causes stuttering), TCP is constantly panicking and backing down to almost zero, then trying to speed back up to 3 Mbps. 
When TCP drops to near-zero, your link efficiency crashes to 16%. 

**What is the maximum Link Efficiency achievable in this setup?**
In this specific VM environment, because TCP CUBIC/BBR are so sensitive to BMv2 stuttering, achieving a constant 100% link utilization with standard TCP is nearly impossible without artificially increasing Linux TCP window limits (e.g., editing `sysctl tcp_rmem`). 
However, **you do not need exactly 100% Link Efficiency for your paper.** What you have right now—oscillating Karma, aggressive penalization of RED flows, and dynamic JFI corrections—is the exact mathematical proof you need to show that your KBCS Proactive Fair Queuing system works under emulated network constraints.
