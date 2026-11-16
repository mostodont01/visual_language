# Plan: flows, optional inputs, incremental builds

Written 2026-11-17 from the RoboCars chat, for a separate chat working on VL in parallel.
RoboCars (`~/Programming/robots/robocars`) is VL's main user; everything here comes from
real problems there. Decisions marked **decided** were agreed with the user; the rest are
proposals the VL chat may refine (ask the user when a choice changes how graphs look).

## 0. First: commit the work in progress

This repo has uncommitted work that RoboCars already depends on:
`history.py` (branches + commits), `mcp_server.py`, `graph_layout.py`, `examples/test/` and
changes to `graph_model.py`, `main.py`, `project.py`, `ui/Main.qml`, `ui/components/SettingsPage.qml`,
`README.md`. Review, test and commit it (in sensible pieces) before starting anything below.

**Compatibility contract with RoboCars:** `tools/bench.py` and `tools/pi_bench.py` in RoboCars import
`compiler.generate_project(graph, catalog, packages, [], {"fullscreen": False}, out_dir, name)` and
`node_catalog.load_node_package(path)`. They also read `.vl` files directly (`project.json`,
`history/history.json`, `history/objects/*`). If these change, say so in the commit message and in
the "Changes RoboCars must follow" list at the bottom of this file.

## Order

1. **Optional inputs** (+ non-triggering inputs). Small; unblocks the RoboCars hardware nodes.
2. **Incremental builds** (the proper fix, **decided**). Makes everything after it faster to develop.
3. **Flows** (start-up / event trees). The biggest one.

Each step: tests (pytest for Python, a headless C++ test program for the runtime, `VL_FAST=1`),
then commit and push. RoboCars' bench (`python3 tools/bench.py` in the RoboCars repo) is the
end-to-end test: its results must not change (except build time).

---

## 1. Optional inputs  (**decided**: yes)

Today a node only runs once **every** input has a value, so an unconnected input without a widget
blocks the node forever and "optional" inputs don't exist.

Proposal:
- Node JSON, per input: `"optional": true` and an optional `"default": <value>` (falls back to the
  widget default, then `T{}`).
- **Optional inputs never gate the node.** Unconnected: gets the default once at creation.
  Connected: holds the default until the first value arrives.
- C++: `Input<T>::connected()` (set by the generated code) next to the existing `hasValue()`.
- Compiler / issues list: no "unconnected input" problem for optional inputs.
- UI: draw optional sockets slightly differently (e.g. hollow).

Same step, small and related: **non-triggering inputs**, `"triggers": false` in the JSON. Such an
input stores new values but doesn't start a run. Today a node runs whenever *any* input changes, so
Detect Obstacles re-used an old 10 Hz scan with new 30 Hz positions and saw ghost robots; it now skips
repeated data by hand. With this flag the scan input triggers and the position input just updates.

## 2. Incremental builds  (**decided**: proper fix, not just ccache)

Today `generated/main.cpp` `#include`s every node header and bakes every setting value in as a C++
literal, and builds start from a fresh folder. Any change recompiles a lot; the RoboCars bench
(14 scenes, only values differ between them) spends most of its ~4.5 min building. It also caused the
shared-helper-header problem: a helper header shipped by two nodes is included twice into main.cpp,
so RoboCars uses named `#ifndef ROBOCARS_X_HPP` guards (`#pragma once` failed randomly with GCC).

Proposal:
- **Values out of the code.** Settings and initial input values go to `generated/values.json`
  (or a simpler key=value format), read at start-up. Changing a value = **no compile at all**.
  A small JSON reader in the runtime is fine. (Bench: one build, 14 runs.)
- **main.cpp depends only on the graph's structure** (which nodes, which wires), so it only
  recompiles when nodes or wires change.
- **One translation unit per node type.** The generator writes `generated/node_<type>.cpp` that
  includes the node's header and registers a factory plus a port table (socket id → type-erased
  `InputBase*` / output with a type id). main.cpp includes only `vl/runtime.hpp` and the custom type
  headers, creates nodes through the factories and connects them by socket id (the compiler has
  already type-checked the wires; the runtime checks the type id once at start-up). Node headers
  and their helpers are then compiled once per node TU, which also ends the duplicate-header problem.
