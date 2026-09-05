from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import unittest
from unittest import mock

from scripts import preflight


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-orchestration"
SKILL_ROOT = PLUGIN / "skills" / "codex-orchestration"


class PackagingTests(unittest.TestCase):
    def test_pull_request_attestation_template_is_strict_json(self) -> None:
        template = (ROOT / ".github" / "pull_request_template.md").read_text(
            encoding="utf-8"
        )
        start = "<!-- codex-review-attestation:start -->"
        end = "<!-- codex-review-attestation:end -->"
        self.assertEqual(template.count(start), 1)
        self.assertEqual(template.count(end), 1)
        attestation = json.loads(template.split(start, 1)[1].split(end, 1)[0])
        self.assertEqual(attestation["schema"], 1)
        self.assertEqual(attestation["repository"], "jimnguyendev/Codex-Orchestration")
        self.assertRegex(attestation["reviewed_head_sha"], r"^[0-9a-f]{40}$")
        self.assertIsInstance(attestation["negative_test_evidence"], list)

    def test_versioned_hooks_use_preflight_source_of_truth(self) -> None:
        expected = {
            ROOT / ".githooks" / "pre-commit": "#!/bin/sh\nexec python3 scripts/preflight.py quick\n",
            ROOT / ".githooks" / "pre-push": "#!/bin/sh\nexec python3 scripts/preflight.py full\n",
        }
        for hook, content in expected.items():
            self.assertEqual(hook.read_text(encoding="utf-8"), content)
            index = subprocess.run(
                ["git", "ls-files", "--stage", hook.relative_to(ROOT).as_posix()],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(index.returncode, 0, index.stderr)
            self.assertTrue(index.stdout.startswith("100755 "), index.stdout)

    def test_ci_uses_strict_targets_and_pinned_actions(self) -> None:
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        codeql = (ROOT / ".github" / "workflows" / "codeql.yml").read_text(
            encoding="utf-8"
        )
        expected_targets = {
            "quality": "quality",
            "test": "test",
            "plugin-lifecycle": "lifecycle",
            "legacy-client-guard": "legacy",
            "portability": "portability",
        }
        for job, target in expected_targets.items():
            match = re.search(
                rf"(?ms)^  {re.escape(job)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:|\Z)",
                ci,
            )
            self.assertIsNotNone(match, job)
            self.assertEqual(
                match.group(1).count(f"scripts/preflight.py {target} --ci"), 1, job
            )
        for workflow in (ci, codeql):
            self.assertIn("concurrency:", workflow)
            self.assertIn("github.event.pull_request.number || github.ref", workflow)
        self.assertIn('python-version: ["3.11", "3.13"]', ci)
        self.assertIn("os: [macos-latest, windows-latest]", ci)
        self.assertIn("@openai/codex@0.144.1", ci)
        self.assertIn("@openai/codex@0.142.5", ci)
        self.assertEqual(codeql.count("github/codeql-action/analyze@"), 1)

    def test_portability_runs_routing_and_subscription_regressions(self) -> None:
        calls: list[tuple[str, tuple[str, ...], int]] = []

        def record(
            root: Path,
            name: str,
            modules: list[str] | None = None,
            *,
            timeout: int = 600,
            env: dict[str, str] | None = None,
        ) -> preflight.CheckResult:
            del root, env
            calls.append((name, tuple(modules or ()), timeout))
            return preflight.CheckResult(name, "PASS")

        with (
            mock.patch.object(
                preflight,
                "compile_check",
                return_value=preflight.CheckResult("compile", "PASS"),
            ),
            mock.patch.object(preflight, "unittest_check", side_effect=record),
        ):
            results = preflight.ci_checks(
                "portability", ROOT, base_sha=None, head_sha=None
            )
        observed = {name: modules for name, modules, _ in calls}
        self.assertEqual(
            observed["portability-native-routing"], ("tests.test_native_routing",)
        )
        self.assertEqual(
            observed["portability-routing-state"], ("tests.test_routing_state",)
        )
        self.assertEqual(
            observed["portability-fable-advisor-mcp"],
            ("tests.test_fable_advisor_mcp",),
        )
        self.assertEqual(
            observed["portability-test-external-providers"],
            ("tests.test_external_providers",),
        )
        self.assertEqual(
            observed["portability-test-external-subscription"],
            ("tests.test_external_subscription",),
        )
        self.assertTrue(all(result.status == "PASS" for result in results))

    def test_manifest_marketplace_and_release_identity_are_aligned(self) -> None:
        manifest = json.loads(
            (PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        marketplace = json.loads(
            (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(manifest["name"], "codex-orchestration")
        self.assertEqual(manifest["version"], "0.11.0")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertEqual(
            manifest["repository"],
            "https://github.com/jimnguyendev/Codex-Orchestration",
        )
        self.assertEqual(manifest["author"]["name"], "CJ Zafir")
        self.assertEqual(marketplace["plugins"][0]["source"]["path"], "./plugins/codex-orchestration")
        self.assertIn("## 0.11.0 — Unreleased", changelog)

    def test_runtime_payload_is_compact_and_kimi_free(self) -> None:
        scripts = SKILL_ROOT / "scripts"
        providers = SKILL_ROOT / "providers"
        required = {
            "configure_native_routing.py",
            "configure_orchestration.py",
            "routing_state.py",
            "inspect_models.py",
            "fable_advisor_mcp.py",
            "external_providers.py",
            "external_subscription.py",
        }
        self.assertTrue(required.issubset({path.name for path in scripts.glob("*.py")}))
        self.assertEqual(
            {path.name for path in providers.glob("*.json")},
            {"claude-fable.json", "claude-opus.json"},
        )
        removed = {
            "external_auth_helper.py",
            "external_cli_trust.py",
            "external_configurator.py",
            "external_credentials.py",
            "external_readiness.py",
            "external_registry.py",
        }
        self.assertTrue(removed.isdisjoint({path.name for path in scripts.glob("*.py")}))
        self.assertFalse((SKILL_ROOT / "references" / "external-models.md").exists())
        skill_lines = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8").splitlines()
        self.assertLessEqual(len(skill_lines), 290)

    def test_fable_mcp_is_packaged_and_disabled_until_selected(self) -> None:
        mcp = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))
        servers = mcp["mcpServers"]
        self.assertEqual(
            set(servers),
            {"fable-advisor-python3", "fable-advisor-python", "fable-advisor-py"},
        )
        for server in servers.values():
            self.assertFalse(server["enabled"])
            self.assertIn("fable_advisor_mcp.py", server["args"][-1])

    def test_invocation_metadata_and_starter_prompts_are_consistent(self) -> None:
        metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        manifest = json.loads(
            (PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        invocation = "$codex-orchestration:codex-orchestration"
        for surface in (metadata, skill, readme, "\n".join(manifest["interface"]["defaultPrompt"])):
            self.assertIn(invocation, surface)
        self.assertIn("allow_implicit_invocation: true", metadata)
        prompts = manifest["interface"]["defaultPrompt"]
        self.assertGreaterEqual(len(prompts), 1)
        self.assertLessEqual(len(prompts), 3)
        for prompt in prompts:
            self.assertLessEqual(len(prompt), 128)
        self.assertIn("GPT-5.6 Luna Max", readme)
        self.assertIn("GPT-5.6 Terra Max", readme)

    def test_dual_version_lifecycle_uses_current_payload_version(self) -> None:
        smoke = (ROOT / "tests" / "plugin_lifecycle_smoke.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('OLD_VERSION = "0.5.0"', smoke)
        self.assertIn('NEW_VERSION = "0.11.0"', smoke)
        self.assertIn("configure_native_routing.py", smoke)
        self.assertIn("fable_advisor_mcp.py", smoke)

    def test_threat_models_bind_current_payload_version(self) -> None:
        version = json.loads(
            (PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )["version"]
        routing = (ROOT / "docs" / "routing-simplification-threat-model.md").read_text(
            encoding="utf-8"
        )
        fallback = (ROOT / "docs" / "executor-fallback-threat-model.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"release hiện tại là {version}", routing)
        self.assertIn(f"upgrade lên package {version}", routing)
        self.assertIn(f"phải cùng version {version}", fallback)
        self.assertIn("Từ phiên bản 0.10.0", fallback)

    def test_readme_leads_with_product_and_routing_before_install(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertLess(readme.index("## How routing works"), readme.index("## Install"))
        self.assertIn("Kimi K3, OpenRouter setup", readme)
        self.assertIn("does not promise a fixed percentage saving", readme)


if __name__ == "__main__":
    unittest.main()
