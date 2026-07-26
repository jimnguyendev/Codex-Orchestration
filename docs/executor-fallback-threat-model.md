# Saved Executor fallback threat model (v1)

## Scope and asset

Schema 5 permits an optional saved direct-model Executor fallback. The protected
asset is the root's exact delegated request: its intended model/effort, all other
spawn fields, one-execution semantics, and an honest record of whether fallback was
used. This is model-visible routing policy. It does not make the Codex engine
schedule, load, or successfully call a model.

| Threat | Mitigation and negative test |
| --- | --- |
| Silent downgrade | A fallback must be an opt-in, different, direct model; it is consumed before one retry. A current-task Executor override and `no subagents` suppress it. Test that no fallback occurs without saved state, after a first retry, or for task-local Executor work. |
| Tampered state | State schema/policy 5, exact top-level shape, route type, different model, and marker validation fail closed. Both managed hints must contain exactly one canonical JSON binding for every saved route, including a null or direct-model fallback. Test malformed schema values, custom-agent fallback, equal model, unknown fields, mismatched policy version, and a valid-shape route-only edit. |
| Error spoofing | Retry only for the immediate direct `agents.spawn_agent` result with no child/agent provenance and the exact normalized `Unknown model <primary>. Available models: <list>` shape containing the exact saved fallback. Test substring, mixed, changed, prompt/log-derived, and ambiguous errors. |
| Provenance confusion | Presence of a child or agent ID makes the result ineligible. Test that post-child output, child task errors, and any later result cannot trigger a retry. |
| Double execution | Consume the single eligibility before invoking fallback, preserve every request field except `model` and `reasoning_effort`, then stop after the retry. Test that retry count cannot exceed one and all preserved fields are byte-for-byte equivalent. |
| Version skew | Package, manifest, lifecycle fixture, schema/policy validator, and public docs release as 0.9.0 together; legacy schemas remain constrained to their historic shapes. Test packaging version alignment and reject unrecognized state schemas. |
| CAS race | Native setup/disable pair App Server version checks with a byte-digest state compare-and-swap under an installer lock. The digest observed before the config write must still match immediately before state replacement or removal; otherwise the newer valid state is preserved and the config change is rolled back. Test stale config versions plus concurrent setup and disable state replacements. |

Permission, authentication, provider, rate-limit, timeout, cancellation, and task
errors are negative cases, not fallback signals. Their tests require no retry and a
reported failure. Residual limitation: a valid policy can only constrain the model's
visible instructions; it cannot prove the current task's callable child schema,
engine scheduler behavior, or live provider capacity. Exact live tool evidence is
still required before reporting route use as accepted or confirmed.
