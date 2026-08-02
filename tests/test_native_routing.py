from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPO_ROOT
    / "plugins"
    / "codex-orchestration"
    / "skills"
    / "codex-orchestration"
    / "scripts"
    / "configure_native_routing.py"
)
sys.path.insert(0, str(SCRIPT.parent))

SPEC = importlib.util.spec_from_file_location("configure_native_routing", SCRIPT)
assert SPEC and SPEC.loader
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)


FAKE_CODEX = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

if "--version" in sys.argv:
    print("codex-cli 0.144.1")
    raise SystemExit(0)

if "features" in sys.argv and "list" in sys.argv:
    if (
        os.environ.get("FAKE_CODEX_INCOMPATIBLE") == "1"
        or Path(sys.argv[0]).name.startswith("old-")
    ):
        print("unknown multi_agent_mode_hint_text", file=sys.stderr)
        raise SystemExit(1)
    print("multi_agent_v2 under-development false")
    raise SystemExit(0)

if "app-server" not in sys.argv:
    raise SystemExit(2)

home = Path(os.environ["CODEX_HOME"]).resolve()
home.mkdir(parents=True, exist_ok=True)
store = home / ".fake-user-config.json"
effective_store = home / ".fake-effective-config.json"
version_file = home / ".fake-version"
mutate_after_write = home / ".fake-mutate-after-write"
mutate_namespace_after_write = home / ".fake-mutate-namespace-after-write"
mutate_feature_after_write = home / ".fake-mutate-feature-after-write"
mutate_state_after_write = home / ".fake-mutate-state-after-write"
concurrent_state_payload = home / ".fake-concurrent-routing-state.json"
ok_overridden = home / ".fake-ok-overridden"
overridden_returned = home / ".fake-overridden-returned"
fail_overridden_rollback = home / ".fake-fail-overridden-rollback"

def read_config():
    if store.exists():
        return json.loads(store.read_text(encoding="utf-8"))
    return {
        "features": {"multi_agent_v2": {"max_concurrent_threads_per_session": 5}},
        "unrelated": {"keep": True},
    }

def version():
    return int(version_file.read_text()) if version_file.exists() else 0

def set_path(root, path, value):
    parts = []
    current_part = []
    quoted = False
    escaped = False
    for character in path:
        if escaped:
            current_part.append(character)
            escaped = False
        elif character == "\\" and quoted:
            escaped = True
        elif character == '"':
            quoted = not quoted
        elif character == "." and not quoted:
            parts.append("".join(current_part))
            current_part = []
        else:
            current_part.append(character)
    parts.append("".join(current_part))
    current = root
    for part in parts[:-1]:
        if not isinstance(current.get(part), dict):
            current[part] = {}
        current = current[part]
    if value is None:
        current.pop(parts[-1], None)
    else:
        current[parts[-1]] = value

models = [
    {
        "id": "gpt-5.6-sol",
        "model": "gpt-5.6-sol",
        "supportedReasoningEfforts": [
            {"reasoningEffort": value, "description": value}
            for value in ("low", "medium", "high", "xhigh", "max", "ultra")
        ],
        "defaultReasoningEffort": "xhigh",
    },
    {
        "id": "gpt-5.6-terra",
        "model": "gpt-5.6-terra",
        "supportedReasoningEfforts": [
            {"reasoningEffort": value, "description": value}
            for value in ("low", "medium", "high", "xhigh", "max", "ultra")
        ],
        "defaultReasoningEffort": "high",
    },
    {
        "id": "gpt-5.6-luna",
        "model": "gpt-5.6-luna",
        "supportedReasoningEfforts": [
            {"reasoningEffort": value, "description": value}
            for value in ("low", "medium", "high", "xhigh", "max")
        ],
        "defaultReasoningEffort": "high",
    },
]

if (home / ".fake-remove-terra-model").exists():
    models = [item for item in models if item["model"] != "gpt-5.6-terra"]
if (home / ".fake-remove-terra-high-effort").exists():
    for item in models:
        if item["model"] == "gpt-5.6-terra":
            item["supportedReasoningEfforts"] = [
                option
                for option in item["supportedReasoningEfforts"]
                if option["reasoningEffort"] != "high"
            ]

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        continue
    if method == "initialize":
        result = {
            "userAgent": "fake-codex",
            "codexHome": str(home),
            "platformFamily": "unix",
            "platformOs": "test",
        }
    elif method == "config/read":
        config = read_config()
        effective = (
            json.loads(effective_store.read_text(encoding="utf-8"))
            if effective_store.exists()
            else config
        )
        result = {
            "config": effective,
            "origins": {},
            "layers": [
                {
                    "name": {
                        "type": "user",
                        "file": str(home / "config.toml"),
                        "profile": None,
                    },
                    "version": f"sha256:v{version()}",
                    "config": config,
                    "disabledReason": None,
                }
            ],
        }
    elif method == "model/list":
        result = {"data": models, "nextCursor": None}
    elif method == "config/batchWrite":
        params = message["params"]
        expected = params.get("expectedVersion")
        current_version = f"sha256:v{version()}"
        if fail_overridden_rollback.exists() and overridden_returned.exists():
            print(json.dumps({
                "id": request_id,
                "error": {
                    "code": -32600,
                    "message": "Forced rollback failure",
                    "data": {"config_write_error_code": "configVersionConflict"},
                },
            }), flush=True)
            continue
        if expected is not None and expected != current_version:
            print(json.dumps({
                "id": request_id,
                "error": {
                    "code": -32600,
                    "message": "Configuration was modified",
                    "data": {"config_write_error_code": "configVersionConflict"},
                },
            }), flush=True)
            continue
        config = read_config()
        for edit in params["edits"]:
            set_path(config, edit["keyPath"], edit.get("value"))
        if mutate_after_write.exists():
            set_path(
                config,
                "features.multi_agent_v2.usage_hint_text",
                "CONCURRENT USER EDIT",
            )
            mutate_after_write.unlink()
        if mutate_namespace_after_write.exists():
            set_path(
                config,
                "features.multi_agent_v2.tool_namespace",
                "collaboration",
            )
            mutate_namespace_after_write.unlink()
        if mutate_feature_after_write.exists():
            set_path(
                config,
                "features.multi_agent_v2.max_concurrent_threads_per_session",
                9,
            )
            mutate_feature_after_write.unlink()
        store.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
        if mutate_state_after_write.exists():
            state_path = home / ".codex-orchestration-routing.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["previous"]["usage"] = {
                "known": True,
                "present": True,
                "value": "CONCURRENT STATE EDIT",
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")
            mutate_state_after_write.unlink()
        if concurrent_state_payload.exists():
            (home / ".codex-orchestration-routing.json").write_bytes(
                concurrent_state_payload.read_bytes()
            )
            concurrent_state_payload.unlink()
        new_version = version() + 1
        version_file.write_text(str(new_version), encoding="utf-8")
        status = "ok"
        if ok_overridden.exists() and not overridden_returned.exists():
            overridden_returned.touch()
            status = "okOverridden"
        result = {
            "status": status,
            "version": f"sha256:v{new_version}",
            "filePath": str(home / "config.toml"),
            "overriddenMetadata": None,
        }
    else:
        print(json.dumps({
            "id": request_id,
            "error": {"code": -32601, "message": f"unknown method {method}"},
        }), flush=True)
        continue
    print(json.dumps({"id": request_id, "result": result}), flush=True)
