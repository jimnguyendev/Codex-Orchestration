---
name: codex-orchestration
description: Route bounded implementation work to GPT-5.6 Luna Max for routine tasks or GPT-5.6 Terra Max for hard, ambiguous, or high-risk tasks while the current Codex task remains root. Use for model routing, delegated implementation, setup, status, repair, disable, custom roles, or optional Claude Fable 5 and Claude Opus 5 planning and review.
---

# Codex Orchestration

Keep the model selected for the current Codex task as root. Root owns user intent,
architecture, routing, integration, verification, permissions, and the final answer.
The default workflow has one routing decision and one implementation worker; it does
not automatically create Planner, Advisor, Designer, or review loops.

Explicit invocation: `$codex-orchestration:codex-orchestration route this implementation`.

## Default routing policy

Do not delegate trivial work that root can finish faster than writing and validating a
handoff. Otherwise choose exactly one implementation lane before the first spawn:

- **Luna Max — routine:** bounded, well-specified, low-blast-radius work whose result
  is largely determined by existing contracts. Examples: mechanical edits, wiring,
  CRUD, straightforward tests, and localized bug fixes.
- **Terra Max — hard or risky:** work needing material judgment, broad context, or
  stronger failure analysis. Examples: security/auth/state changes, concurrency,
  data loss or migration risk, difficult debugging, non-trivial algorithms, broad
  refactors, unclear legacy behavior, public contracts, and large blast radius.

Apply a warm-root gate before choosing Luna. Keep the work in root when root already
holds the relevant implementation context, the owned paths overlap a dirty integration,
or a cold child would have to rediscover several packages before editing. A Luna slice
should normally have a known change surface of at most three owned files or one narrow
module. A slice spanning database schema, migration, seed, API wiring, and tests is
Terra/state work even when its ownership is bounded. Bounded ownership alone does not
make a task routine.

When uncertain, use Terra. Route by task shape rather than model prestige. A user's
explicit lane or `no subagents` instruction overrides this default.

Use the exact task-local route when the host exposes direct child routing:

```text
Routine: model=gpt-5.6-luna, reasoning_effort=max, fork_turns=none
Hard/risky: model=gpt-5.6-terra, reasoning_effort=max, fork_turns=none
```

Never silently substitute another model or effort. An unavailable route is a blocker,
not permission to fall back. Report `route accepted` only when the spawn call accepts
the exact route. Report `used and confirmed` only when runtime metadata exposes the
effective child model and effort. Child prose is not routing evidence.

## Keep handoffs small

Different-model children start from a bounded packet with `fork_turns=none`. Do not
paste the conversation, a complete plan, repeated repository descriptions, full logs,
or files the worker can inspect itself. Send only these five sections:

```text
OBJECTIVE
<one observable outcome>

OWNERSHIP
<exact files/modules the worker may change; preserve unrelated work>

CONTRACTS
<interfaces, invariants, settled decisions, and relevant facts only>

DONE WHEN
<acceptance criteria and stop conditions>

VERIFY AND RETURN
<smallest useful checks; return status, changed files, evidence, and remaining risk>
```

Keep the packet under 1,200 words unless the task itself requires more. Prefer file
paths and precise facts over copied content. One worker owns one bounded slice. Run
workers in parallel only when write ownership and dependencies are genuinely
independent; otherwise run serially.

For Luna, add two explicit stop conditions to `DONE WHEN`: `FIRST ARTIFACT` and
`READ BUDGET`. Before the first edit or exact regression test, Luna may make at most
three batched discovery tool calls. Within 120 seconds it must create the smallest safe
artifact or return `BLOCKED` with the newly discovered ambiguity. These are
orchestration stop conditions, not host-enforced time or token limits.

This packet preserves the trajectory but is not Elves-style prewalk. True prewalk
switches models inside the same worker session after orientation, a bounded TODO, and
the first real edit. A new Codex child is a cold handoff even when its packet is good;
do not claim KV-cache or same-session continuity.

## Escalation and retries

If Luna discovers hidden ambiguity or risk, it must stop before broadening scope and
return the new facts. Root then corrects the packet and may make one Terra attempt.
Do not send an unchanged prompt, run Luna and Terra competitively, or use Terra merely
because Luna returned an ordinary implementation failure.

