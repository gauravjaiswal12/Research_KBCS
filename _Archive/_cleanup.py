"""
Organise kbcs_v2 and baseline_p4cci locally.

KBCS_V2 — move to _archive/:
  Junk/old: _makerun.log, _old_dashboard.py, _old_index.html,
            _run_exercise_ref.py, _tutorial_makefile_ref.txt,
            weekly_progress_report.md (duplicate of root one)
  Debug helpers: debug_batch_read.py, debug_registers.py,
                 verify_patch.py, test_rl.py, read_pdf.py
  Grafana/docker (not used for paper): docker-compose.yml,
                 grafana-provisioning/, fix_grafana.py, sync_dash.py
  Old sync scripts: sync_3mbps.py, sync_10mbps.py, sync_exp.py,
                    sync_dbell.py, sync_test_suite.py, compile_and_sync.py
  Old fix scripts: fix_csv.py, fix_vm_queues.py, patch_queues.py
  Old generate_plots.py (replaced by generate_paper_plots.py)
  launch_dumbbell.py (superseded by test_suite.sh)
  start_traffic.py  (superseded by test_suite.sh)
  explanation/      (single md, not needed in root)
  dashboard/        (live dashboard, not needed for paper)
  telemetry/        (grafana feeder, not needed for paper)

KEEP in kbcs_v2/:
  p4src/kbcs_v2.p4              <- THE P4 program
  kbcs-topo/                    <- all topo JSONs
  topology/topology.py          <- Mininet topology
  topology/visualize.py         <- useful
  controller/rl_controller.py   <- RL controller
  collect_metrics.py            <- metric collection
  test_suite.sh                 <- 30-run suite
  run_experiment.sh             <- single run
  run_dumbbell_experiment.sh    <- dumbbell run
  analyze_results.py            <- analysis
  generate_paper_plots.py       <- NEW plots
  results/                      <- all CSVs
  plots/                        <- all plots
  clean_logs.py                 <- useful cleanup
  vm_diag.py                    <- useful diagnostics
  Makefile                      <- build
  README.md                     <- docs
  KBCS_Presentation_Guide.md    <- presentation

BASELINE_P4CCI — move to _archive/:
  _check_vm.py, _fix_file.py, _fix_syntax.py, _test_base.py,
  _test_vm.py, _upload.py, _upload_analyze.py
  (These were all one-shot debug/upload helpers)

KEEP in baseline_p4cci/:
  p4cci_baseline_v2/            <- all the VM code (DO NOT TOUCH internals)
  _pull_csv.py                  <- still useful to re-pull CSVs
  sync_p4cci.py                 <- useful to sync files
  report.md                     <- reference doc
  P4CCI paper PDF               <- reference
"""

import os, shutil

def archive(src_base, items, archive_dir):
    os.makedirs(archive_dir, exist_ok=True)
    for item in items:
        src = os.path.join(src_base, item)
        dst = os.path.join(archive_dir, item)
        if os.path.exists(src):
            shutil.move(src, dst)
            print(f"  MOVED: {item}")
        else:
            print(f"  SKIP (not found): {item}")

BASE = r'e:\Research Methodology\Project-Implementation'

# ── kbcs_v2 ──────────────────────────────────────────────────────────────────
kbcs = os.path.join(BASE, 'kbcs_v2')
kbcs_archive = os.path.join(kbcs, '_archive')

kbcs_junk = [
    '_makerun.log',
    '_old_dashboard.py',
    '_old_index.html',
    '_run_exercise_ref.py',
    '_tutorial_makefile_ref.txt',
    'weekly_progress_report.md',
    'debug_batch_read.py',
    'debug_registers.py',
    'verify_patch.py',
    'test_rl.py',
    'read_pdf.py',
    'docker-compose.yml',
    'grafana-provisioning',
    'fix_grafana.py',
    'sync_dash.py',
    'sync_3mbps.py',
    'sync_10mbps.py',
    'sync_exp.py',
    'sync_dbell.py',
    'sync_test_suite.py',
    'compile_and_sync.py',
    'fix_csv.py',
    'fix_vm_queues.py',
    'patch_queues.py',
    'generate_plots.py',   # replaced by generate_paper_plots.py
    'launch_dumbbell.py',
    'start_traffic.py',
    'explanation',
    'dashboard',
    'telemetry',
]

print("\n=== kbcs_v2 cleanup ===")
archive(kbcs, kbcs_junk, kbcs_archive)

# ── baseline_p4cci ────────────────────────────────────────────────────────────
p4cci = os.path.join(BASE, 'baseline_p4cci')
p4cci_archive = os.path.join(p4cci, '_archive')

p4cci_junk = [
    '_check_vm.py',
    '_fix_file.py',
    '_fix_syntax.py',
    '_test_base.py',
    '_test_vm.py',
    '_upload.py',
    '_upload_analyze.py',
]

print("\n=== baseline_p4cci cleanup ===")
archive(p4cci, p4cci_junk, p4cci_archive)

print("\nDone.")
