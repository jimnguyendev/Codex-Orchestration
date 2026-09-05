# Fable runtime metadata threat model

Version 0.11.0 adds `claude-fable-5-1` without inheriting the previously
qualified Fable 5 fallback/helper identities. Fresh setup pins Fable 5.1;
persisted `claude-fable-5` state remains valid under its original sealed runtime
policy. Both routes require first-party Claude Code authentication, including
Team accounts, and return no model-authored content until runtime identity is
authorized.

## Assets

- The sealed Fable 5.1, legacy Fable 5, and Opus 5 primary-model identities.
- The legacy-only reviewed Fable 5 helper identity and canonical model mapping.
- The guarantee that model-authored content is not returned before every
  runtime-reported identity is authorized.

## Threats

- An unreviewed model is hidden behind a plausible `canonicalModel` value.
- A Fable 5 fallback/helper allowlist is incorrectly reused for Fable 5.1.
- A non-first-party provider is reported for an otherwise allowed model key.
- A new string-valued metadata field bypasses the numeric usage validation.
- Malformed identity descriptors exploit Python type coercion or empty values.

## Mitigations

- Continue authorizing the complete set of reported model keys against the
  route-specific allowlist before interpreting model output.
- Keep Fable 5.1 primary-only until a live first-party call independently
  qualifies its exact fallback/helper set. Reject every legacy or unknown helper.
- Accept the old `claude-fable-5` route only as exact persisted compatibility;
  a fresh `--planner-fable` or `--advisor-fable` setup writes 5.1.
- Require Claude Code 2.1.255 or newer before writing a fresh Fable 5.1 route.
- Allow `canonicalModel` only through an explicit reported-model-to-canonical-
  model mapping; reject unknown or mismatched values.
- Require the exact provider value `firstParty` whenever `provider` is present.
- Treat only `canonicalModel` and `provider` as string descriptors. Every other
  usage field must remain a finite, non-negative number and booleans remain
  invalid.
- Keep the descriptors optional for compatibility with qualified older Claude
  Code output, but validate them strictly whenever present.

Regression tests cover Fable 5.1 primary-only metadata, the exact legacy
Fable/helper payload, Team authentication, the Claude Code version floor,
mismatched canonical models, third-party providers, unknown string fields, and
malformed descriptor types. Local preflight does not make a Fable model call;
live runtime qualification remains a release gate when access is available.
