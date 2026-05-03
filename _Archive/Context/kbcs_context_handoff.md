# KBCS Project Context Handoff

This file summarizes the current state of the **Karma-Based Credit Scheduler (KBCS)** project for migration to a Linux environment.

## 1. Project Goal
Achieve **Throughput Fairness** between bottleneck-filling flows (CUBIC) and model-based flows (BBR) on a shared link, without using separate physical queues per flow.

## 2. Selected Solution: KBCS
*   **Core Idea**: Logic-based separation using a "Social Credit" system.
*   **Mechanism**:
    *   **Gold Queue**: High Priority (Weight 64).
    *   **Silver Queue**: Medium Priority (Weight 16).
    *   **Bronze Queue**: Low Priority (Weight 1).
*   **Algorithm**:
    *   Track `Karma` (0-100) per flow in Ingress Registers.
    *   If **Congested** (Queue > 80%) AND **Aggressive** (Rate > Fair Share) -> **Karma -= 5**.
    *   Else -> **Karma += 1**.
    *   Map flow to Queue based on Karma (Gold > 80, Bronze < 40).

## 3. Current Status
*   **Design Phase**: **Completed**. The detailed design is in `kbcs_design.md`.
*   **Implementation Phase**: **Ready to Start**. The step-by-step plan is in `kbcs_implementation_plan.md`.

## 4. Key Artifacts (Transfer these to Linux)
1.  `kbcs_design.md`: Contains the Packet Pipeline Flowchart, Congestion Analysis, and Feedback Loop theory.
2.  `kbcs_implementation_plan.md`: Contains the P4 directory structure and Phase 1-4 coding steps.

## 5. Next Step (Action in Linux)
1.  Boot Ubuntu.
2.  Ensure P4/Mininet environment is set up.
3.  Create working directory `~/kbcs_project`.
4.  **Prompt**: "I am starting Phase 1 of KBCS. Please read `kbcs_implementation_plan.md` and help me set up the basic P4 forwarding skeleton."
