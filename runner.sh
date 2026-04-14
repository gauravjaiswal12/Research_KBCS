#!/bin/bash
cd /home/p4

# Cleanup previous
rm -rf kbcs results.zip
mkdir kbcs
cd kbcs
unzip -o ../kbcs.zip > /dev/null

echo "Loading kernel modules..."
sudo modprobe tcp_vegas
sudo modprobe tcp_illinois

echo "Installing deps... this might take a minute."
python3 -m pip install matplotlib numpy pillow >/dev/null 2>&1

chmod +x simple_switch_pq.sh

echo "Building P4 code..."
make build > build_log.txt 2>&1
make build-baseline >> build_log.txt 2>&1

echo "Running full experiment (duration ~90s)... please wait."
sudo -E python3 run_experiment.py --controller --duration 30 >> build_log.txt 2>&1

echo "Generating plots and animated GIF..."
python3 plot_results.py --animate >> build_log.txt 2>&1

cd ..
zip -r results.zip kbcs/results/ > /dev/null

echo "DONE. Check results.zip"
