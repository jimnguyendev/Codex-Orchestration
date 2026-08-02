from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "review_attestation.py"
SPEC = importlib.util.spec_from_file_location("review_attestation", SCRIPT)
assert SPEC and SPEC.loader
ATTESTATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ATTESTATION)
HEAD = "a" * 40
BASE = "b" * 40


def body(**updates: object) -> str:
    value: dict[str, object] = {
        "schema": 1,
        "risk_tier": "security-state",
        "repository": "jimnguyendev/Codex-Orchestration",
        "base_branch": "main",
        "reviewed_head_sha": HEAD,
        "reviewer_identity": "Independent Reviewer",
        "reviewer_route": "terra-max-fresh-context",
        "threat_model": {
            "assets": ["Exact reviewed commits and protected repository state"],
            "threats": ["Untrusted pull request metadata could bypass review gates"],
            "mitigations": ["Strict schema and immutable SHA validation fail closed"],
        },
        "negative_test_evidence": [
            {"category": "negative", "evidence": "test rejects a stale reviewed head SHA"},
            {"category": "malformed", "evidence": "test rejects malformed and duplicate JSON blocks"},
        ],
        "findings_disposition": "all material findings resolved",
    }
    value.update(updates)
    return (
        "summary\n"
        + ATTESTATION.START_MARKER
        + "\n"
        + json.dumps(value)
        + "\n"
        + ATTESTATION.END_MARKER
    )


def event(pr_body: str, *, head: str = HEAD) -> dict[str, object]:
    return {
        "repository": {"full_name": "jimnguyendev/Codex-Orchestration"},
        "pull_request": {
            "body": pr_body,
            "draft": True,
            "head": {"sha": head},
            "base": {"ref": "main", "sha": BASE},
        },
    }


class ReviewAttestationTests(unittest.TestCase):
    def test_valid_security_attestation_is_bound_to_head(self) -> None:
        tier = ATTESTATION.validate_pull_request_event(
            event(body()),
            expected_base=BASE,
            expected_head=HEAD,
            changed_paths=["scripts/preflight.py"],
        )
        self.assertEqual(tier, "security-state")

    def test_only_schema_one_is_accepted_after_external_probe_removal(self) -> None:
        for schema in (0, 2, "1"):
            with self.subTest(schema=schema), self.assertRaisesRegex(
                ATTESTATION.AttestationError, "schema"
            ):
                ATTESTATION.parse_attestation(body(schema=schema))

        extra = json.loads(
            body().split(ATTESTATION.START_MARKER, 1)[1].split(
                ATTESTATION.END_MARKER, 1
            )[0]
        )
        extra["runtime_probe"] = {"status": "passed"}
        malformed = (
            ATTESTATION.START_MARKER
            + json.dumps(extra)
            + ATTESTATION.END_MARKER
        )
        with self.assertRaisesRegex(ATTESTATION.AttestationError, "fields"):
            ATTESTATION.parse_attestation(malformed)

    def test_docs_tier_allows_explicit_not_required_review(self) -> None:
        docs = body(
            risk_tier="docs",
            reviewer_identity="not-required",
            reviewer_route="not-required",
            threat_model="not-required",
            negative_test_evidence=[],
            findings_disposition="not-required",
        )
        tier = ATTESTATION.validate_pull_request_event(
            event(docs),
            expected_base=BASE,
            expected_head=HEAD,
            changed_paths=["README.md"],
        )
        self.assertEqual(tier, "docs")

    def test_behavior_and_security_reject_placeholders(self) -> None:
        for field in ("reviewer_identity", "reviewer_route", "findings_disposition"):
            with self.subTest(field=field), self.assertRaisesRegex(
                ATTESTATION.AttestationError, "placeholder"
            ):
                ATTESTATION.validate_pull_request_event(
                    event(body(**{field: "not-required"})),
                    expected_base=BASE,
                    expected_head=HEAD,
                    changed_paths=["scripts/preflight.py"],
                )

    def test_security_requires_negative_malformed_and_threat_model(self) -> None:
        for evidence in (
            [{"category": "negative", "evidence": "negative path was rejected"}],
            [{"category": "malformed", "evidence": "malformed path was rejected"}],
            [],
        ):
            with self.subTest(evidence=evidence), self.assertRaises(
                ATTESTATION.AttestationError
            ):
                ATTESTATION.validate_pull_request_event(
                    event(body(negative_test_evidence=evidence)),
                    expected_base=BASE,
                    expected_head=HEAD,
                    changed_paths=["scripts/preflight.py"],
                )
        with self.assertRaisesRegex(ATTESTATION.AttestationError, "threat_model"):
            ATTESTATION.validate_pull_request_event(
                event(body(threat_model="not-required")),
                expected_base=BASE,
                expected_head=HEAD,
                changed_paths=["scripts/preflight.py"],
            )

    def test_repository_base_head_and_tier_are_exact(self) -> None:
        cases = (
            (event(body(repository="other/repo")), "repository"),
            (event(body(base_branch="other")), "base branch"),
            (event(body(reviewed_head_sha="c" * 40)), "reviewed SHA"),
            (event(body(risk_tier="behavior")), "risk tier"),
            (event(body(), head="c" * 40), "head SHA"),
        )
        for value, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                ATTESTATION.AttestationError, message
            ):
                ATTESTATION.validate_pull_request_event(
                    value,
                    expected_base=BASE,
                    expected_head=HEAD,
                    changed_paths=["scripts/preflight.py"],
                )

    def test_duplicate_or_missing_markers_fail_closed(self) -> None:
        duplicate = body() + "\n" + body()
        for value in ("{}", duplicate, ATTESTATION.START_MARKER + "{}"):
            with self.subTest(value=value[:20]), self.assertRaises(
                ATTESTATION.AttestationError
            ):
                ATTESTATION.parse_attestation(value)

    def test_non_pull_request_event_needs_no_attestation(self) -> None:
        self.assertIsNone(
            ATTESTATION.validate_pull_request_event(
                {"repository": {"full_name": "other/repo"}},
                expected_base=BASE,
                expected_head=HEAD,
                changed_paths=["scripts/preflight.py"],
            )
        )


if __name__ == "__main__":
    unittest.main()
