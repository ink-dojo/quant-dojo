# Goal: Control Plane (2026-03-23)

## Goal

Make `quant-dojo` operable through a single control plane:

- a **terminal-first execution surface** for backtests, comparisons, signal generation, rebalancing, risk checks, and reporting
- a **dashboard observation surface** that reads standardized run artifacts and exposes safe manual triggers
- a **stable system contract** that future AI agents can call without importing arbitrary internal modules

This goal is complete only when the repo feels less like "many useful scripts" and more like "one coherent operator system."

## Why This Matters

- Phase 5 can become operationally credible only if execution paths are standardized and auditable.
- Dashboard work will stay shallow unless it is backed by a unified run model and artifact contract.
- Future AI automation is dangerous if agents can bypass CLI contracts, state assumptions, and risk gates.
- Without a control plane, every new strategy or experiment increases chaos instead of system capability.

## Scope

### In Scope
- [ ] unify backtest and operational commands under a coherent CLI tree
- [ ] define a strategy registry / run contract instead of ad hoc script invocation
- [ ] standardize backtest artifacts and run metadata
- [ ] expose those standardized artifacts in the dashboard
- [ ] define how future AI agents should call the system safely

### Out of Scope
- [ ] full autonomous trading
- [ ] broker API / real-money execution
- [ ] multi-user auth, cloud productization, or external deployment hardening
- [ ] visual polish that does not improve operator clarity
- [ ] new strategy research unless required to prove the control-plane contract

## Current Verified State

### Already Exists
- [x] Phase 5 paper-trading spine exists: `signal -> rebalance -> risk -> weekly report`
- [x] CLI entrypoint already exists at [cli.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/pipeline/cli.py)
- [x] dashboard FastAPI skeleton already exists at [app.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/dashboard/app.py)
- [x] dashboard routers already cover portfolio, signals, factors, risk, data, AI, and pipeline
- [x] recent Phase 5 fixes improved correctness, restart safety, and weekly reporting

### Current Gaps
- [ ] CLI is useful but not yet a single, hierarchical operator interface
- [ ] there is no strategy registry with standard names, parameter schema, and run contract
- [ ] backtest outputs are not yet standardized into one artifact model that dashboard and AI can both consume
- [ ] dashboard shows slices of the system but not a unified run history across strategies and pipelines
- [ ] there is no explicit AI-safe entrypoint contract; future agents would be tempted to import internals directly

## Operational Outcome

When this goal is done, the system should be able to:

- [ ] run any supported strategy backtest from one CLI namespace
- [ ] compare multiple strategies or parameter runs from one CLI namespace
- [ ] persist a standard run record with metadata, metrics, and artifact paths
- [ ] let dashboard show recent runs, top metrics, parameters, and provenance without re-implementing business logic
- [ ] let a future AI agent trigger approved control-plane commands instead of calling arbitrary modules

## Design Principles

### 1. Terminal First

Execution belongs in the terminal and Python runtime, not in dashboard-only logic.

- the CLI is the authoritative execution surface
- dashboard may trigger runs, but through the same service / command contract
- if a feature only exists in the dashboard, the control plane is not complete

### 2. Artifact First

Every important run should leave behind a machine-readable artifact.

- backtest metrics
- parameter set
- date range
- strategy id
- data version / as-of date
- generated plots or file paths
- status and failure reason if the run did not succeed

Without this, there is nothing reliable for dashboard or AI to inspect.

### 3. Registry Over Ad Hoc Imports

Strategies must be discoverable and invokable through a registry, not via informal file knowledge.

### 4. Dashboard As Control Tower

Dashboard is for:

- seeing the current state
- comparing results
- reading risk and performance
- manually triggering approved tasks

Dashboard is not for inventing a second execution stack.

### 5. AI Uses The Same Control Plane

Future AI agents should:

- select a strategy from the registry
- launch a standard run
- read the run artifact
- propose next actions

They should not:

- import random internal modules directly
- mutate portfolio state outside defined execution paths
- bypass risk gates

## Implementation Plan

### Phase A: CLI Contract Unification

- [ ] redesign [cli.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/pipeline/cli.py) into a hierarchical command tree
- [ ] add a `backtest` namespace with at least:
  - [ ] `backtest run`
  - [ ] `backtest compare`
  - [ ] `backtest list`
- [ ] keep existing operational commands but align naming:
  - [ ] `signal run`
  - [ ] `rebalance run`
  - [ ] `risk check`
  - [ ] `report weekly`
  - [ ] `doctor`
- [ ] make help output readable enough that a human or agent can discover usage without code inspection

### Phase B: Strategy Registry

- [ ] create a strategy registry module defining:
  - [ ] strategy id
  - [ ] human-readable name
  - [ ] description
  - [ ] supported parameters
  - [ ] default lookback / data assumptions
  - [ ] callable entrypoint or adapter
- [ ] register current example and multi-factor strategies through that registry
- [ ] stop relying on "remember which file to import" as the operator contract

### Phase C: Standard Run Artifacts

