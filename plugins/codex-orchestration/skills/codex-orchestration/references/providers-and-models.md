# Providers and models

Load this reference only for persistent setup, custom-provider boundaries, Claude
subscription routing, or legacy recovery. Routine task-local Luna/Terra routing is
fully defined in `SKILL.md`.

## Direct Codex routes

The default lanes are exact direct child routes on the active Codex provider:

| Work shape | Model | Effort | Context mode |
| --- | --- | --- | --- |
| Routine, bounded, low-risk | `gpt-5.6-luna` | `max` | `fork_turns=none` |
| Hard, ambiguous, or high-risk | `gpt-5.6-terra` | `max` | `fork_turns=none` |

If the current task is already a GPT-6 Astra root (`gpt-6-astra`), hard/risky work
stays in root instead of being downgraded to Terra. A direct Astra child route is
valid only when the active callable model catalog exposes the exact `gpt-6-astra`
ID; otherwise report it unavailable without substitution. Luna remains available
for genuinely routine, bounded slices.

The active task model remains root. A direct child route cannot silently cross to a
different provider. Exact route acceptance still depends on the current task's tool
schema and model catalog; a saved policy or visible model description does not prove
that the current child route is callable.

Evidence levels:

- **configured:** a policy or custom-agent file contains the route;
- **available:** the active host catalog exposes the exact model and effort;
- **route accepted:** the spawn API accepted the exact request;
- **used and confirmed:** runtime metadata exposes the effective model and effort.

Never infer the last two levels from child prose.

## Context and caching boundary

`fork_turns=none` intentionally avoids copying the root transcript. The worker receives
one bounded packet and inspects the repository directly. This reduces duplicated input
but starts a new child session. It is not Elves-style prewalk and does not transfer a
KV cache between models.

True prewalk requires the host to preserve one worker session while changing its model
after orientation, a bounded TODO, and the first real edit. If the host later exposes
that primitive, qualify it independently before changing this contract.

## Persistent native policy

`configure_native_routing.py` manages these Codex settings through App Server
compare-and-swap rather than rewriting TOML:

- `features.multi_agent_v2.hide_spawn_agent_metadata`;
- `features.multi_agent_v2.tool_namespace`;
- `features.multi_agent_v2.multi_agent_mode_hint_text`;
- `features.multi_agent_v2.usage_hint_text`;
- the one selected bundled Claude MCP launcher when applicable.

It stores exact restore values in namespaced state and fails closed on malformed,
ambiguous, concurrently replaced, or incompatible state. `status` validates policy
consistency; it does not perform a child model call.

Persistent setup stores Luna as the routine Executor and generates an exact Terra Max
hard/risky lane for non-Astra roots in both managed hints. New setup rejects every persistent Executor
other than `gpt-5.6-luna@max`, including custom agents. Since classification still
happens per task, task-local routing remains the simplest path. A pre-0.11 managed hint pair is reported
as `legacy workflow active` until one explicit setup replaces the hints or the policy
is disabled. Its state stays readable for status, repair, and disable. The historical
saved Executor fallback remains accepted for compatibility but is not the hard-task
lane: it can react only to its narrowly specified unknown-model error.

If marker-owned hints survive without saved state, status reports that repair and
disable are unavailable. Both operations fail before any config write; a fresh exact
Luna Max setup can create new bounded restore state after review.

## Claude subscription routes

Claude Fable 5.1 and Claude Opus 5.5 are optional Planner or Advisor routes. They use
the official Claude Code CLI and an existing first-party Pro, Max, or Team login.
They are never default implementation workers. Fresh Fable setup selects 5.1 and fresh
Opus setup selects 5.5; the older Fable and Opus rows are retained only for exact
saved-state compatibility.

Sealed contracts:

| Provider ID | Model ID | Seats | Efforts |
| --- | --- | --- | --- |
| `claude-fable` | `claude-fable-5-1` | Planner or Advisor | `low`, `medium`, `high`, `xhigh`, `max` |
| `claude-fable` | `claude-fable-5` | Planner or Advisor | `low`, `medium`, `high`, `xhigh`, `max` |
| `claude-opus` | `claude-opus-5-5` | Planner or Advisor | `low`, `medium`, `high`, `xhigh`, `max` |
| `claude-opus` | `claude-opus-5` | Planner or Advisor | `low`, `medium`, `high`, `xhigh`, `max` |

Only one bundled Claude subscription seat may be saved. Planner operations are
`create_plan` and `revise_plan`; Advisor uses `review_plan`. The bridge runs without
tools or session persistence, pins model and effort, minimizes inherited environment,
and validates runtime model metadata. Fable 5.1 requires Claude Code 2.1.255 or newer
and remains primary-only until its fallback/helper identities are live-qualified.
The legacy Fable 5 runtime allowlist is not inherited. Opus 5.5 requires Claude Code
2.1.292 or newer and is primary-only; saved Opus 5 routes keep the 2.1.219 minimum.

Setup and status may check version, supported flags, and first-party authentication,
but they do not make a planning/review model call. Never expose tokens or account
metadata. The plugin does not create Claude credentials or replace Team login with
an API key.

## Custom agents and other providers

`configure_orchestration.py` may create a bounded custom role only after the user asks
for one, but 0.11 emits no `model_provider`. A project role belongs in `.codex/agents/`;
a personal role belongs under the active Codex home. A project role can shadow a
personal role with the same name, so status must fail closed on ambiguity. The retired
provider flags are rejected before any write. Existing managed provider-pinned role
files remain valid only for exact inspection and removal compatibility.

Provider authentication and configuration outside the active Codex provider are
user-owned. Codex Orchestration no longer bundles Kimi, OpenRouter, credential-store
helpers, paid capability probes, or a generic External Model lifecycle. Do not route
those models through this plugin, generate a provider-pinned role for them, or imply
that an unbundled provider is ready.

## Legacy compatibility

Current routing state accepts historical schemas only through exact validators. Schema
5 has incompatible upstream and fork histories; never guess between them. When moving
an active installation across those histories, disable with the version that created
the state, install the target version, then create a fresh policy.

Changing between Fable and Opus seats can require a full disable and fresh setup so
restore data and launcher ownership remain unambiguous. Do not manually edit the saved
state or routing hints to bypass that gate.

## Honest cost comparisons

Compare total model-weighted credits:

```text
total = root_input + root_output + child_input + child_output + retries + review
```

Use current published prices and observed token accounting. Same-model lower effort can
reduce reasoning output and preserve cache opportunity, while a cheaper child can win
despite a cold handoff. Neither is universally cheaper. Include duplicated context,
tool calls, retries, latency, and quality-driven rework in any benchmark.