- **Persistent build folder** per project and target (e.g. `~/.cache/vl/build/<project-id>/<target>/`),
  Ninja, never wiped; the generator only rewrites files whose content changed (keeps mtimes, so
  Ninja skips them). Cross-compile targets (Zig: linux-arm64, windows) get their own folders.
- Use ccache automatically when installed (cheap extra).
- **Done when:** changing a setting rebuilds nothing; changing one node's `.cpp` recompiles one TU
  + link; adding a wire recompiles main.cpp only. Measure the RoboCars bench before/after.

## 3. Flows: start-up and event trees

**Decided with the user:**
- Flows run in **execution order** (like Blender/Unreal exec wires), not data order.
- A flow has an **end node**.
- The **main tree (today's dataflow graph) only starts after the start-up flow has finished.**
  Example: start the LiDAR (takes ~0.5 s to spin up), wait for it, then race.
- Emergencies are flows too.

Proposal for the details (chosen to fit RoboCars; confirm the UI parts with the user):

**Exec sockets.** A new socket type `exec` in the node JSON (`"type": "exec"` in `inputs` /
`outputs`), drawn differently (white, thicker wire). An exec output connects to one exec input; an
exec input may have many incoming wires. Flow nodes can also have normal data inputs and outputs.

**Flow nodes in C++.** `class FlowNode : public Node` with
`virtual void start()` (when execution arrives) and `virtual int update()` returning
`Running` or the index of the exec output to continue on. Never blocking: `update()` is called every
loop pass, so widgets, timers and the data nodes that the flow needs keep running meanwhile.
Uses `vl::now()`, so `VL_FAST` skips waits.

**Phases.**
- `On Start` (entry) → … → `Start Main` (end): the **start-up flow**. While it runs, the main tree
  doesn't. Graphs without `On Start` start main immediately (all existing graphs keep working).
- `On Event` (entry) with a bool data input `trigger` and a `priority` setting: fires on the rising
  edge, in any phase. It **stops the main tree** (and a lower-priority event flow) and runs its flow.
  End nodes: `Resume Main`, `Restart` (run the start-up flow again), `Stop Program`.
- **Which data nodes run when** (one rule): a data node runs whenever something active needs it.
  Main tree: all data nodes. During a flow: only the data nodes upstream of the data inputs of
  that flow's nodes (computed by the compiler). Event `trigger` inputs are watched in every phase,
  so their upstream nodes always run (e.g. battery monitor, emergency switch).
- **`stop()` hook** on `Node`: called when the main tree is stopped by an event and when the program
  exits (SIGINT/SIGTERM). A motor node sets its outputs to zero there, so "the robot stops" doesn't
  depend on any graph wiring. Optional `reset()` hook, called before `Restart` re-enters start-up.

**Built-in flow nodes (VL core):** On Start, On Event, Start Main, Resume Main, Restart,
Stop Program, Wait (seconds), Wait Until (bool input), Branch (bool → true / false), Log (message).
Loops in flows are allowed (an exec wire back to an earlier node).

**RoboCars example** (what this has to express):

    On Start → Wait Until [LiDAR ready] → Wait Until [start place chosen] → Wait Until [start button]
             → Start Main
    On Event [emergency switch or battery low or motor stalled] (priority 10)
             → Log "stopped: …" → Wait Until [all clear] → Restart

`LiDAR ready`, `start place chosen` (a data node that reads the button and drives the place LEDs) and
the trigger inputs are ordinary data nodes; they run during the flows because of the rule above.

**Done when:** the example runs headless with `VL_FAST=1` in a test (simulated button / trigger
nodes), Wait / Wait Until / Branch / events / Restart are covered by tests, existing graphs behave
exactly as before (RoboCars bench unchanged).

---

## Known runtime gotchas (from RoboCars, for context)

- Every input must have a value before a node runs (→ step 1).
- In a loop, the compiler picks feedback wires by DFS; they never trigger a run and start with the
  field value or `T{}`. Which wires get picked depends on the graph, so loops can deadlock.
  Workarounds used: nodes that close a loop send outputs in `setup()`; consumers run on a timer.
  (Worth revisiting after step 2: maybe let the node JSON mark feedback inputs explicitly.)
- A node runs whenever any input changes (→ `"triggers": false`, step 1).
- Shared helper headers included twice (→ step 2).

## Changes RoboCars must follow

(Fill in as you go: anything that changes the node JSON, the C++ node API, `generate_project`, or the
`.vl` file layout.)

- 