- [ ] define a standard output directory for control-plane runs
- [ ] define a metadata schema for each run
- [ ] persist:
  - [ ] metrics summary
  - [ ] run config / params
  - [ ] timestamps
  - [ ] strategy id
  - [ ] date range
  - [ ] status / error message
  - [ ] links to plots or reports if generated
- [ ] make compare mode read those same artifacts instead of recomputing everything ad hoc

### Phase D: Dashboard Integration

- [ ] add dashboard endpoints for recent backtest runs
- [ ] add dashboard endpoints for strategy registry listing
- [ ] add dashboard views for:
  - [ ] recent runs
  - [ ] strategy comparison
  - [ ] run detail
  - [ ] manual trigger panel
- [ ] ensure dashboard reads standardized run artifacts rather than custom one-off files

### Phase E: Agent-Safe Control Surface

- [ ] document the approved commands and expected outputs for AI usage
- [ ] add a thin service layer, if needed, so dashboard and future agents call the same contract
- [ ] define which commands are read-only vs state-changing
- [ ] define what must be human-approved before a state-changing action is allowed

## File-Level Work

### CLI
- [ ] [cli.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/pipeline/cli.py)
  - redesign command tree
  - unify naming
  - add backtest namespace
  - add comparison flow

### Strategy Contract
- [ ] add `pipeline/strategy_registry.py` or equivalent
  - central strategy registration
  - parameter schema
  - callable adapters

### Backtest Integration
- [ ] [engine.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/backtest/engine.py)
  - expose standardized result object if current output is too loose
- [ ] relevant strategy files under [strategies](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/strategies)
  - adapt to registry contract where needed

### Run Artifacts
- [ ] add `pipeline/run_store.py` or equivalent
  - write run metadata and metrics
  - index historical runs
  - read runs back for comparison and dashboard

### Dashboard
- [ ] [app.py](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/dashboard/app.py)
  - register new run / strategy routes
- [ ] dashboard routers and services under [dashboard](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/dashboard)
  - consume registry and run artifacts
  - show recent runs, comparisons, and triggers
- [ ] [index.html](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/dashboard/static/index.html)
  - operator-oriented layout, not just metric tiles

### Docs
- [ ] [WORKPLAN.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/WORKPLAN.md)
  - keep this goal as the detailed next-step reference after Phase 5
- [ ] [ROADMAP.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/ROADMAP.md)
  - keep phase progression aligned with real execution order
- [ ] [README.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/README.md)
  - explain the operator workflow once implemented

## Definition Of Done

Do not close this goal unless all are true:

- [ ] at least one current strategy can be backtested through the unified CLI contract
- [ ] multiple runs can be compared through a standard interface
- [ ] recent runs are persisted and inspectable as artifacts
- [ ] dashboard can display recent runs and at least one comparison view from those artifacts
- [ ] dashboard trigger paths do not invent a second execution contract
- [ ] the goal file reflects the final verified system behavior

## Exit Gates

`STATUS: CONVERGED` is allowed only if all of the following are true:

- [ ] no scoped P0 gap remains in CLI contract, artifact persistence, or dashboard consumption
- [ ] a human can run a backtest, inspect artifacts, and open the dashboard without reading source code
- [ ] a future AI agent could reasonably use the documented control plane instead of direct imports
- [ ] manual verification proves that execution and observation surfaces agree on the same run data

If any gate fails, the agent must keep working or write back the exact blocker.

## Must-Pass Commands

```bash
python -m py_compile /Volumes/Crucial\ X10/Documents/GitHub/quant-dojo/pipeline/cli.py
python -m pipeline.cli --help
python -m pipeline.cli backtest list
python -m pipeline.cli backtest run <registered_strategy> --start 2023-01-01 --end 2024-12-31
python -m pipeline.cli backtest compare <run_id_1> <run_id_2>
python -m pytest -q /Volumes/Crucial\ X10/Documents/GitHub/quant-dojo/tests
```

Replace placeholder strategy ids and run ids with real values before convergence.

## Manual Verification

- [ ] run a backtest entirely through the new CLI contract
- [ ] inspect the generated run artifact on disk
- [ ] confirm dashboard reads and displays that run
- [ ] trigger one safe manual action from dashboard and confirm it uses the same contract
- [ ] verify the system still supports existing Phase 5 operational commands after the CLI redesign

## Risks To Watch

- [ ] dashboard accidentally forks business logic from CLI
- [ ] strategy registry becomes a thin wrapper with no real contract value
- [ ] artifact schema is too weak for dashboard and AI to consume
- [ ] command names drift from actual operator mental model
- [ ] "AI-ready" language appears in docs without a real control surface underneath

## Self-Review Checklist

Before marking done, the agent must verify:

- [ ] this work reduced operator fragmentation, not just added files
- [ ] the terminal really can serve as the single execution surface
- [ ] dashboard really is reading standardized run data
- [ ] the design would help future AI usage instead of making it more chaotic
- [ ] docs match the actual final control-plane behavior

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
