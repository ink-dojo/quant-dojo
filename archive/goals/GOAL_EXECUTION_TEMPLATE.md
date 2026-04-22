# GOAL Execution Template

## Purpose

Use this template when the objective is not "prototype something interesting" but "drive a research or trading system change to a verified, operationally credible end state."

This template is designed for a single primary agent that owns the task end to end. Parallel agents, if used at all, should only support bounded side work such as targeted review, tests, or isolated implementation slices.

## How To Use This File

1. Copy this file to a new goal file such as `GOAL_<topic>.md`.
2. Replace every placeholder with repo-specific detail.
3. Remove sections that do not apply.
4. Do not mark `STATUS: CONVERGED` until all exit gates pass.

## Title

# Goal: <Short Goal Name> (<YYYY-MM-DD>)

## Goal

Describe the end state in system terms, not vague aspiration.

Example:
"Make daily signal generation reproducible, restart-safe, and verifiable from data load to paper-trade output."

## Why This Matters

- <What system risk this removes>
- <Why this blocks the next phase>
- <Why partial completion would be dangerous>

## Scope

### In Scope
- [ ] <Concrete system change>
- [ ] <Concrete validation or reproducibility work>
- [ ] <Concrete risk / monitoring / state integrity fix>

### Out of Scope
- [ ] <Interesting but separate research path>
- [ ] <Dashboard polish that does not improve system integrity>
- [ ] <Real-money trading rollout if the phase is still paper trading>

## Current Verified State

Only include facts verified in code, tests, pipeline output, or saved artifacts.

### Already Exists
- [x] <Verified component already present>
- [x] <Verified component already present>

### Current Gaps
- [ ] <Actual integrity gap>
- [ ] <Actual testing or reproducibility gap>
- [ ] <Actual operational or state gap>

## Operational Outcome

When this goal is done, the system should be able to:

- [ ] <Operational behavior 1>
- [ ] <Operational behavior 2>
- [ ] <Operational behavior 3>

## Implementation Plan

### Phase A: <Name>
- [ ] <Specific task>
- [ ] <Specific task>

### Phase B: <Name>
- [ ] <Specific task>
- [ ] <Specific task>

### Phase C: <Name>
- [ ] <Specific task>
- [ ] <Specific task>

## File-Level Work

### Core Runtime
- [ ] [billing_or_pipeline_example.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/pipeline/daily_signal.py)
  - <What must change>

### State / Risk / Execution
- [ ] [paper_trader.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/live/paper_trader.py)
  - <What must change>

### Tests / Config / Docs
- [ ] [README.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/README.md)
  - <What must change>

## Definition Of Done

Do not close the goal unless all are true:

- [ ] The target pipeline or subsystem works end to end
- [ ] Reproducibility and restart assumptions are explicit
- [ ] Known integrity issues in the scoped area are either fixed or documented as future work
- [ ] Required commands in "Must-Pass Commands" succeed
- [ ] The goal file reflects the final verified state

## Exit Gates

`STATUS: CONVERGED` is allowed only if all of the following are true:

- [ ] No unresolved scoped P0 or P1 risk remains
- [ ] Validation commands and relevant tests succeeded
- [ ] The system behavior is explainable from inputs to outputs
- [ ] Any residual risk is explicitly written down and moved forward intentionally

If any gate fails, the agent must keep working or write back the exact blocker.

## Must-Pass Commands

Replace with the exact commands for this goal. Remove commands that do not apply.

```bash
python -m compileall /Volumes/Crucial\ X10/Documents/GitHub/quant-dojo
pytest -q /Volumes/Crucial\ X10/Documents/GitHub/quant-dojo/tests
python /Volumes/Crucial\ X10/Documents/GitHub/quant-dojo/pipeline/cli.py --help
```

## Manual Verification

- [ ] Run the targeted pipeline or subsystem on representative local data
- [ ] Inspect generated artifacts, logs, and state files
- [ ] Verify restart behavior if the goal touches live or paper-trading state
- [ ] Verify that outputs are consistent with the documented assumptions

## Risks To Watch

- [ ] Machine-specific paths or hidden environment assumptions
- [ ] False confidence from passing syntax checks without data-backed execution
- [ ] Divergence between strategy spec and paper-trading implementation
- [ ] Weak state recovery after restart
- [ ] Monitoring that appears active but silently does nothing

## Self-Review Checklist

Before marking done, the agent must verify:

- [ ] The implementation reduces operational risk, not just code smell
- [ ] Data assumptions are explicit
- [ ] Tests exercise the real failure mode this goal was created to fix
- [ ] Docs and workplan statements match the actual current system

## If Not Converged

If the agent must stop before completion, it must update this file with:

- current status
- exact blocker
- what was verified
- what remains
- the next highest-value step

Do not stop with a vague sentence like "needs more research."

## Status

### STATUS: ACTIVE

Use one of:

- `STATUS: ACTIVE`
- `STATUS: BLOCKED`
- `STATUS: CONVERGED`

Only use `STATUS: CONVERGED` after all exit gates pass.
