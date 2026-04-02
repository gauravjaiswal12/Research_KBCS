BUILD_DIR  = build
PCAP_DIR   = pcaps
LOG_DIR    = logs
RESULTS    = results

P4C        = p4c-bm2-ss
TOPO       = topology.py
PL_TOPO    = parking_lot_topo.py
RUN_SCRIPT = -E PYTHONPATH=$$PYTHONPATH:$(PWD)/utils:/home/p4/src/mininet python3

compiled_json  := $(BUILD_DIR)/kbcs.json
baseline_json  := $(BUILD_DIR)/kbcs_baseline.json
p4info_txt     := $(BUILD_DIR)/kbcs.p4.p4info.txt
p4info_base    := $(BUILD_DIR)/kbcs_baseline.p4info.txt

# ------------------------------------------------------------------ #
all: build

# ------------------------------------------------------------------ #
# Compile KBCS (enhanced) program                                      #
# ------------------------------------------------------------------ #
build:
	mkdir -p $(BUILD_DIR) $(PCAP_DIR) $(LOG_DIR) $(RESULTS)
	$(P4C) --p4v 16 --p4runtime-files $(p4info_txt) \
	       -o $(compiled_json) p4src/kbcs.p4
	@echo ">>> kbcs.p4 compiled → $(compiled_json)"

# ------------------------------------------------------------------ #
# Compile KBCS baseline (plain forwarding, no karma)                   #
# ------------------------------------------------------------------ #
build-baseline:
	mkdir -p $(BUILD_DIR) $(PCAP_DIR) $(LOG_DIR) $(RESULTS)
	$(P4C) --p4v 16 --p4runtime-files $(p4info_base) \
	       -o $(baseline_json) p4src/kbcs_baseline.p4
	@echo ">>> kbcs_baseline.p4 compiled → $(baseline_json)"

# ------------------------------------------------------------------ #
# Interactive Mininet shells                                             #
# ------------------------------------------------------------------ #
run: build
	sudo $(RUN_SCRIPT) $(TOPO) \
	    --behavioral-exe simple_switch --json $(compiled_json) \
	    --priority-queues 4

run-parking-lot: build
	sudo $(RUN_SCRIPT) $(PL_TOPO) \
	    --behavioral-exe simple_switch --json $(compiled_json) \
	    --priority-queues 4

# ------------------------------------------------------------------ #
# Quick connectivity tests                                              #
# ------------------------------------------------------------------ #
test: build
	sudo $(RUN_SCRIPT) $(TOPO) \
	    --behavioral-exe simple_switch --json $(compiled_json) \
	    --priority-queues 4 --test-only

test-parking-lot: build
	sudo $(RUN_SCRIPT) $(PL_TOPO) \
	    --behavioral-exe simple_switch --json $(compiled_json) \
	    --priority-queues 4 --test-only

# ------------------------------------------------------------------ #
# 4-flow dumbbell traffic test (KBCS enabled)                           #
# ------------------------------------------------------------------ #
traffic: build
	sudo $(RUN_SCRIPT) $(TOPO) \
	    --behavioral-exe simple_switch --json $(compiled_json) \
	    --priority-queues 4 --traffic --duration 30

# ------------------------------------------------------------------ #
# Dumbbell with adaptive controller running in background              #
# ------------------------------------------------------------------ #
traffic-ctrl: build
	sudo $(RUN_SCRIPT) $(TOPO) \
	    --behavioral-exe simple_switch --json $(compiled_json) \
	    --priority-queues 4 --traffic --duration 30 --controller

# ------------------------------------------------------------------ #
# Parking lot traffic test (KBCS enabled)                              #
# ------------------------------------------------------------------ #
traffic-parking: build
	sudo $(RUN_SCRIPT) $(PL_TOPO) \
	    --behavioral-exe simple_switch --json $(compiled_json) \
	    --priority-queues 4 --traffic --duration 30

# ------------------------------------------------------------------ #
# Baseline (no karma) dumbbell traffic test                             #
# ------------------------------------------------------------------ #
baseline-traffic: build-baseline
	sudo $(RUN_SCRIPT) $(TOPO) \
	    --behavioral-exe simple_switch --json $(baseline_json) \
	    --traffic --duration 30

# ------------------------------------------------------------------ #
# Full experiment: baseline → KBCS → parking lot                       #
# ------------------------------------------------------------------ #
experiment: build build-baseline
	sudo python3 run_experiment.py

# ------------------------------------------------------------------ #
# Standalone adaptive controller (run after launching topology)        #
# ------------------------------------------------------------------ #
controller:
	python3 kbcs_controller.py --thrift-port 9090 --interval 2

clean:
	rm -rf $(BUILD_DIR) $(PCAP_DIR) $(LOG_DIR) $(RESULTS)
