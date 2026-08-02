# Security policy

## Supported versions

Security fixes are made on the latest released version. Upgrade before reporting a
problem already fixed on `main`.

## Report a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/jimnguyendev/Codex-Orchestration/security/advisories/new).
Include the affected plugin and Codex versions, operating system, installation scope,
minimal reproduction, impact, and known workaround. Do not include credentials,
tokens, or private configuration.

## Runtime boundaries

The current Codex task remains root and retains user intent, permissions, integration,
verification, and final acceptance. Task-local workers receive bounded packets. The
plugin does not weaken sandboxing, approvals, Goal ownership, or global agent limits.

The default implementation lanes are exact direct routes: Luna Max for routine work
and Terra Max for hard or high-risk work. A missing or rejected route fails closed;
there is no silent model or effort substitution. Spawn acceptance and effective model
identity are reported separately, and child self-report is never identity evidence.

Different-model workers use `fork_turns=none`. This limits transcript disclosure but
does not create same-session prewalk or transfer a KV cache. The worker still receives
delegated prompt content and can inspect files allowed by the active permission profile.

## Persistent routing state

Native setup, status, repair, and disable use Codex App Server `config/read` and
`config/batchWrite`. They preserve unrelated settings, validate exact state schemas,
bind managed routes into marked hints, use optimistic concurrency plus state-file
locking, and keep byte-exact restore data. Malformed, ambiguous, stale, shadowed, or
concurrently replaced state fails closed.

Repair may restore only narrowly validated plugin-owned mode and usage hints. Disable
may restore only values captured by the matching managed state. Neither operation
reads or changes credentials, chats, sessions, or user-owned roles.

Historical schemas and the saved Executor fallback remain readable so existing users
can status, repair, or disable safely. The fallback is compatibility-only and retains
its narrow unknown-model/no-child/single-retry contract; it is not the Luna/Terra task
classifier. See [the fallback threat model](docs/executor-fallback-threat-model.md).

## Optional Claude subscription bridge

The bundled Fable/Opus Planner-or-Advisor bridge uses the official Claude Code CLI and
existing first-party login. It passes a minimal environment, disables tools and session
persistence, pins model and effort, validates structured output, and checks runtime
model metadata against an exact allowlist. Only one bundled Claude subscription seat
may be saved.

MCP requests do not expose caller identity, so the root-only caller boundary remains
instruction-enforced. No-tools execution, route authorization, model/effort pinning,
and runtime identity checks are mechanically enforced by the bridge.

## Removed external API-model surface

Version 0.10.0 removes Kimi, OpenRouter provider writes, credential helpers, paid Gate
0 probes, and generic External Model registry/recovery code. The plugin no longer
accepts or stores third-party API credentials and no longer creates API provider tables.
Claude first-party subscription routes are unaffected.

## Update and release boundaries

The explicit update control requires one enabled plugin from the canonical HTTPS Git
marketplace and delegates installation to Codex's native plugin manager. It does not
remove plugins, invent credentials, or rewrite routing state.

Security/state changes require malformed and negative-path tests, a threat model, and
a fresh final-tree review bound to the exact head SHA. Local checks are partial;
protected hosted checks remain authoritative.
