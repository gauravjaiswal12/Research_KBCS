# ==============================================================================
# Makefile — P4air Build & Run Automation
# ==============================================================================
# Targets:
#   make build         — Compile P4 program to JSON
#   make run           — Build + launch Mininet CLI
#   make test          — Build + run pingall connectivity test
#   make traffic       — Build + run iperf3 traffic test (default: 4 clients)
#   make traffic-8     — Traffic test with 8 clients
#   make clean         — Remove build artifacts
#
# Requires: p4c-bm2-ss, simple_switch, python3, mininet
# ==============================================================================

BUILD_DIR = build
PCAP_DIR  = pcaps
LOG_DIR   = logs

# P4 compiler (BMv2 backend)
P4C = p4c-bm2-ss

# Source and output
P4_SRC       = p4src/p4air.p4
COMPILED_JSON = $(BUILD_DIR)/p4air.json

# Topology runner (prepend utils to PYTHONPATH so p4_mininet imports work)
TOPO = PYTHONPATH=$$PYTHONPATH:$(PWD)/utils python3 topology.py

# Default CCAs: one representative per group from the paper
DEFAULT_CCAS = cubic,bbr,vegas,illinois

# ==============================================================================
# Build target — compile P4 source to JSON for BMv2
# ==============================================================================
build:
	mkdir -p $(BUILD_DIR) $(PCAP_DIR) $(LOG_DIR) results
	$(P4C) --p4v 16 \
		--p4runtime-files $(BUILD_DIR)/p4air.p4info.txt \
		-o $(COMPILED_JSON) \
		$(P4_SRC)
	@echo "=== P4air compiled successfully ==="
	@echo "    Output: $(COMPILED_JSON)"

# ==============================================================================
# Run target — launch Mininet with interactive CLI (for debugging)
# ==============================================================================
run: build
	sudo $(TOPO) \
		--behavioral-exe simple_switch \
		--json $(COMPILED_JSON) \
		--priority-queues 8

# ==============================================================================
# Test target — quick connectivity check (pingall)
# ==============================================================================
test: build
	sudo $(TOPO) \
		--behavioral-exe simple_switch \
		--json $(COMPILED_JSON) \
		--test-only \
		--priority-queues 8

# ==============================================================================
# Traffic targets — run iperf3 experiments with different configurations
# ==============================================================================

# 4 clients (one per CCA group): Cubic, BBR, Vegas, Illinois
traffic: build
	sudo $(TOPO) \
		--behavioral-exe simple_switch \
		--json $(COMPILED_JSON) \
		--traffic \
		--duration 30 \
		--num-clients 4 \
		--ccas $(DEFAULT_CCAS) \
		--priority-queues 8

# 8 clients (two per CCA group)
traffic-8: build
	sudo $(TOPO) \
		--behavioral-exe simple_switch \
		--json $(COMPILED_JSON) \
		--traffic \
		--duration 30 \
		--num-clients 8 \
		--ccas cubic,cubic,bbr,bbr,vegas,vegas,illinois,illinois \
		--priority-queues 8

# ==============================================================================
# Baseline build targets — compile baseline P4 programs
# ==============================================================================

# Build No AQM baseline (simple FIFO forwarding)
build-noaqm:
	mkdir -p $(BUILD_DIR)
	$(P4C) --p4v 16 -o $(BUILD_DIR)/no_aqm.json p4src/no_aqm.p4
	@echo "=== no_aqm.p4 compiled ==="

# Build Different Queues baseline (hash-based queue assignment)
build-diffq:
	mkdir -p $(BUILD_DIR)
	$(P4C) --p4v 16 -o $(BUILD_DIR)/diff_queues.json p4src/diff_queues.p4
	@echo "=== diff_queues.p4 compiled ==="

# Build ALL P4 programs (P4air + baselines)
build-all: build build-noaqm build-diffq
	@echo "=== All 3 P4 programs compiled ==="

# ==============================================================================
# Compare target — run full comparison experiment
# ==============================================================================
compare: build-all
	sudo PYTHONPATH=$$PYTHONPATH:$(PWD)/utils python3 experiments/run_comparison.py \
		--duration 30 --num-clients 4 --ccas $(DEFAULT_CCAS)

# ==============================================================================
# Clean target — remove all generated files
# ==============================================================================
clean:
	rm -rf $(BUILD_DIR) $(PCAP_DIR) $(LOG_DIR) results

.PHONY: build run test traffic traffic-8 build-noaqm build-diffq build-all compare clean