'''


def _write_test_cli(
    directory: Path,
    name: str,
    source: str,
    *,
    windows: bool | None = None,
) -> tuple[Path, Path]:
    is_windows = os.name == "nt" if windows is None else windows
    source_path = directory / (f"{name}.py" if is_windows else name)
    source_path.write_text(textwrap.dedent(source), encoding="utf-8")
    source_path.chmod(0o755)
    if not is_windows:
        return source_path, source_path

    launcher = directory / f"{name}.cmd"
    launcher.write_text(
        (
            "@echo off\r\n"
            f'"{sys.executable}" "%~dp0{source_path.name}" %*\r\n'
        ),
        encoding="utf-8",
        newline="",
    )
    return source_path, launcher


class NativeRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        _, self.codex = _write_test_cli(self.root, "fake-codex", FAKE_CODEX)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.claude, _ = _write_test_cli(
            self.bin,
            "claude",
            """\
            #!/usr/bin/env python3
            import json
            import sys
            if sys.argv[1:] in (["auth", "status"], ["auth", "status", "--json"]):
                print(json.dumps({
                    "loggedIn": True,
                    "authMethod": "claude.ai",
                    "apiProvider": "firstParty",
                    "subscriptionType": "max",
                }))
                raise SystemExit(0)
            if sys.argv[1:] == ["--help"]:
                print(
                    "--print --model --effort <level> Effort level "
                    "(low, medium, high, xhigh, max) "
                    "--safe-mode --tools --permission-mode "
                    "--no-session-persistence --prompt-suggestions "
                    "--output-format --json-schema --system-prompt"
                )
                raise SystemExit(0)
            if sys.argv[1:] == ["--version"]:
                print("2.1.219 (Claude Code)")
                raise SystemExit(0)
            raise SystemExit(2)
            """,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_fake_cli_fixture_builds_windows_native_launchers(self) -> None:
        fixture_root = self.root / "windows-fixture"
        fixture_root.mkdir()
        source, launcher = _write_test_cli(
            fixture_root,
            "fake-tool",
            "# fake Python CLI\n",
            windows=True,
        )

        self.assertEqual(source.name, "fake-tool.py")
        self.assertEqual(launcher.name, "fake-tool.cmd")
        self.assertEqual(source.read_text(encoding="utf-8"), "# fake Python CLI\n")
        wrapper = launcher.read_text(encoding="utf-8")
        self.assertIn(f'"{sys.executable}"', wrapper)
        self.assertIn('"%~dp0fake-tool.py"', wrapper)
        self.assertIn("%*", wrapper)

    def test_app_server_close_requests_eof_before_forced_termination(self) -> None:
        server = object.__new__(NATIVE.AppServer)
        process = mock.Mock()
        process.poll.return_value = None
        process.stdin.closed = False
        process.wait.return_value = 0
        server._process = process
        server._stderr = mock.Mock()

        server.close()

        process.stdin.close.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=3)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        server._stderr.close.assert_called_once_with()

    def test_app_server_close_still_forces_a_process_that_ignores_eof(self) -> None:
        server = object.__new__(NATIVE.AppServer)
        process = mock.Mock()
        process.poll.return_value = None
        process.stdin.closed = False
        process.wait.side_effect = [
            subprocess.TimeoutExpired(["codex", "app-server"], 3),
            0,
        ]
        server._process = process
        server._stderr = mock.Mock()

        server.close()

        process.stdin.close.assert_called_once_with()
        self.assertEqual(
            process.wait.call_args_list,
            [mock.call(timeout=3), mock.call(timeout=3)],
        )
        process.terminate.assert_called_once_with()
        process.kill.assert_not_called()
        server._stderr.close.assert_called_once_with()

    def run_script(
        self,
        *arguments: str,
        check: bool = True,
        allow_incompatible: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        compatibility = ["--allow-incompatible-client"] if allow_incompatible else []
        env = os.environ.copy()
        env["PATH"] = f"{self.bin}{os.pathsep}{env.get('PATH', '')}"
        if os.name == "nt":
            env.setdefault("PATHEXT", ".COM;.EXE;.BAT;.CMD")
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--codex-bin",
                str(self.codex),
                "--codex-home",
                str(self.home),
                *compatibility,
                *arguments,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
            env=env,
        )
        if check and result.returncode != 0:
            self.fail(f"command failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def read_fake_config(self) -> dict[str, object]:
        return json.loads(
            (self.home / ".fake-user-config.json").read_text(encoding="utf-8")
        )

    def make_saved_policy_markerless(self) -> dict[str, object]:
        state_path = self.home / NATIVE.STATE_FILENAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        config_path = self.home / ".fake-user-config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        feature = config["features"]["multi_agent_v2"]
        for state_key, config_key in (
            ("mode", "multi_agent_mode_hint_text"),
            ("usage", "usage_hint_text"),
        ):
            legacy = state["managed"][state_key].replace(
                NATIVE.TWO_LANE_POLICY_MARKER + "\n", "", 1
            )
            state["managed"][state_key] = legacy
            feature[config_key] = legacy
        state_path.write_text(json.dumps(state), encoding="utf-8")
        config_path.write_text(json.dumps(config), encoding="utf-8")
        return state

    def write_personal_agent(self, name: str, *, managed: bool = False) -> Path:
        agents = self.home / "agents"
        agents.mkdir(exist_ok=True)
        path = agents / f"{name.replace('_', '-')}.toml"
        content = "\n".join(
                (
                    f'name = "{name}"',
                    'description = "Test custom route"',
                    'model = "gpt-5.6-luna"',
                    'model_reasoning_effort = "high"',
                    'developer_instructions = "Stay bounded and report to the root."',
                    "",
                )
            )
        if managed:
            content = f"{NATIVE.CUSTOM_AGENT_MANAGED_MARKER}\n{content}"
        path.write_text(content, encoding="utf-8")
        return path

    def test_policy_keeps_root_authority_and_pins_fork_none(self) -> None:
        executor = {"kind": "model", "model": "gpt-5.6-luna", "effort": "max"}
        planner = {"kind": "model", "model": "gpt-5.6-sol", "effort": "high"}
        advisor = {"kind": "model", "model": "gpt-5.6-terra", "effort": "high"}
        designer = {"kind": "model", "model": "gpt-5.6-luna", "effort": "high"}
        mode, usage = NATIVE.build_policy(executor, planner, advisor, designer)

        self.assertIn(NATIVE.TWO_LANE_POLICY_MARKER, mode)
        self.assertIn(NATIVE.TWO_LANE_POLICY_MARKER, usage)
        self.assertIn("root task model, you are the orchestrator", mode)
        self.assertIn("Codex still decides whether a plan or subagent helps", mode)
        self.assertIn("never spawn descendants", mode)
        self.assertIn("Explicit user instructions win", mode)
        self.assertIn("Persistent and task-local Planner and Advisor routes", mode)
        self.assertIn("Configuration alone never invokes Planner", mode)
        self.assertIn("Configuration alone never invokes Advisor", mode)
        self.assertIn("never creates a review loop", mode)
        self.assertIn("There is no automatic planning or review loop", mode)
        self.assertNotIn("before Executor work", mode)
        self.assertNotIn("at most eight total Advisor reviews", mode)
        self.assertIn("no Finalizer seat", mode)
        self.assertIn("configured Designer", mode)
        self.assertIn("design artifacts", mode)
        self.assertIn("or release Executor", mode)
        self.assertIn("cannot contact each other", mode)
        self.assertIn("cannot contact each other, Designer, or Executors", mode)
        self.assertIn("classify the task once", mode)
        self.assertIn("Use the configured Executor as the routine lane", mode)
        self.assertIn("gpt-5.6-terra", mode)
        self.assertIn("reasoning_effort = 'max'", mode)
        self.assertIn('model = "gpt-5.6-luna"', usage)
        self.assertIn('reasoning_effort = "max"', usage)
        self.assertIn('model = "gpt-5.6-terra"', usage)
        self.assertIn('reasoning_effort = "max"', usage)
        self.assertIn("For routine, bounded", usage)
        self.assertIn("For hard, ambiguous, or high-risk work", usage)
        self.assertIn('model = "gpt-5.6-sol"', usage)
        self.assertIn("For delegated design work", usage)
        self.assertGreaterEqual(usage.count('fork_turns = "none"'), 4)
        self.assertIn('Never use fork_turns = "all"', usage)
        self.assertIn("task-local Planner and Advisor must still be distinct", usage)
        self.assertIn("same direct model ID", usage)
        self.assertIn("more than one bundled Claude subscription seat", usage)
        self.assertIn("If you are a spawned child, do not call this tool", usage)
        self.assertNotIn("tool_namespace", mode + usage)
        self.assertNotIn("enabled = true", mode + usage)

    def test_configured_planner_and_advisor_require_explicit_task_authority(self) -> None:
        executor = {"kind": "model", "model": "gpt-5.6-luna", "effort": "max"}
        planner = {"kind": "model", "model": "gpt-5.6-sol", "effort": "high"}
        advisor = {"kind": "model", "model": "gpt-5.6-terra", "effort": "high"}
        mode, usage = NATIVE.build_policy(executor, planner, advisor)

        self.assertIn("current task explicitly requests planning", mode)
        self.assertIn("current task explicitly requests review", mode)
        self.assertIn("Only after an explicit current-task planning request", usage)
        self.assertIn("Only after an explicit current-task review request", usage)
        self.assertNotIn("fresh self-contained review call", mode)
        self.assertNotIn("PLAN_REVISE halts before Executor", mode)

    def test_policy_root_fallback_planner_without_advisor_and_fable_hints(self) -> None:
        executor = {"kind": "model", "model": "gpt-5.6-luna", "effort": "high"}
        advisor = {"kind": "model", "model": "gpt-5.6-terra", "effort": "high"}
        root_mode, root_usage = NATIVE.build_policy(executor, None, advisor)
        self.assertIn("root drafts and revises every plan", root_mode)
        self.assertIn("current task explicitly requests review", root_mode)
        self.assertIn("No Planner route is configured", root_usage)

        planner = {"kind": "model", "model": "gpt-5.6-sol", "effort": "xhigh"}
        planner_mode, planner_usage = NATIVE.build_policy(executor, planner, None)
        self.assertIn("Configuration alone never invokes Planner", planner_mode)
        self.assertIn("No advisor route is configured", planner_usage)
        self.assertNotIn("review_plan", planner_usage)

        fable_planner = {
            "kind": "fable",
            "model": NATIVE.FABLE_MODEL,
            "effort": "high",
            "server": "fable-advisor-python3",
        }
        _, fable_planner_usage = NATIVE.build_policy(
            executor, fable_planner, advisor
        )
        self.assertLess(
            fable_planner_usage.index("create_plan"),
            fable_planner_usage.index("revise_plan"),
        )
        self.assertIn("review packet", fable_planner_usage)

        fable_advisor = dict(fable_planner)
        _, fable_advisor_usage = NATIVE.build_policy(
            executor, planner, fable_advisor
        )
        self.assertIn("review_plan", fable_advisor_usage)
        self.assertIn('fork_turns = "none"', fable_advisor_usage)

    def test_executor_fallback_policy_is_exact_and_policy_instructed(self) -> None:
        executor = {"kind": "model", "model": "gpt-5.6-luna", "effort": "xhigh"}
        fallback = {"kind": "model", "model": "gpt-5.6-terra", "effort": "high"}
        mode, usage = NATIVE.build_policy(executor, None, None, None, fallback)

        combined = mode + usage
        self.assertIn("policy instruction, not scheduler-enforced", combined)
        self.assertIn("immediately preceding `agents.spawn_agent`", combined)
        self.assertIn("Unknown model gpt-5.6-luna. Available models: <list>", combined)
        self.assertIn("no child or agent ID", combined)
        self.assertIn("exact available ID", combined)
        self.assertIn("Preserve `message`, `task_name`, `agent_type`, `service_tier`", combined)
        self.assertIn("change only `model` and `reasoning_effort`", combined)
        self.assertIn("Consume that eligibility first", combined)
        self.assertIn("second failure stops", combined)
        self.assertIn("Permission, authentication, provider, rate-limit, timeout", combined)
        self.assertIn("task-local Executor route suppresses both", combined)
        self.assertIn("no-subagents instruction suppresses both", combined)

    def test_executor_fallback_set_preserve_clear_and_rejects_collisions(self) -> None:
        exclusive = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-fallback-model",
            "gpt-5.6-terra",
            "--clear-executor-fallback",
            check=False,
        )
        self.assertEqual(exclusive.returncode, 2)
        self.assertIn("not allowed with argument", exclusive.stderr)
        effort_without_model = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-fallback-effort",
            "high",
            check=False,
        )
        self.assertEqual(effort_without_model.returncode, 2)
        self.assertIn("requires --executor-fallback-model", effort_without_model.stderr)
        agent_with_fallback = self.run_script(
            "--executor-agent",
            "executor_agent",
            "--executor-fallback-model",
            "gpt-5.6-terra",
            check=False,
        )
        self.assertEqual(agent_with_fallback.returncode, 2)
        self.assertIn("requires a direct", agent_with_fallback.stderr)
        unlisted_fallback = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-fallback-model",
            "not-in-catalog",
            "--executor-fallback-effort",
            "high",
            "--confirm-unlisted-models",
            check=False,
        )
        self.assertEqual(unlisted_fallback.returncode, 2)
        self.assertIn("not in this App Server model catalog", unlisted_fallback.stderr)

        applied = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--executor-fallback-model",
            "gpt-5.6-terra",
            "--executor-fallback-effort",
            "high",
            "--apply",
        )
        self.assertIn("Executor fallback: gpt-5.6-terra@high", applied.stdout)
        state_path = self.home / NATIVE.STATE_FILENAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["schema"], 6)
        self.assertEqual(state["executor_fallback"]["model"], "gpt-5.6-terra")
        status = self.run_script("--status")
        self.assertIn(
            "Executor fallback: gpt-5.6-terra@high (user-authorized; callability unverified)",
            status.stdout,
        )

        self.run_script(
            "--executor-model", "gpt-5.6-luna", "--executor-effort", "max", "--apply"
        )
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8"))["executor_fallback"]["model"],
            "gpt-5.6-terra",
        )
        before_invalid = state_path.read_bytes()
        before_invalid_config = self.read_fake_config()
        wrong_effort = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "high",
            "--apply",
            check=False,
        )
        self.assertEqual(wrong_effort.returncode, 2)
        self.assertIn("requires the exact routine Executor", wrong_effort.stderr)
        self.assertEqual(state_path.read_bytes(), before_invalid)
        self.assertEqual(self.read_fake_config(), before_invalid_config)
        agent = self.run_script(
            "--executor-agent", "executor_agent", "--apply", check=False
        )
        self.assertEqual(agent.returncode, 2)
        self.assertIn("requires the exact routine Executor", agent.stderr)
        self.assertEqual(state_path.read_bytes(), before_invalid)
        self.assertEqual(self.read_fake_config(), before_invalid_config)
        unlisted_primary = self.run_script(
            "--executor-model",
            "not-in-catalog",
            "--executor-effort",
            "high",
            "--confirm-unlisted-models",
            "--apply",
            check=False,
        )
        self.assertEqual(unlisted_primary.returncode, 2)
        self.assertIn("requires the exact routine Executor", unlisted_primary.stderr)
        self.assertEqual(state_path.read_bytes(), before_invalid)
        self.assertEqual(self.read_fake_config(), before_invalid_config)

        cleared = self.run_script(
            "--executor-model", "gpt-5.6-luna", "--clear-executor-fallback", "--apply"
        )
        self.assertIn("Executor fallback: none", cleared.stdout)
        self.assertIsNone(
            json.loads(state_path.read_text(encoding="utf-8"))["executor_fallback"]
        )

    def test_preserved_fallback_must_remain_listed_with_its_saved_effort(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-fallback-model",
            "gpt-5.6-terra",
            "--executor-fallback-effort",
            "high",
            "--apply",
        )
        state_path = self.home / NATIVE.STATE_FILENAME
        state_before = state_path.read_bytes()
        config_before = self.read_fake_config()

        for marker, expected in (
            (".fake-remove-terra-model", "Saved executor fallback model"),
            (".fake-remove-terra-high-effort", "Saved executor fallback effort"),
        ):
            with self.subTest(marker=marker):
                (self.home / marker).touch()
                rejected = self.run_script(
                    "--executor-model",
                    "gpt-5.6-luna",
                    "--executor-effort",
                    "max",
                    "--apply",
                    check=False,
                )
                self.assertEqual(rejected.returncode, 2)
                self.assertIn(expected, rejected.stderr)
                self.assertEqual(state_path.read_bytes(), state_before)
                self.assertEqual(self.read_fake_config(), config_before)
                (self.home / marker).unlink()

    def test_planner_argument_validation(self) -> None:
        exclusive = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-model",
            "gpt-5.6-sol",
            "--planner-agent",
            "planner_agent",
            check=False,
        )
        self.assertEqual(exclusive.returncode, 2)
        self.assertIn("not allowed with argument", exclusive.stderr)

        effort = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-agent",
            "planner_agent",
            "--planner-effort",
            "high",
            check=False,
        )
        self.assertEqual(effort.returncode, 2)
        self.assertIn("custom planner agent owns its effort", effort.stderr)

        invalid = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-model",
            "bad model",
            check=False,
        )
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("Invalid planner model", invalid.stderr)

    def test_designer_argument_validation(self) -> None:
        external = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--designer-agent",
            "designer_agent",
            check=False,
        )
        self.assertEqual(external.returncode, 2)
        self.assertIn("unrecognized arguments: --designer-agent", external.stderr)

        invalid = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--designer-model",
            "bad model",
            check=False,
        )
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("Invalid designer model", invalid.stderr)

        for action in ("--status", "--disable", "--repair"):
            with self.subTest(action=action):
                result = self.run_script(
                    action,
                    "--designer-effort",
                    "high",
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("does not accept seat settings", result.stderr)

    def test_persistent_setup_requires_exact_luna_max_without_writes(self) -> None:
        cases = (
            ("wrong model", ("--executor-model", "gpt-5.6-sol", "--executor-effort", "max")),
            ("wrong effort", ("--executor-model", "gpt-5.6-luna", "--executor-effort", "high")),
            ("custom executor", ("--executor-agent", "custom_executor")),
        )
        for label, arguments in cases:
            with self.subTest(label=label):
                rejected = self.run_script(*arguments, "--apply", check=False)
                self.assertEqual(rejected.returncode, 2)
                self.assertIn("requires the exact routine Executor", rejected.stderr)
                self.assertFalse((self.home / ".fake-user-config.json").exists())
                self.assertFalse((self.home / NATIVE.STATE_FILENAME).exists())

        missing_codex = self.root / "must-not-start-for-wrong-executor"
        rejected_before_start = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--codex-bin",
                str(missing_codex),
                "--executor-model",
                "gpt-5.6-sol",
                "--executor-effort",
                "max",
                "--apply",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        self.assertEqual(rejected_before_start.returncode, 2)
        self.assertIn(
            "requires the exact routine Executor", rejected_before_start.stderr
        )
        self.assertNotIn("Codex binary does not exist", rejected_before_start.stderr)

    def test_reserved_claude_model_ids_require_their_sealed_cli_routes(self) -> None:
        missing_codex = self.root / "must-not-start-app-server"
        for option in (
            "--executor-model",
            "--planner-model",
            "--advisor-model",
            "--designer-model",
        ):
            for model in (NATIVE.FABLE_MODEL, NATIVE.OPUS_MODEL):
                arguments = [
                    sys.executable,
                    str(SCRIPT),
                    "--codex-bin",
                    str(missing_codex),
                ]
                if option != "--executor-model":
                    arguments.extend(("--executor-model", "gpt-5.6-luna"))
                arguments.extend((option, model))
                with self.subTest(option=option, model=model):
                    rejected = subprocess.run(
                        arguments,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=20,
                        check=False,
                    )
                    self.assertEqual(rejected.returncode, 2)
                    self.assertIn("reserved Claude model", rejected.stderr)
                    self.assertNotIn("Codex binary does not exist", rejected.stderr)
                    self.assertFalse(
                        (self.home / ".fake-user-config.json").exists()
                    )
                    self.assertFalse(
                        (self.home / NATIVE.STATE_FILENAME).exists()
                    )

        self.write_personal_agent("claude_opus_5")
        agent = self.run_script(
            "--executor-agent", "claude_opus_5", check=False
        )
        self.assertEqual(agent.returncode, 2)
        self.assertIn("requires the exact routine Executor", agent.stderr)

    def test_capability_probe_checks_the_complete_routing_surface(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="supported")
        with mock.patch.object(NATIVE.subprocess, "run", return_value=completed) as run:
            supported, _ = NATIVE.supports_native_policy(self.codex)
        self.assertTrue(supported)
        argv = run.call_args.args[0]
        self.assertIn(
            'features.multi_agent_v2.tool_namespace="agents"',
            argv,
        )
        self.assertIn(
            "features.multi_agent_v2.hide_spawn_agent_metadata=false",
            argv,
        )
        self.assertTrue(
            any("multi_agent_mode_hint_text" in value for value in argv)
        )
        self.assertTrue(any("usage_hint_text" in value for value in argv))

    def test_setup_status_and_disable_round_trip(self) -> None:
        preview = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
        )
        self.assertIn("Dry run only", preview.stdout)
        self.assertFalse((self.home / ".fake-user-config.json").exists())

        applied = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        self.assertIn("Native routing policy installed", applied.stdout)
        config = self.read_fake_config()
        feature = config["features"]["multi_agent_v2"]
        self.assertEqual(feature["max_concurrent_threads_per_session"], 5)
        self.assertFalse(feature["hide_spawn_agent_metadata"])
        self.assertEqual(feature["tool_namespace"], "agents")
        self.assertIn(NATIVE.MANAGED_MARKER, feature["usage_hint_text"])
        self.assertIn(NATIVE.TWO_LANE_POLICY_MARKER, feature["usage_hint_text"])
        self.assertIn('model = "gpt-5.6-luna", reasoning_effort = "max"', feature["usage_hint_text"])
        self.assertIn('model = "gpt-5.6-terra", reasoning_effort = "max"', feature["usage_hint_text"])
        self.assertIn("For hard, ambiguous, or high-risk work", feature["usage_hint_text"])
        self.assertEqual(config["unrelated"], {"keep": True})

        status = self.run_script("--status")
        self.assertIn("Native policy: installed and effective", status.stdout)
        self.assertIn("V2 activation: not inferred", status.stdout)
        self.assertIn("Executor: gpt-5.6-luna@max", status.stdout)
        self.assertIn("Designer: none", status.stdout)
        self.assertIn("Advisor: none", status.stdout)
        self.assertIn("V2 tool namespace: agents", status.stdout)
        self.assertIn("Routing validation: not performed", status.stdout)

        required = self.run_script("--status", "--require-effective")
        self.assertEqual(required.returncode, 0)

        disabled = self.run_script("--disable", "--apply")
        self.assertIn("Native routing disabled", disabled.stdout)
        feature = self.read_fake_config()["features"]["multi_agent_v2"]
        self.assertEqual(feature, {"max_concurrent_threads_per_session": 5})
        self.assertFalse((self.home / NATIVE.STATE_FILENAME).exists())

    def test_existing_schema_six_policy_without_two_lane_marker_fails_strict_status(
        self,
    ) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        self.make_saved_policy_markerless()

        status = self.run_script("--status", "--require-effective", check=False)
        self.assertEqual(status.returncode, 1)
        self.assertIn("legacy workflow active", status.stdout)
        self.assertIn("existing state remains valid", status.stdout)

        disabled = self.run_script("--disable", "--apply")
        self.assertIn("Native routing disabled", disabled.stdout)

    def test_marker_only_migration_preserves_fable_planner(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-fable",
            "--planner-effort",
            "high",
            "--apply",
        )
        legacy_state = self.make_saved_policy_markerless()

        migrated = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )

        self.assertIn("preserved existing sealed seat(s): planner", migrated.stdout)
        current = json.loads(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(current["planner"], legacy_state["planner"])
        self.assertIsNone(current["advisor"])
        self.assertIn(NATIVE.TWO_LANE_POLICY_MARKER, current["managed"]["mode"])

    def test_marker_only_migration_preserves_opus_advisor(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-opus",
            "--advisor-effort",
            "max",
            "--apply",
        )
        legacy_state = self.make_saved_policy_markerless()

        migrated = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )

        self.assertIn("preserved existing sealed seat(s): advisor", migrated.stdout)
        current = json.loads(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(current["advisor"], legacy_state["advisor"])
        self.assertIsNone(current["planner"])
        self.assertIn(NATIVE.TWO_LANE_POLICY_MARKER, current["managed"]["usage"])

    def test_markerless_hints_without_state_do_not_offer_repair_or_disable(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--apply",
        )
        self.make_saved_policy_markerless()
        (self.home / NATIVE.STATE_FILENAME).unlink()

        status = self.run_script("--status", "--require-effective", check=False)

        self.assertEqual(status.returncode, 1)
        self.assertIn("managed hints found without saved state", status.stdout)
        self.assertIn("repair and disable are unavailable", status.stdout)
        self.assertNotIn("existing state remains valid", status.stdout)
        repair = self.run_script("--repair", check=False)
        self.assertEqual(repair.returncode, 2)
        self.assertIn("requires valid saved plugin state", repair.stderr)
        config_before_disable = (
            self.home / ".fake-user-config.json"
        ).read_bytes()
        disable = self.run_script("--disable", "--apply", check=False)
        self.assertEqual(disable.returncode, 2)
        self.assertIn("saved restore state is missing", disable.stderr)
        self.assertEqual(
            (self.home / ".fake-user-config.json").read_bytes(),
            config_before_disable,
        )

    def test_direct_planner_designer_setup_status_and_require_effective(self) -> None:
        setup = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-model",
            "gpt-5.6-sol",
            "--planner-effort",
            "auto",
            "--advisor-model",
            "gpt-5.6-terra",
            "--advisor-effort",
            "high",
            "--designer-model",
            "gpt-5.6-luna",
            "--designer-effort",
            "medium",
            "--apply",
        )
        self.assertIn("Planner: gpt-5.6-sol@xhigh", setup.stdout)
        state = json.loads(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(state["schema"], 6)
        self.assertEqual(state["policy_version"], 6)
        self.assertEqual(state["planner"]["effort"], "xhigh")
        self.assertEqual(state["designer"]["effort"], "medium")

        status = self.run_script("--status", "--require-effective")
        self.assertIn("Planner: gpt-5.6-sol@xhigh", status.stdout)
        self.assertIn("Designer: gpt-5.6-luna@medium", status.stdout)
        self.assertEqual(status.returncode, 0)

    def test_legacy_state_schemas_upgrade_to_six_without_losing_restore(self) -> None:
        for legacy_schema in (1, 2, 3, 4, 5):
            with self.subTest(schema=legacy_schema):
                setup_arguments = ["--executor-model", "gpt-5.6-luna"]
                if legacy_schema == 2:
                    setup_arguments.append("--advisor-fable")
                self.run_script(*setup_arguments, "--apply")

                state_path = self.home / NATIVE.STATE_FILENAME
                legacy = json.loads(state_path.read_text(encoding="utf-8"))
                original_previous = legacy["previous"]
                legacy["schema"] = legacy_schema
                legacy["policy_version"] = legacy_schema
                if legacy_schema < 3:
                    legacy.pop("planner", None)
                if legacy_schema < 4:
                    legacy.pop("designer", None)
                if legacy_schema < 5:
                    legacy.pop("executor_fallback", None)
                legacy["managed"]["mode"] = (
                    f"{NATIVE.MANAGED_MARKER}\nlegacy schema {legacy_schema} mode"
                )
                legacy["managed"]["usage"] = (
                    f"{NATIVE.MANAGED_MARKER}\nlegacy schema {legacy_schema} usage"
                )
                if legacy_schema == 5:
                    binding = NATIVE.routing_state_binding(legacy)
                    legacy["managed"]["mode"] += f"\n{binding}"
                    legacy["managed"]["usage"] += f"\n{binding}"
                state_path.write_text(json.dumps(legacy), encoding="utf-8")

                config = self.read_fake_config()
                feature = config["features"]["multi_agent_v2"]
                feature["multi_agent_mode_hint_text"] = legacy["managed"]["mode"]
                feature["usage_hint_text"] = legacy["managed"]["usage"]
                (self.home / ".fake-user-config.json").write_text(
                    json.dumps(config), encoding="utf-8"
                )

                self.run_script(
                    "--executor-model",
                    "gpt-5.6-luna",
                    "--planner-model",
                    "gpt-5.6-sol",
                    "--designer-model",
                    "gpt-5.6-luna",
                    "--apply",
                )
                upgraded = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertEqual(upgraded["schema"], 6)
                self.assertEqual(upgraded["policy_version"], 6)
                self.assertEqual(upgraded["previous"], original_previous)
                self.assertEqual(upgraded["planner"]["model"], "gpt-5.6-sol")
                self.assertEqual(upgraded["designer"]["model"], "gpt-5.6-luna")
                if legacy_schema == 2:
                    self.assertIn("mcp", upgraded["managed"])

                self.run_script("--disable", "--apply")
                self.assertEqual(
                    self.read_fake_config()["features"]["multi_agent_v2"],
                    {"max_concurrent_threads_per_session": 5},
                )
                self.assertFalse(state_path.exists())

    def test_state_policy_version_must_match_schema(self) -> None:
        self.run_script("--executor-model", "gpt-5.6-luna", "--apply")
        state_path = self.home / NATIVE.STATE_FILENAME
        current = json.loads(state_path.read_text(encoding="utf-8"))

        for schema, wrong_policy in ((1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 1), (6, True)):
            with self.subTest(schema=schema, policy=wrong_policy):
                state = json.loads(json.dumps(current))
                state["schema"] = schema
                state["policy_version"] = wrong_policy
                if schema < 3:
                    state.pop("planner")
                if schema < 4:
                    state.pop("designer")
                if schema < 5:
                    state.pop("executor_fallback")
                state_path.write_text(json.dumps(state), encoding="utf-8")

                status = self.run_script("--status", check=False)
                self.assertEqual(status.returncode, 2)
                self.assertIn("Saved routing state is invalid", status.stderr)
                self.assertNotIn("policy_version", status.stderr)

    def test_schema_six_route_only_tamper_blocks_every_state_consumer(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-fallback-model",
            "gpt-5.6-terra",
            "--apply",
        )
        state_path = self.home / NATIVE.STATE_FILENAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["executor_fallback"]["effort"] = "xhigh"
        tampered = json.dumps(state).encode()
        config_before = self.read_fake_config()

        actions = (
            ("status", ("--status",)),
            ("setup", ("--executor-model", "gpt-5.6-luna", "--apply")),
            ("repair", ("--repair", "--apply")),
            ("disable", ("--disable", "--apply")),
            (
                "Fable setup",
                ("--executor-model", "gpt-5.6-luna", "--advisor-fable", "--apply"),
            ),
        )
        for label, arguments in actions:
            with self.subTest(action=label):
                state_path.write_bytes(tampered)
                rejected = self.run_script(*arguments, check=False)
                self.assertEqual(rejected.returncode, 2)
                self.assertIn("Saved routing state is invalid", rejected.stderr)
                self.assertEqual(state_path.read_bytes(), tampered)
                self.assertEqual(self.read_fake_config(), config_before)

    def test_legacy_state_schemas_reject_planner_key_even_when_null(self) -> None:
        self.run_script("--executor-model", "gpt-5.6-luna", "--apply")
        state_path = self.home / NATIVE.STATE_FILENAME
        current = json.loads(state_path.read_text(encoding="utf-8"))

        for schema in (1, 2):
            with self.subTest(schema=schema):
                state = json.loads(json.dumps(current))
                state["schema"] = schema
                state["policy_version"] = schema
                state["planner"] = None
                state_path.write_text(json.dumps(state), encoding="utf-8")

                status = self.run_script("--status", check=False)
                self.assertEqual(status.returncode, 2)
                self.assertIn("Saved routing state is invalid", status.stderr)

    def test_legacy_state_schemas_reject_designer_key_even_when_null(self) -> None:
        self.run_script("--executor-model", "gpt-5.6-luna", "--apply")
        state_path = self.home / NATIVE.STATE_FILENAME
        current = json.loads(state_path.read_text(encoding="utf-8"))

        for schema in (1, 2, 3):
            with self.subTest(schema=schema):
                state = json.loads(json.dumps(current))
                state["schema"] = schema
                state["policy_version"] = schema
                if schema < 3:
                    state.pop("planner")
                state["designer"] = None
                state_path.write_text(json.dumps(state), encoding="utf-8")

                status = self.run_script("--status", check=False)
                self.assertEqual(status.returncode, 2)
                self.assertIn("Saved routing state is invalid", status.stderr)

    def test_schema_one_rejects_fable_and_mcp_fields(self) -> None:
        self.run_script("--executor-model", "gpt-5.6-luna", "--apply")
        state_path = self.home / NATIVE.STATE_FILENAME
        current = json.loads(state_path.read_text(encoding="utf-8"))
        current["schema"] = 1
        current["policy_version"] = 1
        current.pop("planner")
        mutations = {
            "fable advisor": lambda state: state.__setitem__(
                "advisor",
                {
                    "kind": "fable",
                    "model": NATIVE.FABLE_MODEL,
                    "effort": "high",
                    "server": "fable-advisor-python3",
                },
            ),
            "managed mcp": lambda state: state["managed"].__setitem__("mcp", None),
            "previous mcp": lambda state: state["previous"].__setitem__("mcp", None),
        }

        for label, mutate in mutations.items():
            with self.subTest(field=label):
                state = json.loads(json.dumps(current))
                mutate(state)
                state_path.write_text(json.dumps(state), encoding="utf-8")

                status = self.run_script("--status", check=False)
                self.assertEqual(status.returncode, 2)
                self.assertIn("Saved routing state is invalid", status.stderr)

    def test_saved_managed_strings_require_exact_marker_line(self) -> None:
        self.run_script("--executor-model", "gpt-5.6-luna", "--apply")
        state_path = self.home / NATIVE.STATE_FILENAME
        current = json.loads(state_path.read_text(encoding="utf-8"))
        mutations = {
            "mode": "arbitrary managed mode",
            "usage": f"{NATIVE.MANAGED_MARKER}-forged suffix",
            "marker only": NATIVE.MANAGED_MARKER,
            "empty body": f"{NATIVE.MANAGED_MARKER}\n   ",
        }

        for label, unmarked in mutations.items():
            with self.subTest(field=label):
                state = json.loads(json.dumps(current))
                field = "usage" if label == "usage" else "mode"
                state["managed"][field] = unmarked
                state_path.write_text(json.dumps(state), encoding="utf-8")

                status = self.run_script("--status", check=False)
                self.assertEqual(status.returncode, 2)
                self.assertIn("Saved routing state is invalid", status.stderr)
                self.assertNotIn(unmarked, status.stderr)

    def test_unknown_state_schema_fails_closed(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--apply",
        )
        state_path = self.home / NATIVE.STATE_FILENAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["schema"] = 999
        state_path.write_text(json.dumps(state), encoding="utf-8")

        status = self.run_script("--status", check=False)
        self.assertEqual(status.returncode, 2)
        self.assertIn("Saved routing state is invalid", status.stderr)

    def test_invalid_saved_planner_route_fails_closed(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-model",
            "gpt-5.6-sol",
            "--apply",
        )
        state_path = self.home / NATIVE.STATE_FILENAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["planner"]["effort"] = "not valid"
        state_path.write_text(json.dumps(state), encoding="utf-8")

        status = self.run_script("--status", "--require-effective", check=False)
        self.assertEqual(status.returncode, 2)
        self.assertIn("Saved routing state is invalid", status.stderr)

    def test_existing_user_policy_requires_explicit_replace_and_is_restored(self) -> None:
        initial = {
            "features": {
                "multi_agent_v2": {
                    "hide_spawn_agent_metadata": True,
                    "tool_namespace": "custom_namespace",
                    "multi_agent_mode_hint_text": "MY MODE",
                    "usage_hint_text": "MY USAGE",
                }
            }
        }
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(initial), encoding="utf-8"
        )

        refused = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
            check=False,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("user-authored mode hint", refused.stderr)

        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--replace-existing-policy",
            "--apply",
        )
        self.run_script("--disable", "--apply")
        self.assertEqual(self.read_fake_config(), initial)

    def test_boolean_feature_shape_is_restored(self) -> None:
        initial = {"features": {"multi_agent_v2": True}, "keep": "yes"}
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(initial), encoding="utf-8"
        )
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        feature = self.read_fake_config()["features"]["multi_agent_v2"]
        self.assertTrue(feature["enabled"])
        self.assertEqual(feature["tool_namespace"], "agents")
        self.run_script("--disable", "--apply")
        self.assertEqual(self.read_fake_config(), initial)

    def test_boolean_feature_shape_survives_a_seat_update(self) -> None:
        initial = {"features": {"multi_agent_v2": False}, "keep": "yes"}
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(initial), encoding="utf-8"
        )
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        self.run_script("--disable", "--apply")
        self.assertEqual(self.read_fake_config(), initial)

    def test_fresh_setup_recovers_marker_without_state_before_disable(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        (self.home / NATIVE.STATE_FILENAME).unlink()
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        self.run_script("--disable", "--apply")
        feature = self.read_fake_config()["features"]["multi_agent_v2"]
        self.assertNotIn("multi_agent_mode_hint_text", feature)
        self.assertNotIn("usage_hint_text", feature)
        self.assertFalse(feature["hide_spawn_agent_metadata"])
        self.assertEqual(feature["tool_namespace"], "agents")

    def test_fresh_setup_recovers_partial_marker_before_disable(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        (self.home / NATIVE.STATE_FILENAME).unlink()
        config = self.read_fake_config()
        config["features"]["multi_agent_v2"].pop("usage_hint_text")
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        self.run_script("--disable", "--apply")
        feature = self.read_fake_config()["features"]["multi_agent_v2"]
        self.assertNotIn("multi_agent_mode_hint_text", feature)
        self.assertNotIn("usage_hint_text", feature)
        self.assertEqual(feature["tool_namespace"], "agents")

    def test_namespace_edit_after_setup_blocks_disable_and_is_preserved(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        config = self.read_fake_config()
        config["features"]["multi_agent_v2"]["tool_namespace"] = "collaboration"
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        status = self.run_script("--status")
        self.assertIn("managed fields conflict", status.stdout)
        self.assertIn("run --repair as a dry run", status.stdout)
        self.assertIn("Seats: suppressed", status.stdout)
        required = self.run_script(
            "--status", "--require-effective", check=False
        )
        self.assertEqual(required.returncode, 1)
        update = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
            check=False,
        )
        self.assertEqual(update.returncode, 2)
        self.assertIn("changed outside this plugin", update.stderr)
        disabled = self.run_script("--disable", "--apply", check=False)
        self.assertEqual(disabled.returncode, 2)
        self.assertIn("edited after setup", disabled.stderr)
        feature = self.read_fake_config()["features"]["multi_agent_v2"]
        self.assertEqual(feature["tool_namespace"], "collaboration")
        self.assertTrue((self.home / NATIVE.STATE_FILENAME).exists())

    def test_repair_restores_only_saved_managed_hints_and_keeps_state(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--advisor-fable",
            "--apply",
        )
        state_path = self.home / NATIVE.STATE_FILENAME
        state_bytes = state_path.read_bytes()
        state = json.loads(state_bytes)
        config = self.read_fake_config()
        feature = config["features"]["multi_agent_v2"]
        feature["multi_agent_mode_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\nroute through execution_worker"
        )
        feature["usage_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\nroute through verification_worker"
        )
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )

        status = self.run_script("--status")
        self.assertIn("managed fields conflict", status.stdout)

        preview = self.run_script("--repair")
        self.assertIn("mode and usage", preview.stdout)
        self.assertIn("Dry run only", preview.stdout)
        self.assertEqual(self.read_fake_config(), config)
        self.assertEqual(state_path.read_bytes(), state_bytes)

        repaired = self.run_script("--repair", "--apply")
        self.assertIn("Native routing policy repaired", repaired.stdout)
        self.assertIn("fully quit and reopen Codex", repaired.stdout)
        self.assertIn("does not change Claude Fable 5 authentication", repaired.stdout)
        after = self.read_fake_config()
        repaired_feature = after["features"]["multi_agent_v2"]
        self.assertEqual(
            repaired_feature["multi_agent_mode_hint_text"],
            state["managed"]["mode"],
        )
        self.assertEqual(
            repaired_feature["usage_hint_text"],
            state["managed"]["usage"],
        )
        self.assertFalse(repaired_feature["hide_spawn_agent_metadata"])
        self.assertEqual(repaired_feature["tool_namespace"], "agents")
        self.assertEqual(after["unrelated"], {"keep": True})
        self.assertEqual(state_path.read_bytes(), state_bytes)
        healthy = self.run_script("--status", "--require-effective")
        self.assertIn("installed and effective", healthy.stdout)

    def test_repair_refuses_unmarked_or_unrelated_control_drift(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        config = self.read_fake_config()
        feature = config["features"]["multi_agent_v2"]
        feature["multi_agent_mode_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent mode"
        )
        feature["usage_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent usage"
        )
        feature["tool_namespace"] = "collaboration"
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        refused = self.run_script("--repair", "--apply", check=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("only managed mode/usage drift", refused.stderr)
        self.assertEqual(self.read_fake_config(), config)

        feature["tool_namespace"] = "agents"
        feature["usage_hint_text"] = "USER AUTHORED USAGE"
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        refused = self.run_script("--repair", "--apply", check=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("managed ownership marker", refused.stderr)
        self.assertEqual(self.read_fake_config(), config)

    def test_repair_preserves_a_concurrent_user_edit(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        config = self.read_fake_config()
        feature = config["features"]["multi_agent_v2"]
        feature["multi_agent_mode_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent mode"
        )
        feature["usage_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent usage"
        )
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        (self.home / ".fake-mutate-after-write").touch()
        repaired = self.run_script("--repair", "--apply", check=False)
        self.assertEqual(repaired.returncode, 2)
        self.assertIn("newer edit was preserved", repaired.stderr)
        self.assertEqual(
            self.read_fake_config()["features"]["multi_agent_v2"]["usage_hint_text"],
            "CONCURRENT USER EDIT",
        )
        self.assertTrue((self.home / NATIVE.STATE_FILENAME).exists())

    def test_repair_requires_state_and_noops_when_already_matching(self) -> None:
        missing = self.run_script("--repair", "--apply", check=False)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("requires valid saved plugin state", missing.stderr)
        self.assertFalse((self.home / ".fake-user-config.json").exists())

        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        before_config = self.read_fake_config()
        state_path = self.home / NATIVE.STATE_FILENAME
        before_state = state_path.read_bytes()
        no_op = self.run_script("--repair", "--apply")
        self.assertIn("already matches", no_op.stdout)
        self.assertEqual(self.read_fake_config(), before_config)
        self.assertEqual(state_path.read_bytes(), before_state)

    def test_repair_rolls_back_when_effective_policy_is_overridden(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        config = self.read_fake_config()
        feature = config["features"]["multi_agent_v2"]
        feature["multi_agent_mode_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent mode"
        )
        feature["usage_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent usage"
        )
        serialized = json.dumps(config)
        (self.home / ".fake-user-config.json").write_text(
            serialized, encoding="utf-8"
        )
        (self.home / ".fake-effective-config.json").write_text(
            serialized, encoding="utf-8"
        )
        repaired = self.run_script("--repair", "--apply", check=False)
        self.assertEqual(repaired.returncode, 2)
        self.assertIn("did not become effective", repaired.stderr)
        self.assertEqual(self.read_fake_config(), config)
        self.assertTrue((self.home / NATIVE.STATE_FILENAME).exists())

    def test_repair_refuses_fable_launcher_enablement_drift(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--advisor-fable",
            "--apply",
        )
        config = self.read_fake_config()
        feature = config["features"]["multi_agent_v2"]
        feature["multi_agent_mode_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent mode"
        )
        feature["usage_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent usage"
        )
        config["plugins"][NATIVE.PLUGIN_ID]["mcp_servers"][
            "fable-advisor-python3"
        ]["enabled"] = False
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        refused = self.run_script("--repair", "--apply", check=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("Fable launcher setting changed", refused.stderr)
        self.assertEqual(self.read_fake_config(), config)

    def test_repair_refuses_integer_substitution_for_fable_boolean(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--advisor-fable",
            "--apply",
        )
        config = self.read_fake_config()
        feature = config["features"]["multi_agent_v2"]
        feature["usage_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent usage"
        )
        config["plugins"][NATIVE.PLUGIN_ID]["mcp_servers"][
            "fable-advisor-python3"
        ]["enabled"] = 1
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        refused = self.run_script("--repair", "--apply", check=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("Fable launcher setting changed", refused.stderr)
        self.assertEqual(self.read_fake_config(), config)

    def test_repair_detects_a_concurrent_saved_state_edit(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        config = self.read_fake_config()
        feature = config["features"]["multi_agent_v2"]
        feature["multi_agent_mode_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent mode"
        )
        feature["usage_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent usage"
        )
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        (self.home / ".fake-mutate-state-after-write").touch()
        repaired = self.run_script("--repair", "--apply", check=False)
        self.assertEqual(repaired.returncode, 2)
        self.assertIn("state changed concurrently", repaired.stderr)
        state = json.loads(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(
            state["previous"]["usage"]["value"], "CONCURRENT STATE EDIT"
        )

    def test_repair_handles_one_hint_in_a_scalar_conversion_only(self) -> None:
        initial = {"features": {"multi_agent_v2": True}, "keep": "yes"}
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(initial), encoding="utf-8"
        )
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        state_path = self.home / NATIVE.STATE_FILENAME
        state_bytes = state_path.read_bytes()
        config = self.read_fake_config()
        feature = config["features"]["multi_agent_v2"]
        feature["usage_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent usage"
        )
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        preview = self.run_script("--repair")
        self.assertIn("saved managed usage hint only", preview.stdout)
        self.run_script("--repair", "--apply")
        self.assertEqual(state_path.read_bytes(), state_bytes)

        config = self.read_fake_config()
        feature = config["features"]["multi_agent_v2"]
        feature["usage_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent usage again"
        )
        feature["unrelated_new_field"] = True
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        refused = self.run_script("--repair", "--apply", check=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("table has other changes", refused.stderr)
        self.assertEqual(self.read_fake_config(), config)

    def test_repair_refuses_noop_scalar_table_drift(self) -> None:
        initial = {"features": {"multi_agent_v2": True}, "keep": "yes"}
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(initial), encoding="utf-8"
        )
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        config = self.read_fake_config()
        config["features"]["multi_agent_v2"]["enabled"] = False
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        refused = self.run_script("--repair", "--apply", check=False)
        self.assertEqual(refused.returncode, 2)
        self.assertNotIn("already matches", refused.stdout)
        self.assertIn("another owned control", refused.stderr)
        self.assertEqual(self.read_fake_config(), config)

    def test_repair_detects_concurrent_scalar_table_drift(self) -> None:
        initial = {"features": {"multi_agent_v2": True}, "keep": "yes"}
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(initial), encoding="utf-8"
        )
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        config = self.read_fake_config()
        config["features"]["multi_agent_v2"]["usage_hint_text"] = (
            f"{NATIVE.MANAGED_MARKER}\ndifferent usage"
        )
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        (self.home / ".fake-mutate-feature-after-write").touch()
        repaired = self.run_script("--repair", "--apply", check=False)
        self.assertEqual(repaired.returncode, 2)
        self.assertIn("newer edit was preserved", repaired.stderr)
        self.assertEqual(
            self.read_fake_config()["features"]["multi_agent_v2"][
                "max_concurrent_threads_per_session"
            ],
            9,
        )
        self.assertTrue((self.home / NATIVE.STATE_FILENAME).exists())

    def test_disable_without_state_preserves_managed_and_user_hints(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        (self.home / NATIVE.STATE_FILENAME).unlink()
        config = self.read_fake_config()
        feature = config["features"]["multi_agent_v2"]
        feature["usage_hint_text"] = "USER USAGE"
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        config_before = (self.home / ".fake-user-config.json").read_bytes()
        disabled = self.run_script("--disable", "--apply", check=False)
        self.assertEqual(disabled.returncode, 2)
        self.assertIn("saved restore state is missing", disabled.stderr)
        self.assertEqual(
            (self.home / ".fake-user-config.json").read_bytes(), config_before
        )

    def test_incompatible_client_blocks_setup_but_never_disable(self) -> None:
        _, old_codex = _write_test_cli(self.root, "old-codex", FAKE_CODEX)
        refused = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--compat-bin",
            str(old_codex),
            check=False,
            allow_incompatible=False,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("shared config unreadable", refused.stderr)

        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        disabled = self.run_script(
            "--disable",
            "--apply",
            "--compat-bin",
            str(old_codex),
            allow_incompatible=False,
        )
        self.assertIn("Native routing disabled", disabled.stdout)

    def test_require_effective_rejects_inactive_and_incompatible_status(self) -> None:
        inactive = self.run_script(
            "--status", "--require-effective", check=False
        )
        self.assertEqual(inactive.returncode, 1)
        self.assertIn("Native policy: inactive", inactive.stdout)

        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        _, old_codex = _write_test_cli(self.root, "old-status-codex", FAKE_CODEX)
        incompatible = self.run_script(
            "--status",
            "--require-effective",
            "--compat-bin",
            str(old_codex),
            check=False,
        )
        self.assertEqual(incompatible.returncode, 1)
        self.assertIn("incompatible", incompatible.stdout)

    def test_require_effective_rejects_orphaned_managed_personal_role(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        agents = self.home / "agents"
        agents.mkdir()
        orphan_name = "codex_orchestration_executor_012345abcdef"
        (agents / "orphan.toml").write_text(
            "\n".join(
                (
                    NATIVE.CUSTOM_AGENT_MANAGED_MARKER,
                    f'name = "{orphan_name}"',
                    'description = "Managed orphan"',
                    'model = "gpt-5.6-luna"',
                    'developer_instructions = "Stay bounded."',
                    "",
                )
            ),
            encoding="utf-8",
        )
        status = self.run_script(
            "--status", "--require-effective", check=False
        )
        self.assertEqual(status.returncode, 1)
        self.assertIn("Orphaned managed custom agents", status.stdout)
        self.assertIn(orphan_name, status.stdout)

    def test_require_effective_requires_status(self) -> None:
        result = self.run_script("--require-effective", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires --status", result.stderr)

    def test_state_from_another_config_is_refused(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        state_path = self.home / NATIVE.STATE_FILENAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["config_file"] = str(self.root / "different" / "config.toml")
        state_path.write_text(json.dumps(state), encoding="utf-8")

        result = self.run_script("--status", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("different Codex config file", result.stderr)

    def test_status_suppresses_seats_when_state_conflicts(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        state_path = self.home / NATIVE.STATE_FILENAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["managed"]["usage"] = (
            f"{NATIVE.MANAGED_MARKER}\nDIFFERENT MANAGED VALUE\n"
            f"{NATIVE.routing_state_binding(state)}"
        )
        state_path.write_text(json.dumps(state), encoding="utf-8")
        status = self.run_script("--status")
        self.assertIn("managed fields conflict", status.stdout)
        self.assertIn("Seats: suppressed", status.stdout)
        self.assertNotIn("Executor: gpt-5.6-luna", status.stdout)

    def test_concurrent_user_edit_after_write_is_preserved(self) -> None:
        (self.home / ".fake-mutate-after-write").touch()
        result = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("newer edit was preserved", result.stderr)
        feature = self.read_fake_config()["features"]["multi_agent_v2"]
        self.assertEqual(feature["usage_hint_text"], "CONCURRENT USER EDIT")
        self.assertTrue((self.home / NATIVE.STATE_FILENAME).exists())

    def test_concurrent_namespace_edit_after_write_is_preserved(self) -> None:
        (self.home / ".fake-mutate-namespace-after-write").touch()
        result = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("newer edit was preserved", result.stderr)
        feature = self.read_fake_config()["features"]["multi_agent_v2"]
        self.assertEqual(feature["tool_namespace"], "collaboration")
        self.assertTrue((self.home / NATIVE.STATE_FILENAME).exists())

    def test_setup_cas_preserves_a_concurrent_valid_state_replacement(self) -> None:
        self.run_script("--executor-model", "gpt-5.6-luna", "--apply")
        state_path = self.home / NATIVE.STATE_FILENAME
        replacement = state_path.read_bytes()
        self.run_script("--disable", "--apply")
        baseline_config = self.read_fake_config()
        payload = self.home / ".fake-concurrent-routing-state.json"
        payload.write_bytes(replacement)

        rejected = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
            check=False,
        )

        self.assertEqual(rejected.returncode, 2)
        self.assertIn("state changed concurrently", rejected.stderr)
        self.assertEqual(state_path.read_bytes(), replacement)
        self.assertEqual(self.read_fake_config(), baseline_config)

    def test_disable_cas_preserves_a_concurrent_valid_state_replacement(self) -> None:
        self.run_script("--executor-model", "gpt-5.6-luna", "--apply")
        state_path = self.home / NATIVE.STATE_FILENAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        replacement = (json.dumps(state, indent=4, sort_keys=True) + "\n").encode()
        payload = self.home / ".fake-concurrent-routing-state.json"
        payload.write_bytes(replacement)
        managed_config = self.read_fake_config()

        rejected = self.run_script("--disable", "--apply", check=False)

        self.assertEqual(rejected.returncode, 2)
        self.assertIn("state changed concurrently", rejected.stderr)
        self.assertEqual(state_path.read_bytes(), replacement)
        self.assertEqual(self.read_fake_config(), managed_config)

    def test_state_write_works_when_fchmod_is_unavailable(self) -> None:
        state_path = self.home / "portable-state.json"
        state = {
            "schema": NATIVE.STATE_SCHEMA,
            "managed_by": "codex-orchestration",
            "config_file": str(self.home / "config.toml"),
        }
        with mock.patch.object(NATIVE.os, "fchmod", None, create=True):
            NATIVE._write_state(state_path, state)
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), state)

    def test_state_cas_uses_windows_lock_backend_without_fcntl(self) -> None:
        self.run_script("--executor-model", "gpt-5.6-luna", "--apply")
        state_path = self.home / NATIVE.STATE_FILENAME
        state, revision = NATIVE._read_state_with_revision(state_path)
        self.assertIsNotNone(state)
        self.assertIsNotNone(revision)

        class FakeMsvcrt:
            LK_LOCK = 1
            LK_UNLCK = 2

            def __init__(self) -> None:
                self.calls: list[tuple[int, int]] = []

            def locking(self, descriptor: int, mode: int, size: int) -> None:
                self.calls.append((mode, size))

        windows_lock = FakeMsvcrt()
        with (
            mock.patch.object(NATIVE, "fcntl", None),
            mock.patch.object(NATIVE, "msvcrt", windows_lock),
        ):
            written_revision = NATIVE._write_state_cas(
                state_path,
                state,
                revision,
            )
            NATIVE._remove_state_cas(state_path, written_revision)

        self.assertFalse(state_path.exists())
        self.assertEqual(
            windows_lock.calls,
            [
                (windows_lock.LK_LOCK, 1),
                (windows_lock.LK_UNLCK, 1),
                (windows_lock.LK_LOCK, 1),
                (windows_lock.LK_UNLCK, 1),
            ],
        )

    def test_missing_state_lock_backend_fails_before_config_write(self) -> None:
        with (
            mock.patch.object(NATIVE, "fcntl", None),
            mock.patch.object(NATIVE, "msvcrt", None),
        ):
            with self.assertRaisesRegex(
                NATIVE.ConfigurationError,
                "no supported file-lock backend",
            ):
                NATIVE._require_state_lock_backend()

    def test_effective_project_override_is_reported_and_blocks_setup(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        effective = self.read_fake_config()
        effective["features"]["multi_agent_v2"]["tool_namespace"] = "collaboration"
        (self.home / ".fake-effective-config.json").write_text(
            json.dumps(effective), encoding="utf-8"
        )
        status = self.run_script("--status")
        self.assertIn("installed but overridden", status.stdout)
        self.assertIn("not routed through agents", status.stdout)

        update = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
            check=False,
        )
        self.assertEqual(update.returncode, 2)
        self.assertIn("effective readback did not match", update.stderr)
        state = json.loads(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(state["executor"]["model"], "gpt-5.6-luna")

    def test_effective_readback_rejects_unexpected_rollback_status(self) -> None:
        effective = {
            "features": {
                "multi_agent_v2": {
                    "hide_spawn_agent_metadata": True,
                    "tool_namespace": "collaboration",
                }
            }
        }
        (self.home / ".fake-effective-config.json").write_text(
            json.dumps(effective), encoding="utf-8"
        )
        real_batch_write = NATIVE._batch_write
        calls = 0

        def batch_write(*args: object, **kwargs: object) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 1:
                return real_batch_write(*args, **kwargs)
            return {"status": "unexpected", "version": "sha256:unknown"}

        argv = [
            str(SCRIPT),
            "--codex-bin",
            str(self.codex),
            "--codex-home",
            str(self.home),
            "--allow-incompatible-client",
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        ]
        stderr = io.StringIO()
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(NATIVE, "_batch_write", side_effect=batch_write),
            mock.patch.object(sys, "stderr", stderr),
        ):
            result = NATIVE.main()

        self.assertEqual(result, 2)
        self.assertEqual(calls, 2)
        self.assertIn("automatic rollback failed", stderr.getvalue())
        self.assertIn("unexpected rollback status", stderr.getvalue())
        self.assertTrue((self.home / NATIVE.STATE_FILENAME).exists())

    def test_ok_overridden_restores_every_owned_field(self) -> None:
        initial = {
            "features": {
                "multi_agent_v2": {"max_concurrent_threads_per_session": 5}
            },
            "unrelated": {"keep": True},
        }
        (self.home / ".fake-ok-overridden").touch()
        result = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("user config change was rolled back", result.stderr)
        self.assertNotIn("automatic rollback failed", result.stderr)
        self.assertEqual(self.read_fake_config(), initial)
        self.assertFalse((self.home / NATIVE.STATE_FILENAME).exists())

    def test_ok_overridden_rollback_failure_is_reported_truthfully(self) -> None:
        (self.home / ".fake-ok-overridden").touch()
        (self.home / ".fake-fail-overridden-rollback").touch()
        result = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("automatic rollback failed", result.stderr)
        self.assertIn("user layer may still contain", result.stderr)
        self.assertNotIn("user config change was rolled back", result.stderr)
        feature = self.read_fake_config()["features"]["multi_agent_v2"]
        self.assertEqual(feature["tool_namespace"], "agents")
        self.assertIn(NATIVE.MANAGED_MARKER, feature["usage_hint_text"])
        self.assertFalse((self.home / NATIVE.STATE_FILENAME).exists())

    def test_state_failure_rejects_unexpected_rollback_status(self) -> None:
        real_batch_write = NATIVE._batch_write
        calls = 0

        def batch_write(*args: object, **kwargs: object) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 1:
                return real_batch_write(*args, **kwargs)
            return {"status": "unexpected", "version": "sha256:unknown"}

        argv = [
            str(SCRIPT),
            "--codex-bin",
            str(self.codex),
            "--codex-home",
            str(self.home),
            "--allow-incompatible-client",
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        ]
        stderr = io.StringIO()
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(
                NATIVE,
                "_write_state",
                side_effect=NATIVE.ConfigurationError("forced state failure"),
            ),
            mock.patch.object(NATIVE, "_batch_write", side_effect=batch_write),
            mock.patch.object(sys, "stderr", stderr),
        ):
            result = NATIVE.main()

        self.assertEqual(result, 2)
        self.assertEqual(calls, 2)
        self.assertIn("may still contain managed fields", stderr.getvalue())
        self.assertIn("unexpected rollback status", stderr.getvalue())
        feature = self.read_fake_config()["features"]["multi_agent_v2"]
        self.assertIn(NATIVE.MANAGED_MARKER, feature["usage_hint_text"])

    def test_luna_executor_with_optional_custom_advisor(self) -> None:
        self.write_personal_agent("codex_orchestration_advisor")
        result = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--advisor-agent",
            "codex_orchestration_advisor",
            "--apply",
        )
        self.assertIn("Executor: gpt-5.6-luna@max", result.stdout)
        feature = self.read_fake_config()["features"]["multi_agent_v2"]
        usage = feature["usage_hint_text"]
        self.assertIn('model = "gpt-5.6-luna"', usage)
        self.assertIn('agent_type = "codex_orchestration_advisor"', usage)
        self.assertIn("No Designer route is configured", usage)

    def test_custom_planner_shadow_and_orphan_tracking(self) -> None:
        name = "codex_orchestration_planner_012345abcdef"
        self.write_personal_agent(name, managed=True)
        setup = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-agent",
            name,
            "--apply",
        )
        self.assertIn(f"Planner: custom agent {name}", setup.stdout)
        healthy = self.run_script("--status", "--require-effective")
        self.assertIn("Orphaned managed custom agents: none", healthy.stdout)

        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--apply",
        )
        orphaned = self.run_script(
            "--status", "--require-effective", check=False
        )
        self.assertEqual(orphaned.returncode, 1)
        self.assertIn(name, orphaned.stdout)

        # Re-selecting the role is still refused if the project shadows it.
        project_agents = self.root / ".codex" / "agents"
        project_agents.mkdir(parents=True)
        (project_agents / "shadow.toml").write_text(
            "\n".join(
                (
                    f'name = "{name}"',
                    'description = "Shadow"',
                    'model = "other-model"',
                    'developer_instructions = "Shadow the planner."',
                    "",
                )
            ),
            encoding="utf-8",
        )
        shadowed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--codex-bin",
                str(self.codex),
                "--codex-home",
                str(self.home),
                "--allow-incompatible-client",
                "--executor-model",
                "gpt-5.6-luna",
                "--planner-agent",
                name,
                "--apply",
            ],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        self.assertEqual(shadowed.returncode, 2)
        self.assertIn("Planner personal agent", shadowed.stderr)
        self.assertIn("shadowed by a project role", shadowed.stderr)

    def test_identical_planner_advisor_routes_rejected_on_clean_setup_and_update(self) -> None:
        same_model = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-model",
            "gpt-5.6-sol",
            "--planner-effort",
            "low",
            "--advisor-model",
            "gpt-5.6-sol",
            "--advisor-effort",
            "ultra",
            check=False,
        )
        self.assertEqual(same_model.returncode, 2)
        self.assertIn("Planner and Advisor routes must be distinct", same_model.stderr)
        self.assertFalse((self.home / NATIVE.STATE_FILENAME).exists())

        self.write_personal_agent("shared_planning_agent")
        same_agent = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-agent",
            "shared_planning_agent",
            "--advisor-agent",
            "shared_planning_agent",
            check=False,
        )
        self.assertEqual(same_agent.returncode, 2)
        self.assertIn("Planner and Advisor routes must be distinct", same_agent.stderr)

        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-model",
            "gpt-5.6-sol",
            "--advisor-model",
            "gpt-5.6-terra",
            "--apply",
        )
        before_config = self.read_fake_config()
        before_state = (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        rejected_update = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-model",
            "gpt-5.6-terra",
            "--advisor-model",
            "gpt-5.6-terra",
            "--apply",
            check=False,
        )
        self.assertEqual(rejected_update.returncode, 2)
        self.assertEqual(self.read_fake_config(), before_config)
        self.assertEqual(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8"),
            before_state,
        )

    def test_two_fable_planning_seats_are_rejected_before_prerequisites(self) -> None:
        result = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-fable",
            "--planner-effort",
            "low",
            "--advisor-fable",
            "--advisor-effort",
            "max",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("at most one bundled Claude subscription seat", result.stderr)
        self.assertFalse((self.home / NATIVE.STATE_FILENAME).exists())

    def test_fable_planner_with_gpt_advisor_uses_one_launcher_and_restores(self) -> None:
        initial = {
            "features": {"multi_agent_v2": {}},
            "plugins": {
                NATIVE.PLUGIN_ID: {
                    "mcp_servers": {
                        "fable-advisor-python3": {"enabled": False},
                        "fable-advisor-python": {"enabled": True},
                        "fable-advisor-py": {"enabled": True},
                    }
                }
            },
        }
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(initial), encoding="utf-8"
        )
        setup = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-fable",
            "--planner-effort",
            "max",
            "--advisor-model",
            "gpt-5.6-terra",
            "--apply",
        )
        self.assertIn("Planner: Claude Fable 5 max", setup.stdout)
        state = json.loads(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(state["planner"]["kind"], "fable")
        self.assertEqual(state["advisor"]["kind"], "model")
        managed_mcp = state["managed"]["mcp"]
        self.assertEqual(sum(value is True for value in managed_mcp.values()), 1)
        self.assertTrue(managed_mcp["fable-advisor-python3"])
        servers = self.read_fake_config()["plugins"][NATIVE.PLUGIN_ID]["mcp_servers"]
        self.assertEqual(
            sum(entry["enabled"] is True for entry in servers.values()), 1
        )

        moved = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-model",
            "gpt-5.6-sol",
            "--advisor-fable",
            "--advisor-effort",
            "high",
            "--apply",
        )
        self.assertIn("Advisor: Claude Fable 5 high", moved.stdout)
        moved_servers = self.read_fake_config()["plugins"][NATIVE.PLUGIN_ID][
            "mcp_servers"
        ]
        self.assertTrue(moved_servers["fable-advisor-python3"]["enabled"])
        self.assertEqual(
            sum(entry["enabled"] is True for entry in moved_servers.values()), 1
        )

        self.run_script("--disable", "--apply")
        self.assertEqual(self.read_fake_config(), initial)

    def test_gpt_planner_with_fable_advisor(self) -> None:
        setup = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-model",
            "gpt-5.6-sol",
            "--advisor-fable",
            "--advisor-effort",
            "medium",
            "--apply",
        )
        self.assertIn("Planner: gpt-5.6-sol@xhigh", setup.stdout)
        self.assertIn("Advisor: Claude Fable 5 medium", setup.stdout)
        state = json.loads(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(state["planner"]["kind"], "model")
        self.assertEqual(state["advisor"]["kind"], "fable")

    def test_fable_setup_status_update_and_disable_restore_mcp_policy(self) -> None:
        initial = {
            "features": {
                "multi_agent_v2": {"max_concurrent_threads_per_session": 5}
            },
            "plugins": {
                NATIVE.PLUGIN_ID: {
                    "mcp_servers": {
                        "fable-advisor-python3": {"enabled": False},
                        "fable-advisor-python": {"enabled": True},
                    }
                }
            },
            "unrelated": {"keep": True},
        }
        (self.home / ".fake-user-config.json").write_text(
            json.dumps(initial), encoding="utf-8"
        )
        setup = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--advisor-fable",
            "--advisor-effort",
            "max",
            "--apply",
        )
        self.assertIn("Claude Fable 5 max", setup.stdout)
        config = self.read_fake_config()
        servers = config["plugins"][NATIVE.PLUGIN_ID]["mcp_servers"]
        self.assertTrue(servers["fable-advisor-python3"]["enabled"])
        self.assertFalse(servers["fable-advisor-python"]["enabled"])
        self.assertNotIn("fable-advisor-py", servers)
        state = json.loads(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(state["advisor"]["kind"], "fable")
        self.assertEqual(state["advisor"]["model"], "claude-fable-5")
        self.assertIn("mcp", state["previous"])

        status = self.run_script("--status")
        self.assertIn("Claude Fable 5: ready", status.stdout)
        self.assertIn("no model call made", status.stdout)

        update = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--apply",
        )
        self.assertIn("Advisor: none", update.stdout)
        servers = self.read_fake_config()["plugins"][NATIVE.PLUGIN_ID]["mcp_servers"]
        self.assertTrue(all(not entry["enabled"] for entry in servers.values()))

        self.run_script("--disable", "--apply")
        self.assertEqual(self.read_fake_config(), initial)

    def test_fable_effort_defaults_to_high_and_ultra_maps_to_max(self) -> None:
        setup = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--advisor-fable",
            "--apply",
        )
        self.assertIn("Advisor: Claude Fable 5 high", setup.stdout)
        state = json.loads(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(state["advisor"]["effort"], "high")

        update = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--advisor-fable",
            "--advisor-effort",
            "ultra",
            "--apply",
        )
        self.assertIn("Advisor: Claude Fable 5 max", update.stdout)
        self.assertIn("Advisor effort alias: ultra -> max", update.stdout)
        state = json.loads(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(state["advisor"]["effort"], "max")

    def test_fable_effort_normalization_accepts_every_public_label(self) -> None:
        expected = {
            "auto": "high",
            "low": "low",
            "medium": "medium",
            "high": "high",
            "xhigh": "xhigh",
            "max": "max",
            "ultra": "max",
        }
        for requested, effective in expected.items():
            with self.subTest(requested=requested):
                self.assertEqual(
                    NATIVE.normalize_fable_effort(requested), effective
                )

        with self.assertRaisesRegex(
            NATIVE.ConfigurationError, "low.*medium.*high.*xhigh.*max.*ultra"
        ):
            NATIVE.normalize_fable_effort("extreme")

    def test_opus_setup_status_update_and_disable_are_no_model_call(self) -> None:
        setup = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-opus",
            "--advisor-effort",
            "xhigh",
            "--apply",
        )
        self.assertIn("Advisor: Claude Opus 5 xhigh", setup.stdout)
        self.assertIn("setup makes no model call", setup.stdout)
        state = json.loads(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(state["schema"], 6)
        self.assertEqual(
            state["advisor"],
            {
                "kind": "claude_subscription",
                "model": "claude-opus-5",
                "effort": "xhigh",
                "server": "fable-advisor-python3",
            },
        )

        status = self.run_script("--status", "--require-effective")
        self.assertIn("Claude Opus 5: ready", status.stdout)
        self.assertIn("no model call made", status.stdout)

        update = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-opus",
            "--advisor-effort",
            "max",
            "--apply",
        )
        self.assertIn("Advisor: Claude Opus 5 max", update.stdout)
        updated = json.loads(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(updated["advisor"]["effort"], "max")

        self.run_script("--disable", "--apply")
        self.assertFalse((self.home / NATIVE.STATE_FILENAME).exists())
        servers = (
            self.read_fake_config()
            .get("plugins", {})
            .get(NATIVE.PLUGIN_ID, {})
            .get("mcp_servers", {})
        )
        self.assertTrue(
            all(not entry.get("enabled", False) for entry in servers.values())
        )

    def test_opus_transition_requires_full_disable_then_roundtrips(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-fable",
            "--apply",
        )
        before_config = self.read_fake_config()
        before_state = (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8")
        rejected = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-opus",
            "--apply",
            check=False,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn(
            "configure_native_routing.py --disable --apply", rejected.stderr
        )
        self.assertEqual(self.read_fake_config(), before_config)
        self.assertEqual(
            (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8"),
            before_state,
        )

        self.run_script("--disable", "--apply")
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-opus",
            "--apply",
        )
        for requested in (
            ("--advisor-fable",),
            ("--planner-opus",),
            (),
        ):
            with self.subTest(requested=requested):
                before_config = self.read_fake_config()
                before_state = (
                    self.home / NATIVE.STATE_FILENAME
                ).read_text(encoding="utf-8")
                rejected = self.run_script(
                    "--executor-model",
                    "gpt-5.6-luna",
                    *requested,
                    "--apply",
                    check=False,
                )
                self.assertEqual(rejected.returncode, 2)
                self.assertIn(
                    "configure_native_routing.py --disable --apply",
                    rejected.stderr,
                )
                self.assertEqual(self.read_fake_config(), before_config)
                self.assertEqual(
                    (self.home / NATIVE.STATE_FILENAME).read_text(encoding="utf-8"),
                    before_state,
                )

        self.run_script("--disable", "--apply")
        fable = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-fable",
            "--apply",
        )
        self.assertIn("Planner: Claude Fable 5 high", fable.stdout)

    def test_generic_opus_transitions_are_rejected_without_writes(self) -> None:
        state_path = self.home / NATIVE.STATE_FILENAME
        version_path = self.home / ".fake-version"

        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-fable",
            "--apply",
        )
        before_config = self.read_fake_config()
        before_state = state_path.read_text(encoding="utf-8")
        before_version = version_path.read_text(encoding="utf-8")
        fable_to_generic = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-model",
            NATIVE.OPUS_MODEL,
            "--advisor-effort",
            "high",
            "--confirm-unlisted-models",
            "--apply",
            check=False,
        )
        self.assertEqual(fable_to_generic.returncode, 2)
        self.assertIn("reserved Claude model", fable_to_generic.stderr)
        self.assertEqual(self.read_fake_config(), before_config)
        self.assertEqual(state_path.read_text(encoding="utf-8"), before_state)
        self.assertEqual(version_path.read_text(encoding="utf-8"), before_version)

        self.run_script("--disable", "--apply")
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-model",
            "gpt-5.6-terra",
            "--apply",
        )
        forged = json.loads(state_path.read_text(encoding="utf-8"))
        forged["advisor"]["model"] = NATIVE.OPUS_MODEL
        state_path.write_text(json.dumps(forged), encoding="utf-8")
        before_config = self.read_fake_config()
        before_state = state_path.read_text(encoding="utf-8")
        before_version = version_path.read_text(encoding="utf-8")
        generic_to_fable = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-fable",
            "--apply",
            check=False,
        )
        self.assertEqual(generic_to_fable.returncode, 2)
        self.assertIn("Saved routing state is invalid", generic_to_fable.stderr)
        self.assertEqual(self.read_fake_config(), before_config)
        self.assertEqual(state_path.read_text(encoding="utf-8"), before_state)
        self.assertEqual(version_path.read_text(encoding="utf-8"), before_version)

    def test_opus_version_and_effort_prerequisites_fail_closed(self) -> None:
        original = self.claude.read_text(encoding="utf-8")
        self.claude.write_text(
            original.replace("2.1.219 (Claude Code)", "2.1.218 (Claude Code)"),
            encoding="utf-8",
        )
        too_old = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-opus",
            check=False,
        )
        self.assertEqual(too_old.returncode, 2)
        self.assertIn("requires Claude Code 2.1.219 or newer", too_old.stderr)
        self.assertFalse((self.home / NATIVE.STATE_FILENAME).exists())

    def test_opus_version_output_must_be_one_canonical_version_line(self) -> None:
        original = self.claude.read_text(encoding="utf-8")

        for output in (
            "2.1.219 (Claude Code)",
            " \t2.1.219 (Claude Code)\r\n",
            "2.1.220 (Claude Code)",
            "2.2.0 (Claude Code)",
            "3.0.0 (Claude Code)",
        ):
            with self.subTest(accepted=output):
                self.claude.write_text(
                    original.replace(
                        'print("2.1.219 (Claude Code)")',
                        f"print({output!r})",
                    ),
                    encoding="utf-8",
                )
                accepted = self.run_script(
                    "--executor-model",
                    "gpt-5.6-luna",
                    "--advisor-opus",
                )
                self.assertIn("Dry run only", accepted.stdout)

        for output in (
            "wrapper 9.9.9\n2.1.219 (Claude Code)",
            "2.1.219 (Claude Code)\n2.1.220 (Claude Code)",
            "Claude Code 2.1.219",
            "prefix2.1.219 (Claude Code)",
            "2.1.219 (Claude Code)suffix",
            "02.1.219 (Claude Code)",
            f"{'9' * 5000}.1.1 (Claude Code)",
        ):
            with self.subTest(rejected=output):
                self.claude.write_text(
                    original.replace(
                        'print("2.1.219 (Claude Code)")',
                        f"print({output!r})",
                    ),
                    encoding="utf-8",
                )
                rejected = self.run_script(
                    "--executor-model",
                    "gpt-5.6-luna",
                    "--advisor-opus",
                    check=False,
                )
                self.assertEqual(rejected.returncode, 2)
                self.assertIn("unparseable version", rejected.stderr)
                self.assertFalse(
                    (self.home / NATIVE.STATE_FILENAME).exists()
                )

        self.claude.write_text(
            original.replace(
                'print("2.1.219 (Claude Code)")',
                "print('2.1.218 (Claude Code)')",
            ),
            encoding="utf-8",
        )
        too_old = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-opus",
            check=False,
        )
        self.assertEqual(too_old.returncode, 2)
        self.assertIn("requires Claude Code 2.1.219 or newer", too_old.stderr)

    def test_bundled_claude_prerequisite_checks_every_runtime_control(self) -> None:
        original = self.claude.read_text(encoding="utf-8")
        required = (
            "--print",
            "--model",
            "--effort",
            "--safe-mode",
            "--tools",
            "--permission-mode",
            "--no-session-persistence",
            "--prompt-suggestions",
            "--output-format",
            "--json-schema",
            "--system-prompt",
        )
        for flag in required:
            with self.subTest(flag=flag):
                self.claude.write_text(
                    original.replace(flag, f"--missing-{flag.removeprefix('--')}"),
                    encoding="utf-8",
                )
                rejected = self.run_script(
                    "--executor-model",
                    "gpt-5.6-luna",
                    "--advisor-opus",
                    check=False,
                )
                self.assertEqual(rejected.returncode, 2)
                self.assertIn(flag, rejected.stderr)
                self.assertFalse((self.home / NATIVE.STATE_FILENAME).exists())
        self.claude.write_text(original, encoding="utf-8")

        self.claude.write_text(
            original.replace(
                "(low, medium, high, xhigh, max)",
                "(low, medium, high, max, future)",
            ),
            encoding="utf-8",
        )
        missing = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-opus",
            "--advisor-effort",
            "xhigh",
            check=False,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIn("does not advertise Claude Opus 5 effort 'xhigh'", missing.stderr)

        self.claude.write_text(
            original.replace(
                "(low, medium, high, xhigh, max)",
                "(unparseable)",
            ),
            encoding="utf-8",
        )
        malformed_efforts = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-opus",
            check=False,
        )
        self.assertEqual(malformed_efforts.returncode, 2)
        self.assertIn(
            "does not advertise Claude Opus 5 effort 'high'",
            malformed_efforts.stderr,
        )

        self.claude.write_text(
            original.replace(
                "(low, medium, high, xhigh, max)",
                "(low, medium, high, xhigh, max, future)",
            ),
            encoding="utf-8",
        )
        supported = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-opus",
            "--advisor-effort",
            "max",
        )
        self.assertIn("Dry run only", supported.stdout)
        unsealed = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-opus",
            "--advisor-effort",
            "future",
            check=False,
        )
        self.assertEqual(unsealed.returncode, 2)
        self.assertIn("Claude Opus 5 effort must be one of", unsealed.stderr)

        self.claude.write_text(
            original.replace("2.1.219 (Claude Code)", "not-a-version"),
            encoding="utf-8",
        )
        malformed = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-opus",
            check=False,
        )
        self.assertEqual(malformed.returncode, 2)
        self.assertIn("unparseable version", malformed.stderr)
        self.assertFalse((self.home / NATIVE.STATE_FILENAME).exists())

    def test_bundled_claude_requires_exact_long_option_tokens(self) -> None:
        original = self.claude.read_text(encoding="utf-8")
        required = (
            "--print",
            "--model",
            "--effort",
            "--safe-mode",
            "--tools",
            "--permission-mode",
            "--no-session-persistence",
            "--prompt-suggestions",
            "--output-format",
            "--json-schema",
            "--system-prompt",
        )
        for flag in required:
            for fake in (
                f"{flag}-FAKE",
                f"--FAKE{flag}",
            ):
                with self.subTest(flag=flag, fake=fake):
                    self.claude.write_text(
                        original.replace(flag, fake),
                        encoding="utf-8",
                    )
                    rejected = self.run_script(
                        "--executor-model",
                        "gpt-5.6-luna",
                        "--advisor-opus",
                        check=False,
                    )
                    self.assertEqual(rejected.returncode, 2)
                    self.assertIn(flag, rejected.stderr)
                    self.assertFalse(
                        (self.home / NATIVE.STATE_FILENAME).exists()
                    )

        duplicate_crlf = original.replace(
            "--print --model",
            r"--print\r\n--model",
        )
        for flag in required:
            duplicate_crlf = duplicate_crlf.replace(flag, f"{flag} {flag}")
        self.claude.write_text(duplicate_crlf, encoding="utf-8")
        accepted = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--advisor-opus",
        )
        self.assertIn("Dry run only", accepted.stdout)

    def test_opus_effort_set_matches_documented_contract(self) -> None:
        self.assertEqual(
            NATIVE.OPUS_EFFORTS,
            {"low", "medium", "high", "xhigh", "max"},
        )
        self.assertEqual(NATIVE.normalize_opus_effort("auto"), "high")
        for effort in NATIVE.OPUS_EFFORTS:
            self.assertEqual(NATIVE.normalize_opus_effort(effort), effort)

    def test_fable_setup_rejects_effort_missing_from_installed_claude(self) -> None:
        self.claude.write_text(
            self.claude.read_text(encoding="utf-8").replace(
                "(low, medium, high, xhigh, max)",
                "(low, medium, high, max)",
            ),
            encoding="utf-8",
        )
        result = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--advisor-fable",
            "--advisor-effort",
            "xhigh",
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "Claude Code does not advertise Fable effort 'xhigh'",
            result.stderr,
        )
        self.assertFalse((self.home / NATIVE.STATE_FILENAME).exists())

    def test_require_effective_rejects_unavailable_saved_fable_effort(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--advisor-fable",
            "--advisor-effort",
            "xhigh",
            "--apply",
        )
        self.claude.write_text(
            self.claude.read_text(encoding="utf-8").replace(
                "(low, medium, high, xhigh, max)",
                "(low, medium, high, max)",
            ),
            encoding="utf-8",
        )

        status = self.run_script(
            "--status",
            "--require-effective",
            check=False,
        )

        self.assertEqual(status.returncode, 1)
        self.assertIn(
            "Claude Code does not advertise Fable effort 'xhigh'",
            status.stdout,
        )

    def test_require_effective_rejects_unavailable_fable_auth(self) -> None:
        self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--executor-effort",
            "max",
            "--advisor-fable",
            "--apply",
        )
        self.claude.write_text(
            self.claude.read_text(encoding="utf-8").replace(
                '"loggedIn": True',
                '"loggedIn": False',
            ),
            encoding="utf-8",
        )

        status = self.run_script(
            "--status",
            "--require-effective",
            check=False,
        )

        self.assertEqual(status.returncode, 1)
        self.assertIn(
            "must be logged in through a first-party Pro, Max, or Team account",
            status.stdout,
        )

    def test_missing_or_project_shadowed_custom_agent_is_refused(self) -> None:
        name = "codex_orchestration_planner"
        missing = self.run_script(
            "--executor-model",
            "gpt-5.6-luna",
            "--planner-agent",
            name,
            "--apply",
            check=False,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIn("must resolve to exactly one personal file", missing.stderr)

        self.write_personal_agent(name)
        project_agents = self.root / ".codex" / "agents"
        project_agents.mkdir(parents=True)
        (project_agents / "shadow.toml").write_text(
            "\n".join(
                (
                    f'name = "{name}"',
                    'description = "Shadow"',
                    'model = "other-model"',
                    'developer_instructions = "Shadow the personal route."',
                    "",
                )
            ),
            encoding="utf-8",
        )
        shadowed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--codex-bin",
                str(self.codex),
                "--codex-home",
                str(self.home),
                "--allow-incompatible-client",
                "--executor-model",
                "gpt-5.6-luna",
                "--planner-agent",
                name,
                "--apply",
            ],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        self.assertEqual(shadowed.returncode, 2)
        self.assertIn("shadowed by a project role", shadowed.stderr)


if __name__ == "__main__":
    unittest.main()
