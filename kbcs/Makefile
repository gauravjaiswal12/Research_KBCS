BUILD_DIR = build
PCAP_DIR = pcaps
LOG_DIR = logs

TOPO = topology.py
P4C = p4c-bm2-ss
RUN_SCRIPT = PYTHONPATH=$$PYTHONPATH:$(PWD)/utils python3 $(TOPO)

compiled_json := $(BUILD_DIR)/kbcs.json
baseline_json := $(BUILD_DIR)/kbcs_baseline.json

all: run

build:
	mkdir -p $(BUILD_DIR) $(PCAP_DIR) $(LOG_DIR) results
	$(P4C) --p4v 16 --p4runtime-files $(BUILD_DIR)/kbcs.p4.p4info.txt -o $(compiled_json) p4src/kbcs.p4

build-baseline:
	mkdir -p $(BUILD_DIR) $(PCAP_DIR) $(LOG_DIR) results
	$(P4C) --p4v 16 --p4runtime-files $(BUILD_DIR)/kbcs_baseline.p4info.txt -o $(baseline_json) p4src/kbcs_baseline.p4

run: build
	sudo $(RUN_SCRIPT) --behavioral-exe simple_switch --json $(compiled_json)

test: build
	sudo $(RUN_SCRIPT) --behavioral-exe simple_switch --json $(compiled_json) --test-only

traffic: build
	sudo $(RUN_SCRIPT) --behavioral-exe simple_switch --json $(compiled_json) --traffic --duration 30

baseline-traffic: build-baseline
	sudo $(RUN_SCRIPT) --behavioral-exe simple_switch --json $(baseline_json) --traffic --duration 30

clean:
	rm -rf $(BUILD_DIR) $(PCAP_DIR) $(LOG_DIR) results
