from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins" / "codex-orchestration" / "skills" / "codex-orchestration" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import external_providers as PROVIDERS  # noqa: E402


class SubscriptionProviderTests(unittest.TestCase):
    def test_only_sealed_claude_templates_are_bundled(self) -> None:
        provider_dir = SCRIPTS.parent / "providers"
        self.assertEqual(
            {path.name for path in provider_dir.glob("*.json")},
            {"claude-fable.json", "claude-opus.json"},
        )
        fable = PROVIDERS.load_provider("claude-fable")
        opus = PROVIDERS.load_provider("claude-opus")
        for provider in (fable, opus):
            self.assertEqual(provider["lane"], "subscription")
            self.assertEqual(provider["auth"], "first_party_cli")
            self.assertEqual(provider["runtime_identity"], "cli_metadata")
            self.assertEqual(
                provider["subscription_adapter"]["module"],
                "fable_advisor_mcp",
            )
        self.assertEqual(
            set(fable["models"]),
            {"claude-fable-5", "claude-fable-5-1"},
        )
        self.assertEqual(fable["version"], 2)
        self.assertEqual(set(opus["models"]), {"claude-opus-5"})

    def test_subscription_effort_is_exact(self) -> None:
        provider = PROVIDERS.load_provider("claude-opus")
        model = "claude-opus-5"
        self.assertEqual(PROVIDERS.resolve_effort(provider, model, "auto"), "high")
        for effort in ("low", "medium", "high", "xhigh", "max"):
            self.assertEqual(PROVIDERS.resolve_effort(provider, model, effort), effort)
        with self.assertRaisesRegex(PROVIDERS.ProviderError, "unsupported"):
            PROVIDERS.resolve_effort(provider, model, "minimal")
        with self.assertRaisesRegex(PROVIDERS.ProviderError, "not in provider"):
            PROVIDERS.resolve_effort(provider, "claude-other", "high")

    def test_subscription_manifest_shape_fails_closed(self) -> None:
        provider = PROVIDERS.load_provider("claude-fable")
        for mutate in (
            lambda value: value.update({"lane": "native"}),
            lambda value: value.update({"auth": "secure_store"}),
            lambda value: value.update({"base_url": "https://example.invalid/v1"}),
            lambda value: value.update({"qualified": False}),
            lambda value: value["subscription_adapter"].update(
                {"module": "untrusted_bridge"}
            ),
            lambda value: value["models"]["claude-fable-5-1"].update(
                {"supported_efforts": ["high", "high"]}
            ),
        ):
            value = deepcopy(provider)
            mutate(value)
            with self.assertRaises(PROVIDERS.ProviderError):
                PROVIDERS.validate_provider(value, expected_id="claude-fable")

    def test_provider_loader_cannot_escape_bundled_directory(self) -> None:
        for provider_id in ("../outside", "/tmp/outside", "openrouter", "Bad.Provider", ""):
            with self.subTest(provider_id=provider_id):
                with self.assertRaises(PROVIDERS.ProviderError):
                    PROVIDERS.load_provider(provider_id)


if __name__ == "__main__":
    unittest.main()
