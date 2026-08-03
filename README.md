# Codex Orchestration

Codex Orchestration keeps the model selected for the current Codex task in charge and
routes implementation volume through two explicit lanes:

- **GPT-5.6 Luna Max** for routine, bounded, low-risk work.
- **GPT-5.6 Terra Max** for hard, ambiguous, or high-risk work.

The root model owns requirements, architecture, integration, verification, and the
final answer. The plugin does not automatically create Planner, Advisor, Designer, or
final-review loops. It delegates only when a worker is likely to save more than the
handoff costs.

This is an independently maintained fork at
[`jimnguyendev/Codex-Orchestration`](https://github.com/jimnguyendev/Codex-Orchestration),
based on CJ Zafir's original project and distributed under the MIT license.

## How routing works

| Task shape | Lane |
| --- | --- |
| Mechanical edits, wiring, CRUD, straightforward tests, localized fixes | Luna Max |
| Security/auth/state, concurrency, migrations, hard debugging, broad refactors, unclear legacy contracts | Terra Max |

When uncertain, route to Terra. Trivial work stays in root when writing a handoff would
cost more than doing the work.

Each child receives a short five-part packet: objective, owned files, contracts, done
criteria, and verification. Different-model children use `fork_turns=none`; they do not
receive the full root transcript. This is a bounded cold handoff, not Elves-style
same-session prewalk and not cross-model KV-cache transfer.

The root inspects the actual diff and reruns relevant checks. Worker completion is not
final acceptance. Extra review is used only when requested or required by repository
and risk gates.

File count is advisory rather than a hard Luna limit. Routine work uses no Planner or
Advisor call by default; across all tasks the default budget permits at most one such
model call after an explicit request or repository/risk gate. A second model review
requires explicit current-task approval.

The complete Vietnamese documentation includes the architecture diagrams, exact
same-session prewalk boundary, cost/cache math, threat models, and step-by-step setup:
[`docs/README.md`](docs/README.md).

## Install

Requirements:

- Codex Desktop or another compatible Codex client with plugins and multi-agent v2;
- Python 3.11 or newer for optional persistent setup;
- a fresh Codex task after installation or routing changes.

```bash
codex plugin marketplace add jimnguyendev/Codex-Orchestration
codex plugin add codex-orchestration@codex-orchestration
codex plugin list --json
```

The installed entry should be enabled, point to the canonical Git marketplace, and
report version 0.10.0 or newer. Fully restart Codex after installing or updating.

Use the skill naturally or explicitly:

```text
$codex-orchestration:codex-orchestration route this implementation
$codex-orchestration:codex-orchestration use Luna Max for this routine task
$codex-orchestration:codex-orchestration use Terra Max because this migration is risky
```

## Optional persistent setup

Task-local routing is the default and supports both lanes. Persistent setup stores Luna
as the routine route and generates an explicit Terra Max hard/risky lane, so use it
only when you want durable routing hints. Version 0.10 accepts exactly Luna Max as the
persistent Executor; arbitrary/custom Executor routes stay task-local:

```text
$codex-orchestration:codex-orchestration setup executor: GPT-5.6 Luna Max
```

Inspect, repair, update, or disable the saved policy with:

```text
$codex-orchestration:codex-orchestration status
$codex-orchestration:codex-orchestration repair
$codex-orchestration:codex-orchestration --update
$codex-orchestration:codex-orchestration disable
```

Setup, repair, and disable are preview-first. The configurator uses Codex App Server
compare-and-swap, preserves unrelated settings, and stores exact restore values.
Status proves saved policy consistency, not live child callability. After upgrading a
policy created before 0.10, strict status reports `legacy workflow active`; run one
fresh explicit setup or disable it before relying on the new lanes. Marker-only
migration preserves an existing validated Fable/Opus seat when that seat is omitted.
If saved state is missing, status reports that repair and disable are unavailable.

## Optional Fable and Opus planning

Claude Fable 5 and Claude Opus 5 remain optional sealed Planner or Advisor routes.
They use the official Claude Code CLI, the existing first-party login, no tools, no
session persistence, and exact runtime model checks. They are never automatic and are
not implementation lanes.

```text
$codex-orchestration:codex-orchestration setup planner: Claude Fable 5 High, executor: GPT-5.6 Luna Max
$codex-orchestration:codex-orchestration setup advisor: Claude Opus 5 High, executor: GPT-5.6 Luna Max
```

Only one bundled Claude subscription seat may be saved. Opus requires Claude Code
2.1.219 or newer.

## What was removed in 0.10.0

Kimi K3, OpenRouter setup, credential enrollment, paid Gate 0 probes, and the generic
External Model lifecycle were removed. Kimi was the only bundled API-model route and
accounted for a large part of the plugin's code and instruction surface.

The historical saved Executor fallback remains accepted for state compatibility, but
it is not used as the Luna/Terra classifier. New tasks select their lane explicitly
before spawning.

## Cost and performance

The plugin does not promise a fixed percentage saving. A useful comparison includes
model-weighted input/output credits, duplicated context, reasoning output, tool calls,
retries, latency, and quality-driven rework.

Lowering the root model's reasoning effort can preserve same-model cache opportunity
and reduce reasoning work. A Luna child can still be cheaper even after a cold handoff
because its unit price is lower. Benchmark the actual task mix and verify current
pricing before publishing exact claims.

## Security and evidence

- Root remains responsible for permissions, scope, integration, and delivery.
- The plugin never creates credentials or bypasses sandbox and approval controls.
- Requested model and effort never silently fall back.
- Saved state and config changes fail closed on malformed or ambiguous ownership.
- Local checks are partial; protected hosted checks remain authoritative.

## Development

Fast local feedback:

```bash
python3 scripts/preflight.py quick
```

Required local handoff gate:

```bash
python3 scripts/preflight.py full
```

Every behavior fix needs an exact regression test. Plugin payload changes require a
strictly greater semantic version. Security or state changes require a threat model,
negative and malformed-path tests, and a fresh final-tree review bound to the exact
head SHA.

## License

Original project by CJ Zafir. This maintained fork remains available under the MIT
license; see [LICENSE](LICENSE).