The saved Executor fallback from older plugin versions is compatibility-only. It is
not the Luna/Terra routing policy: it reacts narrowly to an unknown-model error and
must never be used to classify hard work. New workflows should select Luna or Terra
explicitly before spawning.

## Luna progress and takeover protocol

Do not infer a stall from silence or elapsed time alone. At the 120-second first-artifact
gate, root must inspect the worker-owned diff before sending a message or claiming no
work exists. A file edit or exact new regression is progress even if Luna has not sent
a checkpoint. If no artifact exists, send one `checkpoint now` request and allow at
most 60 more seconds. If a partial artifact exists but no new artifact appears for 180
seconds, request a checkpoint once, allow at most 60 more seconds, and then stop the
seat.

Before interrupting, snapshot the owned-path diff. After interrupting, wait for the
child to reach a terminal state and snapshot the diff again. Reconcile and attribute
every partial edit before root takes ownership; root must not edit the same paths or
say “no changes” before this handoff completes. Never launch an unchanged retry.

## Verification

Worker reports are claims. Root must inspect the actual diff, confirm scope, rerun the
smallest relevant checks, and judge the outcome against the user's request. Use an
additional reviewer only when the user requests one or the repository/risk gate
requires independent review. Do not add a routine final-review spawn to every task.

For security, authentication, state, destructive behavior, migrations, or public API
changes, use Terra and follow repository-specific threat-model, negative-test, and
review requirements. The plugin never weakens approvals, permissions, sandboxing,
global agent limits, or Goal ownership.

## Optional planning and review

Planner and Advisor are opt-in. Do not invoke them merely because they are configured.
Use them when the user explicitly requests planning/review or when a repository gate
requires it. Carry only the current plan, original constraints, and a compact findings
ledger; never replay the full transcript. Stop on approval and avoid repeated reviews
that do not add new evidence.

Claude Fable 5 and Claude Opus 5 remain sealed first-party subscription routes for one
Planner or Advisor seat. They use the official Claude Code login, no tools, no session
persistence, exact model/effort validation, and the bundled bridge. They are not
implementation lanes. Read
[providers-and-models.md](references/providers-and-models.md) only when configuring or
diagnosing these routes, custom agents, provider boundaries, or legacy state.

Kimi, OpenRouter, credential enrollment, paid Gate 0, and generic External Model
lifecycle management are not part of this plugin. Never claim they are bundled or
prepare those routes through Codex Orchestration.

## Task-local behavior

Task-local routing is the default because it avoids a persistent policy when one
choice per task is enough. Use the strongest exact mechanism exposed by the host:

1. direct `model` plus `reasoning_effort` with `fork_turns=none`;
2. a loaded custom agent pinned to the exact route;
3. `unavailable` when neither exact route exists.

Do not downgrade an exact request to a prompt preference. Do not create or change
Goal state; root retains it. Executors do not spawn descendants and do not call the
optional Planner/Advisor bridge.

## Persistent native setup

Persistent setup is optional. It stores the Luna routine route while the generated
policy pins Terra Max for hard/risky work; classification still happens per task. Use
it only when the user explicitly asks for `setup`. Version 0.10 persistent setup
accepts exactly `gpt-5.6-luna` at `max`; arbitrary/custom Executor routes remain
task-local. Existing non-Luna saved routes are compatibility state for status, repair,
and disable, not templates for a new policy. Resolve the active host's Codex binary,
then run the installed script from this skill directory. Preview before apply:

```bash
python3 <skill-dir>/scripts/configure_native_routing.py \
  --codex-bin <active-codex-binary> \
  --executor-model gpt-5.6-luna \
  --executor-effort max

python3 <skill-dir>/scripts/configure_native_routing.py \
  --codex-bin <active-codex-binary> \
  --executor-model gpt-5.6-luna \
  --executor-effort max \
  --apply
```

A literal setup request authorizes a clean apply after preview, but not replacement of
unrelated user policy. Start a new Codex task after apply. Use `--planner-fable`,
`--planner-opus`, `--advisor-fable`, or `--advisor-opus` only when the user explicitly
selects that optional seat. Do not configure a saved Luna-to-Terra fallback as the
normal two-lane policy.

