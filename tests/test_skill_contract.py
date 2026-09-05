from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "plugins" / "codex-orchestration" / "skills" / "codex-orchestration"
SKILL = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
REFERENCE = (SKILL_ROOT / "references" / "providers-and-models.md").read_text(
    encoding="utf-8"
)
README = (ROOT / "README.md").read_text(encoding="utf-8")
README_VI = (ROOT / "README-vi.md").read_text(encoding="utf-8")


class SkillContractTests(unittest.TestCase):
    def test_root_remains_owner_and_trivial_work_avoids_handoff(self) -> None:
        self.assertIn("Keep the model selected for the current Codex task as root", SKILL)
        self.assertIn("Do not delegate trivial work", SKILL)
        self.assertIn("integration, verification", SKILL)
        self.assertIn("Worker reports are claims", SKILL)

    def test_default_lane_matrix_is_exact(self) -> None:
        self.assertIn("Luna Max — routine", SKILL)
        self.assertIn("Terra Max — hard or risky", SKILL)
        self.assertIn(
            "Routine: model=gpt-5.6-luna, reasoning_effort=max, fork_turns=none",
            SKILL,
        )
        self.assertIn(
            "Hard/risky: model=gpt-5.6-terra, reasoning_effort=max, fork_turns=none",
            SKILL,
        )
        self.assertIn("When uncertain, use Terra", SKILL)
        self.assertNotIn("reasoning_effort=xhigh", SKILL)

    def test_astra_keeps_hard_work_at_the_frontier_root_and_fails_closed(self) -> None:
        for surface in (SKILL, REFERENCE, README, README_VI):
            self.assertIn("gpt-6-astra", surface)
        self.assertIn("GPT-6 Astra root", SKILL)
        self.assertIn("catalog", SKILL)
        self.assertIn("do not downgrade", SKILL)

    def test_handoff_is_bounded_and_does_not_copy_history(self) -> None:
        for heading in (
            "OBJECTIVE",
            "OWNERSHIP",
            "CONTRACTS",
            "DONE WHEN",
            "VERIFY AND RETURN",
        ):
            self.assertIn(heading, SKILL)
        self.assertIn("under 1,200 words", SKILL)
        self.assertIn("Do not\npaste the conversation", SKILL)
        self.assertIn("one bounded packet", REFERENCE)

    def test_prewalk_claim_is_truthful(self) -> None:
        self.assertIn("is not Elves-style prewalk", SKILL)
        self.assertIn("A new Codex child is a cold handoff", SKILL)
        self.assertIn("do not claim KV-cache or same-session continuity", SKILL)
        self.assertIn("True prewalk requires the host", REFERENCE)

    def test_luna_escalation_is_bounded_and_not_an_automatic_fallback(self) -> None:
        self.assertIn("may make one Terra attempt", SKILL)
        self.assertIn("Do not send an unchanged prompt", SKILL)
        self.assertIn("compatibility-only", SKILL)
        self.assertIn("must never be used to classify hard work", SKILL)

    def test_luna_has_warm_root_progress_and_takeover_guards(self) -> None:
        self.assertIn("Apply a warm-root gate", SKILL)
        self.assertIn("File count is\nadvisory, never a hard eligibility limit", SKILL)
        self.assertIn("touches more than three files", SKILL)
        self.assertIn("Route by contract, state boundaries", SKILL)
        self.assertIn("database schema, migration, seed, API wiring, and tests", SKILL)
        self.assertIn("at most\nthree batched discovery tool calls", SKILL)
        self.assertIn("Within 120 seconds", SKILL)
        self.assertIn("allow at most 60 more seconds", SKILL)
        self.assertIn("inspect the worker-owned diff", SKILL)
        self.assertIn("wait for the\nchild to reach a terminal state", SKILL)
        self.assertIn("must not edit the same paths", SKILL)
        self.assertIn("not host-enforced time or token limits", SKILL)

    def test_reviews_and_planning_are_not_automatic(self) -> None:
        self.assertIn("not automatically create Planner, Advisor, Designer", SKILL)
        self.assertIn("final-review spawn to every task", SKILL)
        self.assertIn("Planner and Advisor are opt-in", SKILL)
        self.assertIn("Configuration alone authorizes zero calls", SKILL)
        self.assertIn("at most one Planner-or-Advisor model call total per task", SKILL)
        self.assertIn("reserve that call until implementation and checks finish", SKILL)
        self.assertIn("asks the user before any model re-review", SKILL)
        self.assertIn("Only an explicit current-task instruction may enlarge", SKILL)
        self.assertNotIn("at most three owned files", SKILL)

    def test_kimi_and_generic_external_lifecycle_are_removed(self) -> None:
        self.assertIn("Kimi, OpenRouter", SKILL)
        self.assertIn("are not part of this plugin", SKILL)
        self.assertFalse((SKILL_ROOT / "providers" / "openrouter.json").exists())
        self.assertFalse((SKILL_ROOT / "references" / "external-models.md").exists())
        for name in (
            "external_auth_helper.py",
            "external_cli_trust.py",
            "external_configurator.py",
            "external_credentials.py",
            "external_readiness.py",
            "external_registry.py",
        ):
            self.assertFalse((SKILL_ROOT / "scripts" / name).exists(), name)

    def test_fable_and_opus_remain_explicit_optional_routes(self) -> None:
        self.assertIn("Claude Fable 5.1 and Claude Opus 5 remain", SKILL)
        self.assertIn("They are not implementation lanes", SKILL)
        self.assertIn("claude-fable-5-1", REFERENCE)
        self.assertIn("claude-fable-5", REFERENCE)
        self.assertIn("claude-opus-5", REFERENCE)
        self.assertIn("Team", REFERENCE)
        self.assertIn("Claude Code 2.1.255 or newer", REFERENCE)
        self.assertTrue((SKILL_ROOT / "scripts" / "fable_advisor_mcp.py").is_file())
        self.assertTrue((SKILL_ROOT / "scripts" / "external_subscription.py").is_file())

    def test_persistent_setup_pins_both_lanes(self) -> None:
        self.assertIn("--executor-model gpt-5.6-luna", SKILL)
        self.assertIn("--executor-effort max", SKILL)
        self.assertIn("stores the Luna routine route", SKILL)
        self.assertIn("pins Terra Max for hard/risky work", SKILL)
        self.assertIn("Version 0.11 persistent setup", SKILL)
        self.assertIn("legacy workflow active", SKILL)
        self.assertIn("config/read", SKILL)
        self.assertIn("config/batchWrite", SKILL)

    def test_route_reporting_is_evidence_based(self) -> None:
        self.assertIn("route accepted", SKILL)
        self.assertIn("used and confirmed", SKILL)
        self.assertIn("Child prose is not routing evidence", SKILL)
        self.assertIn("Never silently substitute", SKILL)

    def test_goal_permissions_and_custom_roles_remain_bounded(self) -> None:
        self.assertIn("Do not create or change\nGoal state", SKILL)
        self.assertIn("never weakens approvals, permissions, sandboxing", SKILL)
        self.assertIn("Create custom roles only when explicitly requested", SKILL)
        self.assertIn("Never\noverwrite an unmanaged file", SKILL)

    def test_cost_language_has_no_stale_fixed_percentage(self) -> None:
        self.assertIn("Do not promise a fixed saving", SKILL)
        self.assertIn("verify current prices", SKILL)
        self.assertNotIn("about 64% fewer credits", SKILL)
        self.assertNotIn("published Luna rate of 20%", SKILL)
        self.assertIn("cached input, uncached input", SKILL)
        self.assertIn("first-artifact latency", SKILL)

    def test_user_docs_match_default_contract(self) -> None:
        for surface in (README, README_VI):
            self.assertIn("GPT-5.6 Luna Max", surface)
            self.assertIn("GPT-5.6 Terra Max", surface)
            self.assertIn("0.10.0", surface)
            self.assertIn("$codex-orchestration:codex-orchestration", surface)
        self.assertIn("không phải same-session prewalk", README_VI)


if __name__ == "__main__":
    unittest.main()
