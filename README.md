# Codex Orchestration

Route planning, review, design, and implementation work to bounded model roles while the model selected for the Codex task remains in charge.

This repository is the independently maintained `jimnguyendev/Codex-Orchestration` fork of CJ Zafir's original project. It preserves the original attribution and MIT license while carrying fork-specific Executor fallback, state-binding, compare-and-swap, and Windows-locking work.

Vietnamese documentation: [README-vi.md](README-vi.md)

## What is it?

Codex Orchestration is a Codex plugin for assigning models to five clear roles:

- Root: understands the request, owns decisions, integrates work, verifies the final tree, and answers the user.
- Planner: creates or revises a bounded plan when planning is useful.
- Advisor: independently reviews that plan and returns an explicit decision.
- Designer: produces a design handoff for work where UX or visual judgment matters.
- Executor: implements a bounded packet selected by Root.

Codex remains the root orchestrator. The plugin adds routing policy to Codex's existing multi-agent flow; it does not replace Codex, create a second scheduler, or force every task through every role. Codex decides when delegation or parallel work is useful.

## How it works

```text
                    CODEX COORDINATES THE WORK
                              |
                              v
                 PLANNER CREATES THE FIRST PLAN
                              |
                              v
                      ADVISOR REVIEWS IT
                              |
                     approved or revised
                              |
                              v
                    EXECUTORS IMPLEMENT IT
                              |
                              v
                     CODEX TESTS & DELIVERS
```

Planner and Advisor are optional. A configured Advisor uses an eight-round bounded approval loop with a safety limit of eight reviews, stopping immediately on approval. Root owns the canonical plan, findings ledger, implementation release, integration, and final verification.

The plugin never creates credentials or bypasses permissions. Existing Codex sandbox, approval, Git, and user-authority boundaries still apply.

## Why use it?

- Spend stronger planning or review capacity only where judgment is useful.
- Use focused Executors for bounded implementation without giving up Root ownership.
- Keep model/provider choices explicit and fail closed when a requested route is unavailable.
- Use Fable or Opus through a sealed, no-tools, no-session-persistence bridge.
- Preserve exact restore state so setup, repair, and disable do not broadly rewrite Codex configuration.

On suitable independent work, the target is up to 2x faster on suitable tasks and to hit premium-model limits about 40% less often. These speed and limit figures are targets, not guarantees; task shape, context duplication, reviews, retries, tools, and service tier can materially change the result.

## Quick start

After installation and a full Codex Desktop restart, enter this prompt in a new task:

```text
$codex-orchestration:codex-orchestration setup planner: Claude Fable 5 High, advisor: GPT-5.6 Sol High, executor: GPT-5.6 Luna Extra High
```

Fable defaults to **High**. You may choose **Low**, **Medium**, **High**, **XHigh**, or **Max**. **Ultra** is accepted as an alias for Max because Claude Code exposes the effective value as `max`.

For a minimal direct Executor setup:

```text
$codex-orchestration:codex-orchestration setup executor: GPT-5.6 Luna Extra High
```

For a same-provider Designer:

```text
$codex-orchestration:codex-orchestration setup designer: GPT-5.6 Sol High, executor: GPT-5.6 Luna Extra High
```

For the sealed Opus subscription route, choose one Planner or Advisor seat:

```text
$codex-orchestration:codex-orchestration setup planner: Claude Opus 5 High, advisor: GPT-5.6 Sol High, executor: GPT-5.6 Luna Extra High
```

Claude Opus 5 requires Claude Code 2.1.219 or newer. Both bundled Claude routes use the user's first-party Claude Code login, so you do not need to add an Anthropic API key to Codex.

## Install

Requirements:

- Codex Desktop or another compatible Codex client with plugins and multi-agent v2;
- Python 3.11 or newer for the bundled configurators;
- the official Claude Code CLI only when using Claude Fable 5 or Claude Opus 5;
- a clean restart after plugin or persistent routing changes.

Install this fork's marketplace and plugin:

```bash
codex plugin marketplace add jimnguyendev/Codex-Orchestration
codex plugin add codex-orchestration@codex-orchestration
```

Fully quit and reopen Codex Desktop, then start a new task. Confirm the installation with:

```bash
codex plugin list --json
```

The installed entry must be enabled, use the canonical Git marketplace source `https://github.com/jimnguyendev/Codex-Orchestration`, and report version 0.9.4 or newer.

## Choosing routes

### Models already available through Codex

Use direct model routes for models available through the same provider as Root. A direct child route keeps Root's provider; it cannot silently switch providers.

### Bundled Claude subscription routes

Fable 5 is the bundled cross-provider exception historically used for one Planner or Advisor seat. Claude Opus 5 is a second sealed subscription model for the same seat types. The plugin invokes the official Claude Code CLI with a minimal environment, no tools, no session persistence, pinned model and effort, and fail-closed runtime identity checks.

Only one bundled Claude subscription seat can be active in a saved policy, so Planner and Advisor stay independent.

### Other providers and custom agents

Other unbundled providers must already be configured and authenticated. Cross-provider custom roles require an existing authenticated, compatible provider and a provider-pinned custom agent.