After upgrading an active policy created before 0.10, `status --require-effective`
reports `legacy workflow active`. Existing state remains valid for status, repair, and
disable. Run one explicit fresh setup to replace the managed hints with the two-lane
workflow, or disable the saved policy and use task-local routing. A marker-only
migration preserves an existing validated Fable or Opus seat when that seat is omitted
from the fresh setup; replacing or removing a sealed seat still requires an explicit
complete transition. If the hints survive without saved state, status must say that
repair and disable are unavailable instead of presenting them as recovery paths.

The configurator uses Codex App Server `config/read` and `config/batchWrite`, preserves
unrelated settings, validates state, and stores exact restore data. Existing conflict
rules and schema compatibility remain fail-closed.

## Status, repair, disable, and update

Run these operations only when requested, from the target project, using the active
host binary and the installed skill path.

Status is read-only:

```bash
python3 <skill-dir>/scripts/configure_native_routing.py \
  --codex-bin <active-codex-binary> --status
```

Use `--status --require-effective` for a strict gate. Policy status proves config and
saved-state consistency, not live child callability. Make one bounded read-only child
probe when exact runtime routing matters.

Repair only the narrowly validated managed-hint drift. Preview, then apply:

```bash
python3 <skill-dir>/scripts/configure_native_routing.py \
  --codex-bin <active-codex-binary> --repair
python3 <skill-dir>/scripts/configure_native_routing.py \
  --codex-bin <active-codex-binary> --repair --apply
```

Disable restores the saved pre-setup values. Preview, then apply:

```bash
python3 <skill-dir>/scripts/configure_native_routing.py \
  --codex-bin <active-codex-binary> --disable
python3 <skill-dir>/scripts/configure_native_routing.py \
  --codex-bin <active-codex-binary> --disable --apply
```

Never erase managed fields that changed after setup. `repair` and `disable` do not
change credentials, chats, sessions, or user-owned custom roles.
When managed hints survive without saved restore state, both repair and disable fail
closed without a config write. Review the hints and run a fresh exact Luna Max setup
to create new state, or remove the stale hints manually.

`--update` means update only this plugin from the canonical marketplace
`https://github.com/jimnguyendev/Codex-Orchestration`. Refuse ambiguous, local,
disabled, duplicate, or unexpected sources. After update, restart Codex and begin a
new task; an already loaded skill cannot hot-reload.

## Custom roles

Create custom roles only when explicitly requested. Project roles live under
`.codex/agents/`; personal roles live under the active Codex home. Preview changes
with `scripts/configure_orchestration.py` and apply only after clean validation. Never
overwrite an unmanaged file or delete edited/user-owned roles. Version 0.10 creates
only active-provider roles without `model_provider`; the retired `--executor-provider`
and `--advisor-provider` flags fail closed even when that provider already exists in
user config. Existing managed provider-pinned files remain readable and removable,
but the plugin does not recreate them. New roles load in a fresh task.

## Cost and speed claims

Do not promise a fixed saving. Compare model-weighted credits, duplicated input,
reasoning output, tool calls, retries, and rework. Lowering root reasoning effort can
save time and reasoning tokens while preserving one model's cache opportunity, but it
does not change that model's unit price. A Luna handoff may still win when its lower
unit cost exceeds cold-start overhead; verify current prices before publishing exact
percentages. Report logical input, cached input, uncached input, output, wall time,
first-artifact latency, and rework separately; a large cached share does not make a
run operationally free.

## Packaged resources

- `scripts/configure_native_routing.py`: persistent setup, status, repair, and disable.
- `scripts/configure_orchestration.py`: custom-agent creation and legacy migration.
- `scripts/fable_advisor_mcp.py`: sealed Fable/Opus Planner or Advisor bridge.
- `scripts/external_subscription.py`: validated dispatch for the two Claude routes.
- `scripts/inspect_models.py`: host model-catalog diagnostics.
- [providers-and-models.md](references/providers-and-models.md): optional advanced and legacy details.
