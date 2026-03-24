# Goal: Control Plane Convergence (2026-03-24)

## Goal

Take the newly built control plane from "first working version" to "system-level converged operator surface."

This goal is not about inventing a new direction. It is about making the current control-plane stack difficult to break, easy to verify, and safe enough that future AI agents can rely on it without hidden footguns.

## Why This Exists

The first control-plane wave is real and valuable:

- unified CLI command tree exists
- strategy registry exists
- run store exists
- dashboard backtest endpoints exist
- agent-safe `control_surface` exists
- legacy CLI compatibility and approval gate have been restored

That is enough to say "the control plane exists."

It is **not** enough to say "the control plane is converged."

The remaining risk is no longer missing architecture. The remaining risk is false confidence:

- dashboard and CLI may still drift
- run artifacts may still be too loose
- tests may still be too module-local instead of system-level
- AI-safe entrypoints may exist, but still not be proven as the only sane path

## Single Primary Objective

Prove that `quant-dojo` control-plane execution and observation surfaces agree on one stable contract, and refuse convergence until repeated review loops fail to find new material gaps.

## In Scope

- [ ] system-level validation of the control plane, not just module-level existence
- [ ] run artifact schema hardening
- [ ] dashboard consumption hardening for backtest runs
- [ ] run detail / comparison / provenance operator visibility
- [ ] manual trigger paths using the same control-plane contract
- [ ] explicit convergence gates for AI-safe usage
- [ ] repeated independent review loops before closure

## Out of Scope

- [ ] new strategy research
- [ ] broker / real-money execution
- [ ] visual redesign that does not improve operator clarity
- [ ] agent autonomy expansion beyond current approval-gated control surface
- [ ] replacing the existing control plane with a different architecture

## Current Verified State

### Already True
- [x] `pipeline/cli.py` has a hierarchical command tree
- [x] old CLI entrypoints are restored alongside the new tree
- [x] `pipeline/strategy_registry.py` defines discoverable strategies
- [x] `pipeline/run_store.py` persists run records
- [x] `pipeline/control_surface.py` exposes approved commands and approval gating
- [x] dashboard has backtest routes and a recent-runs surface
- [x] automated tests exist for registry, run store, CLI, and control surface

### Not Yet Proven
- [ ] a complete end-to-end path from CLI backtest to dashboard display is regression-tested
- [ ] run artifacts have a sufficiently strict, stable schema for future AI usage
- [ ] dashboard comparison and detail views expose enough provenance for operator trust
- [ ] dashboard manual triggers demonstrably reuse the same underlying control-plane contract
- [ ] two separate convergence review loops can no longer find new material issues

## Operational Outcome

When this goal is done, a human operator should be able to:

- [ ] run a strategy backtest entirely through the unified CLI
- [ ] inspect the exact run artifact on disk
- [ ] query the same run through dashboard APIs
- [ ] view recent runs, detail, and comparison without reading source code
- [ ] know which commands are read-only, which require approval, and why
- [ ] trust that AI agents should call the control surface, not internal modules

## Design Principles

### 1. Convergence Means Repeated Scrutiny

One clean implementation pass is not enough.

This goal is complete only when:

- at least **two independent review loops**
- run after the implementation is "done"
- and neither loop finds a new material issue

Material issue means:

- correctness bug
- contract ambiguity
- dashboard/CLI mismatch
- unsafe state-changing path
- missing provenance that blocks operator trust

Cosmetic nits do not count. Anything that would change behavior, trust, or future AI safety does count.

### 2. CLI Is Still Authoritative

Dashboard may observe and trigger.
CLI remains the canonical execution surface.

If dashboard can do something that CLI cannot explain, the control plane is not converged.

### 3. Artifact Semantics Must Be Explicit

A run record is not enough by itself.

The system must make it obvious:

- what each artifact file contains
- whether a CSV is returns, equity, or generic result output
- what metrics were computed from
- what parameters and date range produced the result

### 4. AI Safety Requires Narrow Contracts

`control_surface` should be the obvious future AI entrypoint.

That means:

- read-only commands are easy to discover
- mutating commands are gated
- dry-run behavior is predictable
- outputs are structured enough for machine use

### 5. Convergence Is Allowed To Be Boring

This phase is about closing trust gaps, not showing off more features.

## Implementation Plan

### Phase A: Artifact Contract Hardening

- [ ] document the exact schema of a stored backtest run
- [ ] distinguish record metadata vs metrics vs artifact files
- [ ] clarify what `equity_csv` means and whether the stored DataFrame is truly an equity curve or generic run output
- [ ] add any missing artifact fields needed for dashboard detail and comparison
- [ ] ensure failed runs also leave behind enough structured metadata for diagnosis

### Phase B: End-to-End Regression

- [ ] add at least one automated end-to-end path:
  - [ ] run backtest through CLI or control-plane service
  - [ ] persist run into `run_store`
  - [ ] fetch run through dashboard service / API layer
  - [ ] assert key metrics and metadata survive unchanged
- [ ] add regression coverage for legacy CLI compatibility:
  - [ ] `signal --date`
  - [ ] `rebalance --date`
  - [ ] `weekly-report`
  - [ ] `risk-check`
- [ ] add regression coverage for control-surface approval gate and dry-run semantics