Project roles live under `.codex/agents/`. Personal roles live under `~/.codex/agents/`. New files load only in a new task, and a project role with the same name can shadow a personal role, so status validation fails closed on ambiguity.

Create a bounded project role with:

```text
$codex-orchestration:codex-orchestration create project role: researcher
```

The audited External Model lifecycle is documented in the [External Models reference](plugins/codex-orchestration/skills/codex-orchestration/references/external-models.md). Detailed provider and routing boundaries are in [providers and models](plugins/codex-orchestration/skills/codex-orchestration/references/providers-and-models.md).

Asking `is Kimi available to use as Designer?` is read-only discovery. It never authorizes configuration, credentials, or spend. The answer distinguishes supported, configured, locally ready, and callable now.

## Saved Executor fallback

Version 0.9.4 preserves this fork's opt-in Executor fallback in routing schema 6. It is a narrow model-visible policy, not an engine scheduler feature:

- both primary and fallback must be different direct same-provider models;
- the fallback is used at most once;
- eligibility exists only when the immediately preceding spawn returns no child provenance and exactly reports the saved primary as an unknown model while listing the saved fallback as available;
- every request field is preserved except `model` and `reasoning_effort`;
- permission, authentication, provider, rate, timeout, cancellation, post-child, mixed, or ambiguous failures never trigger fallback;
- an explicit task-local Executor route or `no subagents` suppresses both saved routes.

Example intent:

```text
$codex-orchestration:codex-orchestration setup executor: GPT-5.6 Luna Extra High, executor fallback: GPT-5.6 Terra High
```

Status proves saved policy consistency, not live callability or fallback eligibility. Make one exact read-only child probe in a fresh task before relying on a custom or direct route.

## Operations

Inspect the saved policy and current workspace compatibility:

```text
$codex-orchestration:codex-orchestration status
```

Update only this plugin from its canonical marketplace:

```text
$codex-orchestration:codex-orchestration --update
```

After an update, fully restart Codex Desktop and start a new task; an already loaded skill or MCP process cannot be replaced in place.

If status reports narrowly repairable managed hint drift, use:

```text
$codex-orchestration:codex-orchestration repair
```

Repair restores only validated plugin-owned mode and usage hints. It preserves restore snapshots, seat routes, launcher settings, credentials, chats, sessions, and concurrent valid state replacements.

Disable persistent native routing with:

```text
$codex-orchestration:codex-orchestration disable
```

`disable` restores the routing values captured before setup and removes the validated plugin-owned state. It does not uninstall the plugin.

## Upgrade notes

Version **0.6.0 or newer** is required for External Model roles. Version 0.7.x added native update, repair, Designer, and Kimi lifecycle handling. Version 0.8.x added sealed direct External Model invocation. Version 0.9.4 combines Claude Opus 5, hardened Fable decisions, eight Advisor reviews, the saved Executor fallback, route binding, CAS rollback, and Windows locking in schema 6.

If `codex plugin list --json` still reports an older version or `marketplaceSource.sourceType` is `local`, the client is using a local checkout rather than this fork's canonical Git marketplace. Disable an active saved policy before removing or replacing that registration, then reinstall and restart.

Before downgrading to a plugin that predates the saved routing schema, disable with the current version first. Older versions intentionally fail closed on unknown state.

Upstream releases 0.9.0 through 0.9.3 used schema 5 for a different Opus-bearing state shape, while this fork already used schema 5 for fallback and route binding. Before switching an active installation from that upstream version to this fork, run `disable` with the upstream installation, then install this fork and create a fresh schema-6 policy. The validator intentionally refuses to guess between colliding schema-5 shapes.

## Uninstall

First disable the managed routing policy from a current task, then remove the plugin and marketplace with Codex's native plugin manager. `disable` does not delete user-owned custom roles, because those files may contain user changes or unrelated roles. Review and remove any user-owned custom roles separately.

Removing the plugin without disabling first can leave valid managed routing hints loaded in Codex config. Reinstall the current version and disable cleanly if that happens.

## Security model

- Root remains responsible for scope, architecture, integration, review, and delivery.
- Planner and Advisor are root-directed, read-only seats and cannot release Executor work.
- Bundled Claude calls are sealed to exact models and locally validated structured decisions.
- Routing state is exact-schema validated and bound into both managed hints.
- App Server config writes use optimistic concurrency; state writes use byte-exact CAS and Unix or Windows file locking.
- Saved fallback behavior is intentionally narrower than ordinary retry logic.
- External credentials never belong in chat, prompts, Git, state, or logs.
- Local preflight results are partial; hosted protected checks remain authoritative.

Report suspected vulnerabilities through this fork's private GitHub vulnerability reporting page, without including credentials or private configuration.

## Development

Fast local feedback:

```bash
python3 scripts/preflight.py quick
```

Required local handoff gate:

```bash
python3 scripts/preflight.py full
```

Every behavior fix needs an exact regression test. Plugin payload changes require a strictly greater semantic version. Security or state changes require a threat model, malformed and negative-path tests, and a fresh final-tree review bound to the exact head SHA.

## License and attribution

Original project by CJ Zafir. This independently maintained fork is distributed under the MIT license; see [LICENSE](LICENSE).
