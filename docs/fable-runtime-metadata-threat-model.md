# Fable runtime metadata threat model

Version 0.10.1 accepts the identity descriptors that Claude Code now emits in
each `modelUsage` entry. This change remains fail-closed: it does not trust
arbitrary strings merely because they arrived in first-party CLI output.

## Assets

- The sealed Fable and Opus primary-model identities.
- The reviewed Fable helper identity and its canonical model mapping.
- The guarantee that model-authored content is not returned before every
  runtime-reported identity is authorized.

## Threats

- An unreviewed model is hidden behind a plausible `canonicalModel` value.
- A non-first-party provider is reported for an otherwise allowed model key.
- A new string-valued metadata field bypasses the numeric usage validation.
- Malformed identity descriptors exploit Python type coercion or empty values.

## Mitigations

- Continue authorizing the complete set of reported model keys against the
  route-specific allowlist before interpreting model output.
- Allow `canonicalModel` only through an explicit reported-model-to-canonical-
  model mapping; reject unknown or mismatched values.
- Require the exact provider value `firstParty` whenever `provider` is present.
- Treat only `canonicalModel` and `provider` as string descriptors. Every other
  usage field must remain a finite, non-negative number and booleans remain
  invalid.
- Keep the descriptors optional for compatibility with qualified older Claude
  Code output, but validate them strictly whenever present.

Regression tests cover the exact current Fable/helper payload plus mismatched
canonical models, third-party providers, unknown string fields, and malformed
descriptor types.