### Phase C: Dashboard Operator Trust

- [ ] add or harden run detail support
- [ ] add or harden run comparison support
- [ ] expose provenance clearly:
  - [ ] strategy id / name
  - [ ] params
  - [ ] date range
  - [ ] created time
  - [ ] status / error
  - [ ] artifact paths if present
- [ ] ensure dashboard does not silently reinterpret run data

### Phase D: Trigger Path Unification

- [ ] verify dashboard trigger paths reuse the same underlying contract as CLI / control surface
- [ ] remove or reject any dashboard-only execution path that bypasses the unified contract
- [ ] prove at least one manual trigger path is wired end-to-end and observable

### Phase E: Convergence Reviews

- [ ] run one full review loop after implementation and record findings
- [ ] fix all material findings
- [ ] run a second full review loop by an independent agent / run
- [ ] refuse `STATUS: CONVERGED` if the second loop still finds any new material issue

## File-Level Work

### Core Control Plane
- [ ] [pipeline/run_store.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/pipeline/run_store.py)
  - harden artifact schema
  - improve failed-run metadata if needed
- [ ] [pipeline/control_surface.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/pipeline/control_surface.py)
  - keep approval gate and dry-run semantics explicit
  - ensure outputs remain structured and stable
- [ ] [pipeline/cli.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/pipeline/cli.py)
  - preserve both new and legacy operator paths

### Dashboard
- [ ] [dashboard/services/backtest_service.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/dashboard/services/backtest_service.py)
  - align API responses with run artifact schema
- [ ] [dashboard/routers/backtest.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/dashboard/routers/backtest.py)
  - expose reliable detail / compare behavior
- [ ] [dashboard/static/index.html](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/dashboard/static/index.html)
  - make recent runs, detail, and comparison operator-usable

### Tests
- [ ] [tests/test_control_plane.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/tests/test_control_plane.py)
  - add system-level regression cases
- [ ] add a dedicated dashboard/control-plane integration test file if current coverage becomes too mixed

### Docs
- [ ] [GOAL_control_plane.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_control_plane.md)
  - treat as phase-one implementation record
- [ ] [WORKPLAN.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/WORKPLAN.md)
  - mark convergence as the current control-plane task
- [ ] [README.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/README.md)
  - only update if operator workflow has materially changed

## Definition Of Done

Do not close this goal unless all are true:

- [ ] at least one backtest path is proven end-to-end from execution to dashboard consumption
- [ ] legacy and new CLI contracts both pass regression checks
- [ ] run artifacts have explicit, documented semantics
- [ ] dashboard detail and comparison views expose enough provenance for operator trust
- [ ] mutating control-surface commands require approval and this behavior is tested
- [ ] no known scoped P0 or P1 gap remains in control-plane correctness or trust

## Hard Exit Gates

`STATUS: CONVERGED` is forbidden unless **every** item below is true:

- [ ] implementation work is complete
- [ ] one full post-implementation review loop found no unresolved material issue
- [ ] a second independent review loop also found no new material issue
- [ ] dashboard and CLI are verified to agree on the same run data for at least one real run
- [ ] there is no remaining known path where AI or dashboard bypasses the approved control-plane contract
- [ ] the goal file is updated to reflect final verified behavior, not planned behavior

If either convergence loop finds a new material issue, this goal stays ACTIVE.

## Explicitly Unacceptable Fake-Finished States

The goal is **not** complete if any of these are true:

- [ ] tests are green but no end-to-end run was checked through dashboard consumption
- [ ] dashboard can show recent runs but cannot explain provenance
- [ ] `equity_csv` still means "whatever DataFrame happened to be saved"
- [ ] legacy CLI commands are claimed compatible but not actually exercised
- [ ] approval gate exists in code but not covered by regression tests
- [ ] one review loop passed and the team stopped there

## Must-Pass Commands

```bash
python -m py_compile /Volumes/Crucial\ X10/Documents/GitHub/quant-dojo/pipeline/cli.py
python -m pipeline.cli --help
python -m pipeline.cli strategies
python -m pipeline.cli backtest list
python -m pipeline.cli signal --date 2026-03-20
python -m pipeline.cli signal run --date 2026-03-20
python -m pipeline.cli risk-check
python -m pipeline.cli report weekly --week 2026-W12
python -m pytest -q /Volumes/Crucial\ X10/Documents/GitHub/quant-dojo/tests/test_control_plane.py
python -m pytest -q /Volumes/Crucial\ X10/Documents/GitHub/quant-dojo/tests
```

Before convergence, replace placeholders with at least one real backtest command and at least one dashboard/API integration verification path.

## Manual Verification

- [ ] run a real backtest from the unified CLI
- [ ] inspect the saved run artifact on disk
- [ ] fetch the same run through dashboard service or API
- [ ] compare two runs through the standard interface
- [ ] confirm a mutating control-surface command returns `requires_approval` before approval
- [ ] confirm the approved path executes and persists expected output
- [ ] perform two separate post-implementation review loops and record that neither found a new material issue

## Status

- `ACTIVE`: implementation or convergence review still ongoing
- `BLOCKED`: blocked by a specific missing dependency or unresolved design conflict
- `CONVERGED`: allowed only after both post-implementation review loops find no new material issue
