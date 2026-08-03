#!/usr/bin/env python3
"""Preview, apply, inspect, repair, or disable Codex-Orchestration's routing policy.

The script deliberately uses Codex App Server's config/read and config/batchWrite
RPCs instead of rewriting config.toml itself. Codex therefore owns TOML parsing,
validation, optimistic concurrency, comment preservation, atomic persistence, and
readback verification.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

try:  # The installer is supported on Unix desktop hosts.
    import fcntl
except ImportError:  # pragma: no cover - defensive package import on non-Unix hosts
    fcntl = None  # type: ignore[assignment]

try:  # Windows uses its standard byte-range locking API.
    import msvcrt
except ImportError:  # pragma: no cover - expected on non-Windows hosts
    msvcrt = None  # type: ignore[assignment]

from routing_state import (
    FABLE_EFFORTS,
    FABLE_MODEL,
    MANAGED_MARKER,
    OPUS_EFFORTS,
    OPUS_MODEL,
    ROUTING_TOOL_NAMESPACE,
    RoutingStateError,
    routing_state_binding,
    validate_routing_state,
)

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover - Python < 3.11
    raise SystemExit("Python 3.11 or newer is required (missing tomllib).") from exc


POLICY_VERSION = 6
STATE_SCHEMA = 6
TWO_LANE_POLICY_MARKER = "[codex-orchestration workflow 0.10 two-lane]"
ROUTINE_MODEL = "gpt-5.6-luna"
HARD_MODEL = "gpt-5.6-terra"
LANE_EFFORT = "max"
STATE_FILENAME = ".codex-orchestration-routing.json"
PROBE_VALUE = "CODEX_ORCHESTRATION_CAPABILITY_PROBE"
PLUGIN_ID = "codex-orchestration@codex-orchestration"
FABLE_DEFAULT_EFFORT = "high"
FABLE_EFFORT_CHOICES = ("low", "medium", "high", "xhigh", "max")
FABLE_EFFORT_ALIASES = {"ultra": "max"}
OPUS_DEFAULT_EFFORT = "high"
OPUS_MIN_CLAUDE_VERSION = (2, 1, 219)
FABLE_SERVERS = {
    "fable-advisor-python3": ("python3", []),
    "fable-advisor-python": ("python", []),
    "fable-advisor-py": ("py", ["-3.11"]),
}
RPC_TIMEOUT_SECONDS = 20
PROBE_TIMEOUT_SECONDS = 15
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,199}$")
AGENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
EFFORT_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
PERSONAL_MANAGED_ROLE_RE = re.compile(
    r"^codex_orchestration_(?:executor|advisor|planner|designer)_[0-9a-f]{12}$"
)
CUSTOM_AGENT_MANAGED_MARKER = (
    "# Managed by codex-orchestration. Standalone custom agent v2."
)
MISSING = object()


class ConfigurationError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Manage a persistent Codex multi-agent routing policy. The model "
            "selected for each task remains the root orchestrator."
        )
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--status", action="store_true")
    action.add_argument(
        "--repair",
        action="store_true",
        help=(
            "Restore only drifted plugin-managed mode/usage hints from valid "
            "saved state after a preview."
        ),
    )
    action.add_argument("--disable", action="store_true")
    parser.add_argument(
        "--require-effective",
        action="store_true",
        help=(
            "With --status, return 1 unless the policy is installed, effective, "
            "client-compatible, complete, and free of unavailable or orphaned roles."
        ),
    )

    executor = parser.add_mutually_exclusive_group()
    executor.add_argument(
        "--executor-model",
        help="Persistent 0.10 setup requires gpt-5.6-luna.",
    )
    executor.add_argument(
        "--executor-agent",
        help="Legacy input retained for validation; 0.10 persistent setup rejects it.",
    )
    parser.add_argument(
        "--executor-effort",
        default="auto",
        help="Persistent 0.10 setup requires max; auto resolves to max for Luna.",
    )
    executor_fallback = parser.add_mutually_exclusive_group()
    executor_fallback.add_argument(
        "--executor-fallback-model",
        help="Exact direct model ID to retry once after an eligible executor lookup failure.",
    )
    executor_fallback.add_argument(
        "--clear-executor-fallback",
        action="store_true",
        help="Remove the saved executor fallback during setup.",
    )
    parser.add_argument(
        "--executor-fallback-effort",
        default="auto",
        help="Exact supported fallback effort, or auto (resolved to the catalog default).",
    )

    planner = parser.add_mutually_exclusive_group()
    planner.add_argument("--planner-model", help="Optional exact planner model ID.")
    planner.add_argument("--planner-agent", help="Optional loaded planner agent name.")
    planner.add_argument(
        "--planner-fable",
        action="store_true",
        help="Use the bundled Claude Fable 5 planner through Claude Code.",
    )
    planner.add_argument(
        "--planner-opus",
        action="store_true",
        help="Use the bundled Claude Opus 5 planner through Claude Code.",
    )
    parser.add_argument(
        "--planner-effort",
        default="auto",
        help="Exact supported planner effort, or auto.",
    )

    advisor = parser.add_mutually_exclusive_group()
    advisor.add_argument("--advisor-model", help="Optional exact advisor model ID.")
    advisor.add_argument("--advisor-agent", help="Optional loaded advisor agent name.")
    advisor.add_argument(
        "--advisor-fable",
        action="store_true",
        help="Use the bundled Claude Fable 5 advisor through Claude Code.",
    )
    advisor.add_argument(
        "--advisor-opus",
        action="store_true",
        help="Use the bundled Claude Opus 5 advisor through Claude Code.",
    )
    parser.add_argument(
        "--advisor-effort",
        default="auto",
        help="Exact supported advisor effort, or auto.",
    )

    parser.add_argument("--designer-model", help="Optional exact designer model ID.")
    parser.add_argument(
        "--designer-effort",
        default="auto",
        help="Exact supported designer effort, or auto.",
    )

    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument(
        "--compat-bin",
        action="append",
        default=[],
        help="Additional Codex binary sharing this user config; repeat as needed.",
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        help="Override CODEX_HOME (primarily for isolated validation).",
    )
    parser.add_argument(
        "--replace-existing-policy",
        action="store_true",
        help="Replace user-authored v2 hint text and remember it for disable.",
    )
    parser.add_argument(
        "--allow-incompatible-client",
        action="store_true",
        help="Proceed even though another detected Codex binary rejects this policy.",
    )
    parser.add_argument(
        "--confirm-unlisted-models",
        action="store_true",
        help="Use exact model IDs confirmed by the active host when model/list is unavailable.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply after preview.")
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    if args.require_effective and not args.status:
        raise ConfigurationError("--require-effective requires --status.")
    if args.status and args.apply:
        raise ConfigurationError("--status cannot be combined with --apply.")
    seat_settings = any(
        (
            args.executor_model,
            args.executor_agent,
            args.executor_fallback_model,
            args.clear_executor_fallback,
            args.planner_model,
            args.planner_agent,
            args.planner_fable,
            args.planner_opus,
            args.advisor_model,
            args.advisor_agent,
            args.advisor_fable,
            args.advisor_opus,
            args.designer_model,
            args.executor_effort != "auto",
            args.executor_fallback_effort != "auto",
            args.planner_effort != "auto",
            args.advisor_effort != "auto",
            args.designer_effort != "auto",
        )
    )
    for action, selected in (
        ("--status", args.status),
        ("--repair", args.repair),
        ("--disable", args.disable),
    ):
        if selected and seat_settings:
            raise ConfigurationError(f"{action} does not accept seat settings.")
    if args.repair and (
        args.replace_existing_policy or args.confirm_unlisted_models
    ):
        raise ConfigurationError(
            "--repair cannot be combined with setup replacement or model controls."
        )
    if not args.status and not args.repair and not args.disable and not (
        args.executor_model or args.executor_agent
    ):
        raise ConfigurationError(
            "Setup requires --executor-model gpt-5.6-luna at max. Advisor omission "
            "means none. Designer omission means none."
        )
    if args.executor_agent and args.executor_effort != "auto":
        raise ConfigurationError(
            "A custom executor agent owns its effort; omit --executor-effort."
        )
    if args.executor_fallback_effort != "auto" and not args.executor_fallback_model:
        raise ConfigurationError(
            "--executor-fallback-effort requires --executor-fallback-model."
        )
    if args.executor_fallback_model and not args.executor_model:
        raise ConfigurationError(
            "An executor fallback requires a direct --executor-model primary."
        )
    if (
        args.executor_fallback_model
        and args.executor_model == args.executor_fallback_model
    ):
        raise ConfigurationError(
            "Executor fallback must differ from the primary executor model."
        )
    if args.planner_agent and args.planner_effort != "auto":
        raise ConfigurationError(
            "A custom planner agent owns its effort; omit --planner-effort."
        )
    if args.advisor_agent and args.advisor_effort != "auto":
        raise ConfigurationError(
            "A custom advisor agent owns its effort; omit --advisor-effort."
        )
    if args.planner_fable:
        normalize_fable_effort(args.planner_effort)
    if args.advisor_fable:
        normalize_fable_effort(args.advisor_effort)
    if args.planner_opus:
        normalize_opus_effort(args.planner_effort)
    if args.advisor_opus:
        normalize_opus_effort(args.advisor_effort)
    if sum(
        bool(selected)
        for selected in (
            args.planner_fable,
            args.planner_opus,
            args.advisor_fable,
            args.advisor_opus,
        )
    ) > 1:
        raise ConfigurationError(
            "Planner and Advisor routes must be distinct; configure at most one "
            "bundled Claude subscription seat."
        )
    for label, value, pattern in (
        ("executor model", args.executor_model, MODEL_RE),
        ("executor fallback model", args.executor_fallback_model, MODEL_RE),
        ("planner model", args.planner_model, MODEL_RE),
        ("advisor model", args.advisor_model, MODEL_RE),
        ("designer model", args.designer_model, MODEL_RE),
        ("executor agent", args.executor_agent, AGENT_RE),
        ("planner agent", args.planner_agent, AGENT_RE),
        ("advisor agent", args.advisor_agent, AGENT_RE),
    ):
        if value is not None and not pattern.fullmatch(value):
            raise ConfigurationError(f"Invalid {label}: {value!r}.")
        if "model" in label and value in {FABLE_MODEL, OPUS_MODEL}:
            raise ConfigurationError(
                f"{label.title()} {value!r} is a reserved Claude model ID; "
                "select its bundled sealed route instead."
            )
    for label, value in (
        ("executor effort", args.executor_effort),
        ("executor fallback effort", args.executor_fallback_effort),
        ("planner effort", args.planner_effort),
        ("advisor effort", args.advisor_effort),
        ("designer effort", args.designer_effort),
    ):
        if value != "auto" and not EFFORT_RE.fullmatch(value):
            raise ConfigurationError(f"Invalid {label}: {value!r}.")
    setup_requested = not (args.status or args.repair or args.disable)
    if setup_requested and (
        args.executor_model != ROUTINE_MODEL
        or args.executor_effort not in {"auto", LANE_EFFORT}
    ):
        raise ConfigurationError(
            "Version 0.10 persistent setup requires the exact routine Executor "
            f"{ROUTINE_MODEL}@{LANE_EFFORT}. Arbitrary and custom Executor routes "
            "remain task-local; existing saved routes are available only through "
            "status, repair, and disable."
        )


def normalize_fable_effort(value: str) -> str:
    """Return the Claude CLI effort for a user-facing Fable effort label."""

    requested = FABLE_DEFAULT_EFFORT if value == "auto" else value
    effective = FABLE_EFFORT_ALIASES.get(requested, requested)
    if effective not in FABLE_EFFORTS:
        supported = ", ".join((*FABLE_EFFORT_CHOICES, *FABLE_EFFORT_ALIASES))
        raise ConfigurationError(
            f"Claude Fable 5 effort must be one of: {supported}."
        )
    return effective


def normalize_opus_effort(value: str) -> str:
    """Return one exact documented Claude Opus 5 effort."""

    requested = OPUS_DEFAULT_EFFORT if value == "auto" else value
    if requested not in OPUS_EFFORTS:
        supported = ", ".join(sorted(OPUS_EFFORTS))
        raise ConfigurationError(
            f"Claude Opus 5 effort must be one of: {supported}."
        )
    return requested


def resolve_binary(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.parent != Path(".") or os.sep in value:
        if not candidate.is_file():
            raise ConfigurationError(f"Codex binary does not exist: {candidate}")
        return candidate.resolve()
    found = shutil.which(value)
    if not found:
        raise ConfigurationError(f"Codex binary is not on PATH: {value}")
    return Path(found).resolve()


def binary_version(binary: Path) -> str:
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigurationError(f"Could not run {binary}: {exc}") from exc
    output = result.stdout.strip()
    return output or f"exit {result.returncode}"


def supports_native_policy(binary: Path) -> tuple[bool, str]:
    """Capability-detect the structured field without reading the user's config."""

    with tempfile.TemporaryDirectory(prefix="codex-orchestration-probe-") as home:
        env = os.environ.copy()
        env["CODEX_HOME"] = home
        try:
            result = subprocess.run(
                [
                    str(binary),
                    "-c",
                    "features.multi_agent_v2.hide_spawn_agent_metadata=false",
                    "-c",
                    (
                        "features.multi_agent_v2.tool_namespace="
                        f'"{ROUTING_TOOL_NAMESPACE}"'
                    ),
                    "-c",
                    (
                        "features.multi_agent_v2.multi_agent_mode_hint_text="
                        f'"{PROBE_VALUE}"'
                    ),
                    "-c",
                    (
                        "features.multi_agent_v2.usage_hint_text="
                        f'"{PROBE_VALUE}"'
                    ),
                    "features",
                    "list",
                ],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=PROBE_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
    if result.returncode == 0:
        return True, "supported"
    detail = " ".join(result.stdout.strip().split())
    return False, (detail[:240] or f"exit {result.returncode}")


def discover_compatibility_binaries(
    target: Path, explicit: list[str]
) -> list[Path]:
    candidates: list[Path] = [target]
    for value in explicit:
        candidates.append(resolve_binary(value))
    path_codex = shutil.which("codex")
    if path_codex:
        candidates.append(Path(path_codex).resolve())
    desktop = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
    if desktop.is_file():
        candidates.append(desktop.resolve())
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        real = candidate.resolve()
        if real not in seen:
            seen.add(real)
            unique.append(real)
    return unique


class AppServer:
    def __init__(
        self,
        binary: Path,
        codex_home: Path | None,
        environment: dict[str, str] | None = None,
    ) -> None:
        env = os.environ.copy() if environment is None else environment.copy()
        if codex_home is not None:
            resolved_home = codex_home.expanduser().absolute()
            resolved_home.mkdir(parents=True, exist_ok=True)
            env["CODEX_HOME"] = str(resolved_home)
        self._stderr = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        try:
            self._process = subprocess.Popen(
                [str(binary), "app-server", "--stdio"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=env,
            )
        except OSError as exc:
            self._stderr.close()
            raise ConfigurationError(f"Could not start Codex App Server: {exc}") from exc
        if self._process.stdin is None or self._process.stdout is None:
            self.close()
            raise ConfigurationError("Codex App Server did not expose stdio.")
        self._stdin = self._process.stdin
        self._stdout = self._process.stdout
        self._messages: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
        self._pending: dict[int, dict[str, Any]] = {}
        self._next_id = 0
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        try:
            response = self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "codex_orchestration_installer",
                        "title": "Codex Orchestration Installer",
                        "version": "0.10.3",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            self.codex_home = Path(response["codexHome"])
            self.config_path = self.codex_home / "config.toml"
            self.notify("initialized")
        except BaseException:
            self.close()
            raise

    def _read_loop(self) -> None:
        try:
            for line in self._stdout:
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._messages.put(
                        ConfigurationError(f"Invalid App Server JSON: {exc}")
                    )
                    continue
                if isinstance(message, dict):
                    self._messages.put(message)
            self._messages.put(EOFError("Codex App Server closed stdout."))
        except BaseException as exc:  # pragma: no cover - defensive reader boundary
            self._messages.put(exc)

    def _send(self, message: dict[str, Any]) -> None:
        try:
            self._stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            self._stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ConfigurationError(
                f"Codex App Server closed its input: {exc}. {self.stderr_excerpt()}"
            ) from exc

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send({"method": method, "id": request_id, "params": params})
        deadline = time.monotonic() + RPC_TIMEOUT_SECONDS
        while True:
            if request_id in self._pending:
                message = self._pending.pop(request_id)
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ConfigurationError(
                        f"Timed out waiting for App Server method {method}. "
                        f"{self.stderr_excerpt()}"
                    )
                try:
                    item = self._messages.get(timeout=remaining)
                except queue.Empty as exc:
                    raise ConfigurationError(
                        f"Timed out waiting for App Server method {method}."
                    ) from exc
                if isinstance(item, BaseException):
                    raise ConfigurationError(
                        f"App Server stopped during {method}: {item}. "
                        f"{self.stderr_excerpt()}"
                    )
                message = item
                message_id = message.get("id")
                if not isinstance(message_id, int):
                    continue
                if message_id != request_id:
                    self._pending[message_id] = message
                    continue
            if "error" in message:
                error = message.get("error") or {}
                detail = error.get("message", "unknown App Server error")
                data = error.get("data")
                if isinstance(data, dict) and data.get("config_write_error_code"):
                    detail = f"{detail} ({data['config_write_error_code']})"
                raise ConfigurationError(f"{method} failed: {detail}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise ConfigurationError(f"{method} returned an invalid result.")
            return result

    def notify(self, method: str) -> None:
        self._send({"method": method})

    def stderr_excerpt(self) -> str:
        # Seeking a file descriptor while the child is still writing can move
        # the shared file offset. The process status is enough during a timeout;
        # collect stderr only after the child has stopped.
        if self._process.poll() is None:
            return ""
        try:
            self._stderr.flush()
            self._stderr.seek(0)
            value = " ".join(self._stderr.read().strip().split())
            self._stderr.seek(0, os.SEEK_END)
        except OSError:
            return ""
        return value[-1000:]

    def close(self) -> None:
        process = getattr(self, "_process", None)
        if process is not None:
            stdin = process.stdin
            if stdin is not None and not stdin.closed:
                try:
                    stdin.close()
                except OSError:
                    pass
            if process.poll() is None:
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
        stderr = getattr(self, "_stderr", None)
        if stderr is not None:
            stderr.close()

    def __enter__(self) -> "AppServer":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _user_layer(read_result: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    layers = read_result.get("layers")
    if not isinstance(layers, list):
        raise ConfigurationError("config/read did not include configuration layers.")
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        name = layer.get("name")
        if (
            isinstance(name, dict)
            and name.get("type") == "user"
            and name.get("profile") is None
        ):
            config = layer.get("config")
            if not isinstance(config, dict):
                config = {}
            version = layer.get("version")
            return config, version if isinstance(version, str) else None
    return {}, None


def nested_get(config: dict[str, Any], *segments: str) -> Any:
    current: Any = config
    for segment in segments:
        if not isinstance(current, dict) or segment not in current:
            return MISSING
        current = current[segment]
    return current


def snapshot(value: Any, *, known: bool = True) -> dict[str, Any]:
    if not known:
        return {"known": False, "present": False}
    if value is MISSING:
        return {"known": True, "present": False}
    return {"known": True, "present": True, "value": value}


def snapshot_edit(key_path: str, saved: dict[str, Any]) -> dict[str, Any] | None:
    if not saved.get("known"):
        return None
    return {
        "keyPath": key_path,
        "value": saved.get("value") if saved.get("present") else None,
        "mergeStrategy": "replace",
    }


def fable_key_path(server: str) -> str:
    return (
        f"plugins.{json.dumps(PLUGIN_ID)}.mcp_servers."
        f"{json.dumps(server)}.enabled"
    )


def validate_planning_routes(
    planner: dict[str, Any] | None,
    advisor: dict[str, Any] | None,
) -> None:
    """Reject routes that cannot provide independent planning and review seats."""

    if planner is None or advisor is None:
        return
    planner_kind = planner.get("kind")
    advisor_kind = advisor.get("kind")
    subscription_kinds = {"fable", "claude_subscription"}
    identical = (
        planner_kind == advisor_kind == "model"
        and planner.get("model") == advisor.get("model")
    ) or (
        planner_kind == advisor_kind == "agent"
        and planner.get("agent") == advisor.get("agent")
    ) or (
        planner_kind in subscription_kinds and advisor_kind in subscription_kinds
    )
    if identical:
        raise ConfigurationError(
            "Planner and Advisor routes must be distinct (different direct model IDs, "
            "different custom-agent names, and at most one bundled Claude "
            "subscription seat)."
        )


def _read_state(path: Path) -> dict[str, Any] | None:
    state, _ = _read_state_with_revision(path)
    return state


def _read_state_with_revision(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read one secure state-file snapshot and its byte-exact revision digest."""

    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        raise ConfigurationError(f"Could not inspect routing state {path}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ConfigurationError(f"Routing state is not a regular file: {path}")
    if info.st_nlink != 1:
        raise ConfigurationError(f"Routing state has multiple hard links: {path}")
    try:
        payload = path.read_bytes()
        state = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Could not read routing state {path}: {exc}") from exc
    try:
        return validate_routing_state(state), hashlib.sha256(payload).hexdigest()
    except RoutingStateError as exc:
        raise ConfigurationError("Saved routing state is invalid.") from exc


def _validate_state_config(state: dict[str, Any] | None, config_path: Path) -> None:
    if state is None:
        return
    saved_path = state.get("config_file")
    if not isinstance(saved_path, str):
        raise ConfigurationError("Routing state is missing its config path.")
    if Path(saved_path).expanduser().resolve() != config_path.expanduser().resolve():
        raise ConfigurationError(
            "Routing state belongs to a different Codex config file; refusing to use it."
        )


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        _read_state(path)
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temporary)
    try:
        fchmod = getattr(os, "fchmod", None)
        if callable(fchmod):
            fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        temp_path.unlink(missing_ok=True)


@contextmanager
def _state_lock(path: Path):
    """Serialize state CAS operations between installer processes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f".{path.name}.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        elif msvcrt is not None:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:  # pragma: no cover - supported desktop platforms expose one backend
            raise ConfigurationError(
                "Routing-state compare-and-swap has no supported file-lock backend."
            )
        locked = True
        yield
    finally:
        if locked and fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        elif locked and msvcrt is not None:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        os.close(descriptor)


def _require_state_lock_backend() -> None:
    """Fail before config mutation on an unsupported host."""

    if fcntl is None and msvcrt is None:
        raise ConfigurationError(
            "Routing-state compare-and-swap has no supported file-lock backend."
        )


def _write_state_cas(
    path: Path,
    state: dict[str, Any],
    expected_revision: str | None,
) -> str:
    """Persist state only if the original byte snapshot is still current."""

    with _state_lock(path):
        _, current_revision = _read_state_with_revision(path)
        if current_revision != expected_revision:
            raise ConfigurationError(
                "Saved routing state changed concurrently; its valid replacement was preserved."
            )
        _write_state(path, state)
        _, written_revision = _read_state_with_revision(path)
        if written_revision is None:  # pragma: no cover - impossible after successful replace
            raise ConfigurationError("Routing state disappeared during compare-and-swap.")
        return written_revision


def _remove_state(path: Path) -> None:
    if not path.exists():
        return
    _read_state(path)
    path.unlink()
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _remove_state_cas(path: Path, expected_revision: str | None) -> None:
    """Remove only the exact state snapshot observed before the config write."""

    with _state_lock(path):
        _, current_revision = _read_state_with_revision(path)
        if current_revision != expected_revision:
            raise ConfigurationError(
                "Saved routing state changed concurrently; its valid replacement was preserved."
            )
        if current_revision is not None:
            _remove_state(path)


def _agent_files_with_name(directory: Path, name: str) -> list[Path]:
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise ConfigurationError(f"Unsafe custom-agent directory: {directory}")
    matches: list[Path] = []
    for path in sorted(directory.glob("*.toml")):
        if path.is_symlink() or not path.is_file():
            raise ConfigurationError(f"Unsafe custom-agent path: {path}")
        try:
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ConfigurationError(f"Could not inspect custom agent {path}: {exc}") from exc
        if parsed.get("name") == name:
            for field in ("description", "model", "developer_instructions"):
                if not isinstance(parsed.get(field), str) or not parsed[field]:
                    raise ConfigurationError(
                        f"Custom agent {path} has no valid {field!r} field."
                    )
            matches.append(path)
    return matches


def _project_agent_matches(
    workspace: Path,
    personal_agents: Path,
    name: str,
) -> list[Path]:
    matches: list[Path] = []
    personal_real = personal_agents.resolve()
    for root in (workspace, *workspace.parents):
        directory = root / ".codex" / "agents"
        if directory.is_symlink():
            raise ConfigurationError(f"Unsafe custom-agent directory: {directory}")
        if directory.exists() and directory.resolve() == personal_real:
            continue
        matches.extend(_agent_files_with_name(directory, name))
    return matches


def verify_agent_routes(
    codex_home: Path,
    workspace: Path,
    executor: dict[str, Any],
    planner: dict[str, Any] | None,
    advisor: dict[str, Any] | None,
) -> list[Path]:
    """Require personal role files and reject current-project shadowing."""

    verified: list[Path] = []
    personal_agents = codex_home / "agents"
    for label, route in (
        ("Executor", executor),
        ("Planner", planner),
        ("Advisor", advisor),
    ):
        if route is None or route.get("kind") != "agent":
            continue
        name = route.get("agent")
        if not isinstance(name, str):
            raise ConfigurationError(f"{label} custom-agent route has an invalid name.")
        personal = _agent_files_with_name(personal_agents, name)
        if len(personal) != 1:
            raise ConfigurationError(
                f"{label} custom-agent route {name!r} must resolve to exactly one "
                f"personal file under {personal_agents}; found {len(personal)}."
            )
        project = _project_agent_matches(workspace, personal_agents, name)
        if project:
            locations = ", ".join(str(path) for path in project)
            raise ConfigurationError(
                f"{label} personal agent {name!r} is shadowed by a project role: "
                f"{locations}. Use collision-resistant personal route names or remove "
                "the project collision."
            )
        verified.append(personal[0])
    return verified


def load_models(app: AppServer) -> dict[str, dict[str, Any]]:
    models: dict[str, dict[str, Any]] = {}
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"includeHidden": True, "limit": 100}
        if cursor is not None:
            params["cursor"] = cursor
        result = app.request("model/list", params)
        for item in result.get("data", []):
            if isinstance(item, dict) and isinstance(item.get("model"), str):
                models[item["model"]] = item
        next_cursor = result.get("nextCursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            return models
        cursor = next_cursor


def resolve_model_effort(
    label: str,
    model: str,
    effort: str,
    catalog: dict[str, dict[str, Any]],
    confirm_unlisted: bool,
) -> str:
    item = catalog.get(model)
    if item is None:
        if not confirm_unlisted:
            raise ConfigurationError(
                f"{label} model {model!r} is not in this App Server model catalog."
            )
        if effort == "auto":
            raise ConfigurationError(
                f"{label} effort must be explicit when using an unlisted model."
            )
        return effort
    supported = {
        option.get("reasoningEffort")
        for option in item.get("supportedReasoningEfforts", [])
        if isinstance(option, dict)
    }
    resolved = item.get("defaultReasoningEffort") if effort == "auto" else effort
    if not isinstance(resolved, str) or not resolved:
        raise ConfigurationError(f"Could not resolve {label} effort for {model!r}.")
    if supported and resolved not in supported:
        values = ", ".join(sorted(value for value in supported if isinstance(value, str)))
        raise ConfigurationError(
            f"{label} effort {resolved!r} is not supported by {model!r}; choose {values}."
        )
    return resolved


def select_fable_server() -> str:
    """Select the historical launcher ID shared by bundled Claude routes."""

    for server, (launcher, prefix) in FABLE_SERVERS.items():
        executable = shutil.which(launcher)
        if not executable:
            continue
        try:
            result = subprocess.run(
                [executable, *prefix, "--version"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=PROBE_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        match = re.search(r"Python\s+(\d+)\.(\d+)", result.stdout)
        if result.returncode == 0 and match and tuple(map(int, match.groups())) >= (3, 11):
            return server
    raise ConfigurationError(
        "Bundled Claude planning routes require a Python 3.11+ launcher named "
        "python3, python, "
        "or py. Install one and retry."
    )


def _parse_claude_version(output: str) -> tuple[int, int, int]:
    match = re.fullmatch(
        (
            r"[ \t\r\n]*"
            r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
            r" \(Claude Code\)"
            r"[ \t\r\n]*"
        ),
        output,
    )
    if match is None:
        raise ConfigurationError("Claude Code returned an unparseable version.")
    try:
        return tuple(map(int, match.groups()))
    except ValueError as exc:
        raise ConfigurationError(
            "Claude Code returned an unparseable version."
        ) from exc


def verify_claude_prerequisites(model: str, effort: str) -> dict[str, str]:
    display_name = (
        "Claude Fable 5" if model == FABLE_MODEL else "Claude Opus 5"
        if model == OPUS_MODEL
        else None
    )
    if display_name is None:
        raise ConfigurationError("The bundled Claude model is not sealed.")
    try:
        from fable_advisor_mcp import (
            AdvisorError,
            check_claude_auth,
            resolve_claude,
            sanitized_environment,
        )
    except ImportError as exc:  # pragma: no cover - corrupt package
        raise ConfigurationError("The bundled Claude planning bridge is missing.") from exc
    try:
        claude = resolve_claude()
        auth = check_claude_auth(claude)
        environment = sanitized_environment()
        version_result = (
            subprocess.run(
                [str(claude), "--version"],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=PROBE_TIMEOUT_SECONDS,
                check=False,
            )
            if model == OPUS_MODEL
            else None
        )
        help_result = subprocess.run(
            [str(claude), "--help"],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (AdvisorError, OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigurationError(str(exc)) from exc
    installed_version: tuple[int, int, int] | None = None
    if version_result is not None:
        if version_result.returncode != 0:
            raise ConfigurationError(
                f"Claude Code version check exited with {version_result.returncode}."
            )
        installed_version = _parse_claude_version(version_result.stdout)
    if (
        model == OPUS_MODEL
        and installed_version is not None
        and installed_version < OPUS_MIN_CLAUDE_VERSION
    ):
        required = ".".join(map(str, OPUS_MIN_CLAUDE_VERSION))
        observed = ".".join(map(str, installed_version))
        raise ConfigurationError(
            f"Claude Opus 5 requires Claude Code {required} or newer; "
            f"found {observed}."
        )
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
    advertised_options = set(
        re.findall(
            r"(?<![A-Za-z0-9_-])--[A-Za-z0-9][A-Za-z0-9-]*(?![A-Za-z0-9_-])",
            help_result.stdout,
        )
    )
    missing = [flag for flag in required if flag not in advertised_options]
    if help_result.returncode != 0 or missing:
        detail = ", ".join(missing) if missing else f"exit {help_result.returncode}"
        raise ConfigurationError(
            f"Claude Code is too old for the bundled planning bridge ({detail}); "
            "update it."
        )
    effort_match = re.search(
        r"--effort\s+<level>.*?\((low[^)]*)\)",
        help_result.stdout,
        flags=re.DOTALL,
    )
    advertised_efforts = (
        set(re.findall(r"[a-z]+", effort_match.group(1)))
        if effort_match is not None
        else set()
    )
    if effort not in advertised_efforts:
        effort_label = "Fable" if model == FABLE_MODEL else display_name
        raise ConfigurationError(
            f"Claude Code does not advertise {effort_label} effort {effort!r}; "
            "update Claude Code or choose a supported effort."
        )
    result = {
        "claude": str(claude),
        **auth,
    }
    if installed_version is not None:
        result["version"] = ".".join(map(str, installed_version))
    return result


def verify_fable_prerequisites(effort: str) -> dict[str, str]:
    """Backward-compatible prerequisite helper for existing integrations."""

    return verify_claude_prerequisites(FABLE_MODEL, effort)


def _route_summary(route: dict[str, Any]) -> str:
    if route["kind"] == "agent":
        return f"custom agent {route['agent']}"
    if route["kind"] == "fable":
        return f"Claude Fable 5 {route['effort']}"
    if route["kind"] == "claude_subscription":
        return f"Claude Opus 5 {route['effort']}"
    return f"{route['model']}@{route['effort']}"


def _managed_personal_roles(codex_home: Path) -> tuple[dict[str, Path], list[str]]:
    """Find only collision-resistant v0.4 personal roles owned by this plugin."""

    roles: dict[str, Path] = {}
    issues: list[str] = []
    directory = codex_home / "agents"
    if not directory.exists() and not directory.is_symlink():
        return roles, issues
    if directory.is_symlink() or not directory.is_dir():
        return roles, [f"managed-role directory is unsafe: {directory}"]
    for path in sorted(directory.glob("*.toml")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(f"could not inspect {path}: {exc}")
            continue
        if not content.startswith(CUSTOM_AGENT_MANAGED_MARKER + "\n"):
            continue
        try:
            parsed = tomllib.loads(content)
        except tomllib.TOMLDecodeError as exc:
            issues.append(f"managed role is malformed: {path}: {exc}")
            continue
        name = parsed.get("name")
        if not isinstance(name, str) or not PERSONAL_MANAGED_ROLE_RE.fullmatch(name):
            continue
        if name in roles:
            issues.append(f"managed role {name!r} is duplicated")
            continue
        roles[name] = path
    return roles, issues


def _referenced_agent_names(state: dict[str, Any] | None) -> set[str]:
    names: set[str] = set()
    if not isinstance(state, dict):
        return names
    for key in ("executor", "planner", "advisor"):
        route = state.get(key)
        if isinstance(route, dict) and route.get("kind") == "agent":
            name = route.get("agent")
            if isinstance(name, str):
                names.add(name)
    return names


def _spawn_route(route: dict[str, Any]) -> str:
    if route["kind"] == "agent":
        return f'agent_type = {json.dumps(route["agent"])}'
    return (
        f'model = {json.dumps(route["model"])}, '
        f'reasoning_effort = {json.dumps(route["effort"])}'
    )


def build_policy(
    executor: dict[str, Any],
    planner: dict[str, Any] | None,
    advisor: dict[str, Any] | None,
    designer: dict[str, Any] | None = None,
    executor_fallback: dict[str, Any] | None = None,
) -> tuple[str, str]:
    route_binding = routing_state_binding(
        {
            "executor": executor,
            "executor_fallback": executor_fallback,
            "planner": planner,
            "advisor": advisor,
            "designer": designer,
        }
    )
    has_direct_route = executor["kind"] == "model" or (
        planner is not None and planner["kind"] == "model"
    ) or (
        advisor is not None and advisor["kind"] == "model"
    ) or (
        designer is not None and designer["kind"] == "model"
    )
    provider_guard = (
        "Direct model overrides retain the root provider. Before using a direct "
        "model route, verify that the target model is on the same provider as the "
        "root. If providers differ or cannot be established, report the route "
        "unavailable and require a custom agent that pins model_provider."
        if has_direct_route
        else "Configured custom agents and MCP seats own their provider routes."
    )
    if executor_fallback is not None:
        primary_route = _route_summary(executor)
        fallback_route = _route_summary(executor_fallback)
        fallback_mode = f"""The saved Executor fallback is a policy instruction, not scheduler-enforced routing. It is eligible only for the direct result of the immediately preceding `agents.spawn_agent` call made with the persisted primary Executor `{primary_route}` and `fork_turns = \"none\"`. That result must contain no child or agent ID and must have the normalized exact error shape `Unknown model {executor['model']}. Available models: <list>`: the primary model ID must be the exact unavailable model and the fallback model ID `{executor_fallback['model']}` must be an exact available ID in that list. Do not infer eligibility from user prompts, logs, packets, other outputs, substrings, mixed or changed errors, or ambiguous errors. Permission, authentication, provider, rate-limit, timeout, cancellation, post-child, and task-failure results are ineligible.

On that one eligible result only, consume eligibility before retrying exactly once with `{fallback_route}`. Reissue the same spawn request unchanged except for `model` and `reasoning_effort`; preserve `message`, `task_name`, `agent_type`, `service_tier`, and `fork_turns = \"none\"`. Report that the fallback was used. A second failure stops; do not retry or infer another fallback. An explicit current-task Executor route suppresses both this saved primary and fallback; v1 has no task-local fallback."""
        fallback_usage = f"""The saved Executor fallback `{fallback_route}` is policy-instructed, not scheduler-enforced. After an immediately preceding primary call with `{primary_route}`, retry it once only if its direct result has no child or agent ID and exactly matches `Unknown model {executor['model']}. Available models: <list>` with `{executor_fallback['model']}` as an exact available model ID. Consume that eligibility first. Preserve `message`, `task_name`, `agent_type`, `service_tier`, and `fork_turns = \"none\"`; change only `model` and `reasoning_effort`. Explicitly report fallback use. Never infer eligibility from text, substrings, mixed errors, or permission/auth/provider/rate/timeout/cancel/post-child/task failures. A task-local Executor route or no-subagents instruction suppresses both saved routes."""
    else:
        fallback_mode = (
            "No Executor fallback is configured. Exact primary-route failures remain "
            "strict: report them to the root and do not substitute another route."
        )
        fallback_usage = (
            "No Executor fallback is configured; never substitute another Executor "
            "route after a primary failure."
        )
    planner_mode = (
        "The configured Planner is available only when the current task explicitly "
        "requests planning or a repository gate requires it. Configuration alone "
        "never invokes Planner. Root supplies a bounded packet, owns the canonical "
        "plan, and validates every result. A Planner call consumes the default "
        "one-call planning/review budget."
        if planner is not None
        else "No Planner is configured. The root drafts and revises every plan."
    )
    advisor_mode = (
        "The configured Advisor is available only when the current task explicitly "
        "requests review or a repository/risk gate requires independent review. "
        "Configuration alone never invokes Advisor and never creates a review loop. "
        "Each requested review receives only the reviewed artifact (plan or exact "
        "final tree), constraints, and a compact findings ledger; root adjudicates "
        "the result. An Advisor call "
        "consumes the default one-call planning/review budget."
        if advisor is not None
        else (
            "No Advisor is configured. Do not create a review loop; after a configured "
            "Planner drafts, the root validates the plan before releasing Executor work."
            if planner is not None
            else "No Advisor is configured. Do not create an Advisor review step."
        )
    )
    designer_mode = (
        "After any required plan approval, the root may send bounded visual, UX, "
        "interaction, information-architecture, or design-system work to the "
        "configured Designer. The root supplies approved requirements, exact "
        "deliverables, constraints, and any owned design artifacts. Designer may "
        "edit only explicitly delegated design artifacts; otherwise it returns a "
        "design handoff. It does not revise the canonical plan, change implementation "
        "code, or release Executor. The root validates the handoff and decides what "
        "Executor receives."
        if designer is not None
        else (
            "No Designer is configured. The root owns design decisions or delegates "
            "them through ordinary bounded Executor work when useful."
        )
    )
    mode = f"""{MANAGED_MARKER}
{TWO_LANE_POLICY_MARKER}
This adds model routing to Codex's existing multi-agent flow; it is not a second scheduler.

{route_binding}

If you are the root task model, you are the orchestrator. Own intent, planning, architecture, decomposition, delegation, integration, review, final verification, and the user-facing answer. Codex still decides whether a plan or subagent helps, how many independent slices exist, and what can run safely in parallel. Keep simple, tightly coupled, context-heavy, or root-owned work with the root. Do not delegate merely to prove the policy is active.

{planner_mode}

{advisor_mode}

{designer_mode}

{fallback_mode}

The root owns planning, findings, validation, adjudication, and release to implementation. There is no automatic planning or review loop and no Finalizer seat.

Before implementation delegation, classify the task once. Keep trivial work in root. Apply a warm-root gate: if root already holds the implementation context, owned paths overlap dirty integration, or a cold child must rediscover several packages, keep the work in root. Use the configured Executor as the routine lane only for bounded, well-specified, low-risk work with a known change surface. File count is advisory, never a hard eligibility limit: a coherent mechanical or low-risk change in one module may remain Luna work even when it touches more than three files. A slice spanning database schema, migration, seed, API wiring, and tests is hard/state work even when bounded. Route by contract, state boundaries, ambiguity, and blast radius. Use the exact hard/risky lane `model = {HARD_MODEL!r}, reasoning_effort = {LANE_EFFORT!r}, fork_turns = "none"` for security, authentication, state, destructive behavior, migrations, concurrency, unclear legacy contracts, broad refactors, or other material ambiguity and blast radius. When uncertain, use the hard/risky lane. If Luna discovers hidden risk, stop, correct the packet, and make at most one Terra attempt; never run both lanes competitively or resend an unchanged prompt.

Give each worker one bounded packet with OBJECTIVE, OWNERSHIP, CONTRACTS, DONE WHEN, and VERIFY AND RETURN. Do not copy the full transcript, plan, logs, or files the worker can inspect. Every Luna packet must add FIRST ARTIFACT and READ BUDGET stop conditions: at most three batched discovery tool calls before the first edit or exact regression, and within 120 seconds create the smallest safe artifact or return BLOCKED. At that gate root inspects the owned-path diff before messaging or declaring a stall. With no artifact, request one checkpoint and allow at most 60 more seconds. With a partial artifact but no new artifact for 180 seconds, request one checkpoint, allow at most 60 more seconds, and stop the seat. Before interrupting snapshot the owned diff; after interrupting wait for terminal state, snapshot again, and reconcile every partial edit before root touches the same paths or claims no changes. The timing, read-call, and token limits are orchestration policy instructions and stop conditions, not host-enforced limits. Inspect every handoff, integrate it, and run final checks yourself.

Explicit user instructions win, including no-subagents and task-local seat overrides. Persistent and task-local Planner and Advisor routes must remain distinct: reject the same direct model ID, the same custom-agent name, or more than one bundled Claude subscription seat. This policy does not create or change a Goal, weaken approvals, alter permissions, or force a worker count.

Routine tasks use zero Planner or Advisor calls by default. Across all tasks, the default budget is at most one Planner-or-Advisor model call total, and only after an explicit current-task request or repository/risk gate. If exact final-tree review is required, reserve that call until the implementation and checks are complete and bind it to the exact tree or head. PLAN_REVISE or any finding does not authorize a second call: root fixes locally and asks the user before any model re-review needed to attest the changed tree. Only an explicit current-task instruction may enlarge this budget.

Planner and Advisor are policy-isolated, root-directed seats: they cannot contact each other, Designer, or Executors, spawn descendants, edit files, execute work, or release Executor. They return only to the root. Designer is also root-directed: it cannot contact Planner, Advisor, or Executor, spawn descendants, redesign the root plan, change implementation code, or release Executor. Designer may edit only explicitly delegated design artifacts. Bundled Claude MCP requests do not carry caller identity, so caller isolation is instruction-enforced even though the bridge itself disables tools and persistence. If you are a spawned child, stay inside the supplied packet, report only to the root, never call planning tools, and never spawn descendants. An Executor never redesigns the root plan or contacts Planner, Advisor, or Designer.
"""
    if planner is not None and planner["kind"] in {
        "fable",
        "claude_subscription",
    }:
        planner_hint = (
            "Only after an explicit current-task planning request or repository gate, "
            "call `create_plan` from MCP server "
            f"{json.dumps(planner['server'])}. This is a root tool call. Require "
            "PLAN_DRAFT and assign the canonical version. Under the default one-call "
            "budget root handles later revisions locally; call `revise_plan` only "
            "after the user explicitly authorizes a second model call."
        )
    elif planner is not None:
        planner_hint = (
            "Only after an explicit current-task planning request or repository gate, "
            "call this tool with "
            f"{_spawn_route(planner)}, fork_turns = \"none\". Send the complete "
            "self-contained packet for that round. Require PLAN_DRAFT initially; "
            "under the default one-call budget, root revises locally or asks the user "
            "before any second model call."
        )
    else:
        planner_hint = "No Planner route is configured; the root drafts and revises."
    if advisor is not None and advisor["kind"] in {
        "fable",
        "claude_subscription",
    }:
        advisor_hint = (
            "Only after an explicit current-task review request or repository/risk "
            "gate, call `review_plan` from MCP server "
            f"{json.dumps(advisor['server'])} with the round's self-contained packet. "
            "This is a read-only root tool call, not a spawned child. Require "
            "PLAN_APPROVED or PLAN_REVISE. PLAN_REVISE does not authorize an "
            "automatic second review; ask the user before another model call."
        )
    elif advisor is not None:
        advisor_hint = (
            "Only after an explicit current-task review request or repository/risk "
            "gate, call this tool with "
            f"{_spawn_route(advisor)}, fork_turns = \"none\". Send the complete "
            "review packet and require PLAN_APPROVED or PLAN_REVISE. PLAN_REVISE "
            "does not authorize an automatic second review; ask the user first."
        )
    else:
        advisor_hint = "No advisor route is configured."
    if designer is not None:
        designer_hint = (
            "For delegated design work, call this tool with "
            f"{_spawn_route(designer)}, fork_turns = \"none\". Send approved "
            "requirements, bounded deliverables, explicit design-artifact ownership, "
            "constraints, and the required handoff format."
        )
    else:
        designer_hint = "No Designer route is configured."
    usage = f"""{MANAGED_MARKER}
{TWO_LANE_POLICY_MARKER}
If you are the root task model, you are the orchestrator. Apply these routes only to children you decide to create.

{route_binding}

Classify before spawning. Keep trivial or warm-root work in root. File count is advisory, not a hard Luna limit: a coherent mechanical or low-risk change in one module may touch more than three files. Schema + migration + seed + API + tests is Terra/state work even when bounded; route by contract, state boundaries, ambiguity, and blast radius. For routine, bounded, well-specified, low-risk work that passes this gate, call this tool with {_spawn_route(executor)}, fork_turns = "none". For hard, ambiguous, or high-risk work, call it with model = "{HARD_MODEL}", reasoning_effort = "{LANE_EFFORT}", fork_turns = "none". When uncertain, use Terra. Send only the five-part bounded task packet; do not copy the full conversation. A Luna packet must require a first artifact within 120 seconds and no more than three batched discovery calls before it; otherwise return BLOCKED. Root must inspect and snapshot the owned diff before declaring a stall or interrupting, then wait for terminal state and reconcile partial edits before takeover. The timing, read-call, and token limits are orchestration policy instructions and stop conditions, not host-enforced limits.

Routine tasks use zero Planner or Advisor calls by default. Across all tasks, the default budget is at most one Planner-or-Advisor model call total after an explicit current-task request or repository/risk gate. Reserve it for an exact final-tree review when that gate is mandatory. PLAN_REVISE or any finding never authorizes a second call; root fixes locally and asks the user before model re-review. Only an explicit current-task instruction may enlarge this budget.

{fallback_usage}

{planner_hint}

{advisor_hint}

{designer_hint}

{provider_guard}

Never use fork_turns = "all" with model, reasoning_effort, or agent_type: a full-history fork inherits the root route and rejects those overrides. Never silently substitute the root model when an exact child route is unavailable. Report the unavailable route to the root. A user's explicit current-task model, effort, agent, or no-subagents instruction overrides this saved default; an explicit task-local Executor route suppresses both saved Executor routes. A task-local Planner and Advisor must still be distinct: reject the same direct model ID, the same custom-agent name, or more than one bundled Claude subscription seat.

If you are a spawned child, do not call this tool or create descendants. Finish only your assigned packet and return to the root.
"""
    return mode, usage


def _compatibility_report(
    binaries: list[Path], allow_incompatible: bool
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    incompatible: list[str] = []
    for binary in binaries:
        supported, detail = supports_native_policy(binary)
        version = binary_version(binary)
        results.append(
            {
                "path": str(binary),
                "version": version,
                "supported": supported,
                "detail": detail,
            }
        )
        state = "supports native policy" if supported else f"incompatible: {detail}"
        print(f"Client: {binary} ({version}) — {state}")
        if not supported:
            incompatible.append(f"{binary} ({version})")
    if incompatible and not allow_incompatible:
        joined = ", ".join(incompatible)
        raise ConfigurationError(
            "Native setup would make the shared config unreadable to: "
            f"{joined}. Update those clients, use the per-task skill fallback, or "
            "repeat only after explicit approval with --allow-incompatible-client."
        )
    return results


def _current_values(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "feature": nested_get(config, "features", "multi_agent_v2"),
        "mode": nested_get(
            config, "features", "multi_agent_v2", "multi_agent_mode_hint_text"
        ),
        "usage": nested_get(
            config, "features", "multi_agent_v2", "usage_hint_text"
        ),
        "metadata": nested_get(
            config, "features", "multi_agent_v2", "hide_spawn_agent_metadata"
        ),
        "namespace": nested_get(
            config, "features", "multi_agent_v2", "tool_namespace"
        ),
        "mcp": {
            server: nested_get(
                config,
                "plugins",
                PLUGIN_ID,
                "mcp_servers",
                server,
                "enabled",
            )
            for server in FABLE_SERVERS
        },
    }


def _is_managed(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(MANAGED_MARKER)


def _is_two_lane_policy(current: dict[str, Any]) -> bool:
    return all(
        isinstance(current[key], str)
        and TWO_LANE_POLICY_MARKER in current[key]
        for key in ("mode", "usage")
    )


def _strict_equal(left: Any, right: Any) -> bool:
    """Compare config values without Python's bool/integer equivalence."""

    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _strict_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _strict_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _managed_matches(state: dict[str, Any], current: dict[str, Any]) -> bool:
    managed = state.get("managed")
    base_matches = (
        isinstance(managed, dict)
        and current["mode"] == managed.get("mode")
        and current["usage"] == managed.get("usage")
        and current["metadata"] is False
        and managed.get("namespace") == ROUTING_TOOL_NAMESPACE
        and current["namespace"] == ROUTING_TOOL_NAMESPACE
    )
    if not base_matches:
        return False
    managed_mcp = managed.get("mcp")
    if managed_mcp is not None and not all(
        _strict_equal(current["mcp"].get(server, MISSING), enabled)
        for server, enabled in managed_mcp.items()
    ):
        return False
    if isinstance(state.get("scalar_origin"), bool):
        return _strict_equal(current["feature"], state.get("managed_feature"))
    return True


def _subscription_seat(
    planner: dict[str, Any] | None,
    advisor: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]] | None:
    for seat, route in (("planner", planner), ("advisor", advisor)):
        if isinstance(route, dict) and route.get("kind") in {
            "fable",
            "claude_subscription",
        }:
            return seat, route
    return None


def _guard_subscription_transition(
    existing_state: dict[str, Any] | None,
    planner: dict[str, Any] | None,
    advisor: dict[str, Any] | None,
) -> None:
    """Require an explicit full disable before replacing or moving Opus."""

    if existing_state is None:
        return
    existing = _subscription_seat(
        existing_state.get("planner"), existing_state.get("advisor")
    )
    requested = _subscription_seat(planner, advisor)
    if existing is None:
        return
    existing_seat, existing_route = existing
    opus_involved = existing_route.get("model") == OPUS_MODEL or (
        requested is not None and requested[1].get("model") == OPUS_MODEL
    )
    if not opus_involved:
        return
    same_route = (
        requested is not None
        and requested[0] == existing_seat
        and requested[1].get("model") == existing_route.get("model")
    )
    if same_route:
        return
    requested_label = (
        f"{requested[0]} {requested[1].get('model')}"
        if requested is not None
        else "no bundled Claude subscription seat"
    )
    raise ConfigurationError(
        "Refusing to replace or move the existing "
        f"{existing_seat} {existing_route.get('model')} route with {requested_label}. "
        "First run configure_native_routing.py --disable --apply, then run one "
        "fresh complete setup command."
    )


def _batch_write(
    app: AppServer,
    edits: list[dict[str, Any]],
    version: str | None,
    *,
    reload_user_config: bool,
) -> dict[str, Any]:
    return app.request(
        "config/batchWrite",
        {
            "edits": edits,
            "expectedVersion": version,
            "reloadUserConfig": reload_user_config,
        },
    )


def _status(
    target: Path,
    codex_home: Path | None,
    binaries: list[Path],
    require_effective: bool,
) -> int:
    clients_compatible = True
    for binary in binaries:
        supported, detail = supports_native_policy(binary)
        label = "compatible" if supported else f"incompatible ({detail})"
        print(f"Client: {binary} ({binary_version(binary)}) — {label}")
        clients_compatible = clients_compatible and supported
    with AppServer(target, codex_home) as app:
        workspace = Path.cwd().resolve()
        read_result = app.request(
            "config/read",
            {"includeLayers": True, "cwd": str(workspace)},
        )
        config, _ = _user_layer(read_result)
        current = _current_values(config)
        effective_config = read_result.get("config")
        effective = _current_values(
            effective_config if isinstance(effective_config, dict) else {}
        )
        state_path = app.codex_home / STATE_FILENAME
        state = _read_state(state_path)
        _validate_state_config(state, app.config_path)
        managed_pair = _is_managed(current["mode"]) and _is_managed(
            current["usage"]
        )
        state_matches = state is not None and _managed_matches(state, current)
        if state is not None and managed_pair and not state_matches:
            routing_state = "managed fields conflict with local restore state"
        elif managed_pair:
            controls_ready = (
                current["metadata"] is False
                and current["namespace"] == ROUTING_TOOL_NAMESPACE
            )
            if state is None:
                routing_state = "managed hints found without saved state"
            elif not _is_two_lane_policy(current):
                routing_state = (
                    "legacy workflow active; run a fresh explicit setup to install "
                    "the 0.10 two-lane policy, or disable it"
                )
            elif not controls_ready:
                routing_state = "managed hints found but routing controls are incomplete"
            elif (
                effective["mode"] == current["mode"]
                and effective["usage"] == current["usage"]
                and effective["metadata"] is False
                and effective["namespace"] == ROUTING_TOOL_NAMESPACE
            ):
                routing_state = f"installed and effective in {workspace}"
            else:
                routing_state = f"installed but overridden in {workspace}"
        elif current["mode"] is MISSING and current["usage"] is MISSING:
            routing_state = "inactive"
        else:
            routing_state = "partial or user-authored"
        print(f"Native policy: {routing_state}")
        if routing_state == "managed fields conflict with local restore state":
            print(
                "Recovery: run --repair as a dry run only when the saved plugin "
                "policy should replace drifted managed hints."
            )
        elif routing_state.startswith("legacy workflow active"):
            print(
                "Recovery: existing state remains valid for status, repair, and "
                "disable; run one explicit setup to replace only the managed hints "
                "with the 0.10 two-lane workflow."
            )
        elif routing_state == "managed hints found without saved state":
            print(
                "Recovery: saved restore state is missing, so repair and disable are "
                "unavailable. Review the managed hints, then run one fresh explicit "
                "setup to create the 0.10 two-lane policy and new restore state."
            )
        print(
            "V2 activation: not inferred by the installer; choose a v2 root "
            "model such as current Sol or Terra"
        )
        print(f"Config: {app.config_path}")
        subscription_available = True
        if state_matches:
            print(f"Executor: {_route_summary(state['executor'])}")
            executor_fallback = state.get("executor_fallback")
            print(
                "Executor fallback: "
                + (
                    f"{_route_summary(executor_fallback)} "
                    "(user-authorized; callability unverified)"
                    if isinstance(executor_fallback, dict)
                    else "none"
                )
            )
            planner = state.get("planner")
            advisor = state.get("advisor")
            designer = state.get("designer")
            print(f"Planner: {_route_summary(planner) if planner else 'root'}")
            print(f"Advisor: {_route_summary(advisor) if advisor else 'none'}")
            print(f"Designer: {_route_summary(designer) if designer else 'none'}")
            subscription_routes = [
                route
                for route in (planner, advisor)
                if isinstance(route, dict)
                and route.get("kind") in {"fable", "claude_subscription"}
            ]
            for route in subscription_routes:
                label = (
                    "Claude Fable 5"
                    if route["model"] == FABLE_MODEL
                    else "Claude Opus 5"
                )
                try:
                    verify_claude_prerequisites(route["model"], route["effort"])
                except ConfigurationError as exc:
                    subscription_available = False
                    print(f"{label}: unavailable — {exc}")
                else:
                    print(
                        f"{label}: ready — first-party login; no model call made"
                    )
            try:
                verified = verify_agent_routes(
                    app.codex_home,
                    workspace,
                    state["executor"],
                    planner,
                    advisor,
                )
            except (ConfigurationError, KeyError, TypeError) as exc:
                print(f"Custom-agent route: unavailable — {exc}")
                agent_routes_available = False
            else:
                agent_routes_available = True
                if verified:
                    print(
                        "Custom-agent route: verified — "
                        + ", ".join(str(path) for path in verified)
                    )
        elif routing_state.startswith("installed"):
            agent_routes_available = False
            print("Seats: managed policy found; local state is unavailable")
        elif state is not None:
            agent_routes_available = False
            print("Seats: suppressed because restore state is stale or conflicting")
        else:
            agent_routes_available = False

        managed_roles, role_issues = _managed_personal_roles(app.codex_home)
        referenced_roles = _referenced_agent_names(state if state_matches else None)
        orphaned_roles = {
            name: path
            for name, path in managed_roles.items()
            if name not in referenced_roles
        }
        for issue in role_issues:
            print(f"Managed custom-agent inspection: unavailable — {issue}")
        if orphaned_roles:
            rendered = ", ".join(
                f"{name} ({path})" for name, path in sorted(orphaned_roles.items())
            )
            print(f"Orphaned managed custom agents: {rendered}")
        else:
            print("Orphaned managed custom agents: none")
        if effective["metadata"] is False:
            print("V2 spawn metadata setting: visible when a v2 root is selected")
        else:
            print("V2 spawn metadata setting: hidden or inherited in this workspace")
        if effective["namespace"] == ROUTING_TOOL_NAMESPACE:
            print(f"V2 tool namespace: {ROUTING_TOOL_NAMESPACE}")
        else:
            print("V2 tool namespace: not routed through agents in this workspace")
        print(
            "Routing validation: not performed — config compatibility and policy "
            "effectiveness do not prove route acceptance or the effective child model"
        )
        healthy = (
            clients_compatible
            and routing_state.startswith("installed and effective")
            and state_matches
            and agent_routes_available
            and subscription_available
            and not role_issues
            and not orphaned_roles
        )
    return 1 if require_effective and not healthy else 0


def _prepare_setup_state(
    config: dict[str, Any],
    existing_state: dict[str, Any] | None,
    mode: str,
    usage: str,
    executor: dict[str, Any],
    executor_fallback: dict[str, Any] | None,
    planner: dict[str, Any] | None,
    advisor: dict[str, Any] | None,
    designer: dict[str, Any] | None,
    config_path: Path,
    replace_existing: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    current = _current_values(config)
    feature = current["feature"]
    scalar_feature = isinstance(feature, bool)
    _guard_subscription_transition(existing_state, planner, advisor)

    if existing_state is not None:
        if not _managed_matches(existing_state, current):
            raise ConfigurationError(
                "The managed routing fields changed outside this plugin. Refusing "
                "to overwrite them; inspect status and resolve the conflict first."
            )
        previous = existing_state.get("previous")
        if not isinstance(previous, dict):
            raise ConfigurationError("Managed routing state is missing its restore data.")
        previous = dict(previous)
        scalar_origin = existing_state.get("scalar_origin")
        if isinstance(scalar_origin, bool):
            managed_feature = existing_state.get("managed_feature")
            if current["feature"] != managed_feature:
                raise ConfigurationError(
                    "The converted multi_agent_v2 table gained other changes. Refusing "
                    "to update it because disable could no longer restore the original "
                    "boolean safely."
                )
    else:
        for label in ("mode", "usage"):
            value = current[label]
            if value is not MISSING and not _is_managed(value) and not replace_existing:
                raise ConfigurationError(
                    f"A user-authored {label} hint already exists. Re-run only after "
                    "review with --replace-existing-policy so it can be restored later."
                )
        recovered_mode = _is_managed(current["mode"])
        recovered_usage = _is_managed(current["usage"])
        recovered_any = recovered_mode or recovered_usage
        # Each marker independently proves ownership. Remove a surviving managed
        # string on disable, preserve any user-authored counterpart, and leave
        # unmarked metadata and namespace alone when restore state was lost.
        previous = {
            "mode": snapshot(MISSING) if recovered_mode else snapshot(current["mode"]),
            "usage": (
                snapshot(MISSING) if recovered_usage else snapshot(current["usage"])
            ),
            "metadata": (
                snapshot(MISSING, known=False)
                if recovered_any
                else snapshot(current["metadata"])
            ),
            "namespace": (
                snapshot(MISSING, known=False)
                if recovered_any
                else snapshot(current["namespace"])
            ),
        }
        scalar_origin = feature if scalar_feature else None

    if scalar_feature and existing_state is None:
        replacement = {
            "enabled": feature,
            "hide_spawn_agent_metadata": False,
            "tool_namespace": ROUTING_TOOL_NAMESPACE,
            "multi_agent_mode_hint_text": mode,
            "usage_hint_text": usage,
        }
        edits = [
            {
                "keyPath": "features.multi_agent_v2",
                "value": replacement,
                "mergeStrategy": "replace",
            }
        ]
        rollback = [
            {
                "keyPath": "features.multi_agent_v2",
                "value": feature,
                "mergeStrategy": "replace",
            }
        ]
        managed_feature = replacement
    elif existing_state is not None and isinstance(scalar_origin, bool):
        if not isinstance(feature, dict):
            raise ConfigurationError(
                "Managed scalar conversion is no longer a table; refusing to update it."
            )
        replacement = dict(feature)
        replacement.update(
            {
                "hide_spawn_agent_metadata": False,
                "tool_namespace": ROUTING_TOOL_NAMESPACE,
                "multi_agent_mode_hint_text": mode,
                "usage_hint_text": usage,
            }
        )
        edits = [
            {
                "keyPath": "features.multi_agent_v2",
                "value": replacement,
                "mergeStrategy": "replace",
            }
        ]
        rollback = [
            {
                "keyPath": "features.multi_agent_v2",
                "value": feature,
                "mergeStrategy": "replace",
            }
        ]
        managed_feature = replacement
    else:
        edits = [
            {
                "keyPath": "features.multi_agent_v2.hide_spawn_agent_metadata",
                "value": False,
                "mergeStrategy": "replace",
            },
            {
                "keyPath": "features.multi_agent_v2.tool_namespace",
                "value": ROUTING_TOOL_NAMESPACE,
                "mergeStrategy": "replace",
            },
            {
                "keyPath": "features.multi_agent_v2.multi_agent_mode_hint_text",
                "value": mode,
                "mergeStrategy": "replace",
            },
            {
                "keyPath": "features.multi_agent_v2.usage_hint_text",
                "value": usage,
                "mergeStrategy": "replace",
            },
        ]
        rollback = [
            edit
            for edit in (
                snapshot_edit(
                    "features.multi_agent_v2.hide_spawn_agent_metadata",
                    snapshot(current["metadata"]),
                ),
                snapshot_edit(
                    "features.multi_agent_v2.tool_namespace",
                    snapshot(current["namespace"]),
                ),
                snapshot_edit(
                    "features.multi_agent_v2.multi_agent_mode_hint_text",
                    snapshot(current["mode"]),
                ),
                snapshot_edit(
                    "features.multi_agent_v2.usage_hint_text",
                    snapshot(current["usage"]),
                ),
            )
            if edit is not None
        ]
        managed_feature = None

    existing_managed = existing_state.get("managed", {}) if existing_state else {}
    manage_mcp = (
        any(
            isinstance(route, dict)
            and route.get("kind") in {"fable", "claude_subscription"}
            for route in (planner, advisor)
        )
        or isinstance(existing_managed, dict)
        and isinstance(existing_managed.get("mcp"), dict)
    )
    managed_mcp: dict[str, bool] | None = None
    if manage_mcp:
        previous_mcp = previous.get("mcp")
        if not isinstance(previous_mcp, dict):
            previous_mcp = {}
        subscription_route = next(
            (
                route
                for route in (planner, advisor)
                if isinstance(route, dict)
                and route.get("kind") in {"fable", "claude_subscription"}
            ),
            None,
        )
        selected = (
            subscription_route.get("server")
            if subscription_route is not None
            else None
        )
        existing_mcp = (
            existing_managed.get("mcp")
            if isinstance(existing_managed, dict)
            and isinstance(existing_managed.get("mcp"), dict)
            else {}
        )
        touched = set(existing_mcp)
        touched.update(
            server for server, value in current["mcp"].items() if value is not MISSING
        )
        if isinstance(selected, str):
            touched.add(selected)
        for server in touched:
            if server not in previous_mcp:
                previous_mcp[server] = snapshot(current["mcp"][server])
        previous["mcp"] = previous_mcp
        managed_mcp = {server: server == selected for server in FABLE_SERVERS if server in touched}
        for server, enabled in managed_mcp.items():
            edits.append(
                {
                    "keyPath": fable_key_path(server),
                    "value": enabled,
                    "mergeStrategy": "replace",
                }
            )
            rollback_edit = snapshot_edit(
                fable_key_path(server), snapshot(current["mcp"][server])
            )
            if rollback_edit is not None:
                rollback.append(rollback_edit)

    managed = {
        "mode": mode,
        "usage": usage,
        "metadata": False,
        "namespace": ROUTING_TOOL_NAMESPACE,
    }
    if managed_mcp is not None:
        managed["mcp"] = managed_mcp

    state = {
        "schema": STATE_SCHEMA,
        "policy_version": POLICY_VERSION,
        "managed_by": "codex-orchestration",
        "config_file": str(config_path),
        "executor": executor,
        "executor_fallback": executor_fallback,
        "planner": planner,
        "advisor": advisor,
        "designer": designer,
        "managed": managed,
        "previous": previous,
        "scalar_origin": scalar_origin,
        "managed_feature": managed_feature,
    }
    return state, edits, rollback


def _restore_pre_repair_hints(
    app: AppServer,
    rollback: list[dict[str, Any]],
    expected: dict[str, Any],
    version: str | None,
    workspace: Path,
) -> None:
    result = _batch_write(app, rollback, version, reload_user_config=True)
    if result.get("status") not in {"ok", "okOverridden"}:
        raise ConfigurationError(
            f"unexpected rollback status {result.get('status')!r}"
        )
    read_result = app.request(
        "config/read",
        {"includeLayers": True, "cwd": str(workspace)},
    )
    user_config, _ = _user_layer(read_result)
    current = _current_values(user_config)
    if any(current[field] != value for field, value in expected.items()):
        raise ConfigurationError("pre-repair hint restoration could not be verified")


def _repair(
    app: AppServer,
    config: dict[str, Any],
    version: str | None,
    state: dict[str, Any] | None,
    workspace: Path,
    apply: bool,
) -> int:
    """Restore only saved managed hint bytes after exact drift validation."""

    if state is None:
        raise ConfigurationError(
            "Routing repair requires valid saved plugin state; run status first."
        )
    managed = state.get("managed")
    if not isinstance(managed, dict):
        raise ConfigurationError("Routing repair state has no managed values.")
    current = _current_values(config)
    drifted = [
        field for field in ("mode", "usage") if current[field] != managed[field]
    ]
    if not drifted:
        if _managed_matches(state, current):
            print("Native routing policy already matches its saved managed state.")
            return 0
        raise ConfigurationError(
            "Routing repair permits only managed mode/usage drift; another owned "
            "control or Fable launcher setting changed. The compatibility launcher "
            "is shared by bundled Claude routes."
        )

    if any(not _is_managed(current[field]) for field in ("mode", "usage")):
        raise ConfigurationError(
            "Routing repair requires both live hints to retain the managed ownership "
            "marker; user-authored or missing text was preserved."
        )
    controls_match = (
        current["metadata"] is False
        and current["namespace"] == ROUTING_TOOL_NAMESPACE
    )
    managed_mcp = managed.get("mcp")
    mcp_matches = managed_mcp is None or all(
        _strict_equal(current["mcp"].get(server, MISSING), enabled)
        for server, enabled in managed_mcp.items()
    )
    if not controls_match or not mcp_matches:
        raise ConfigurationError(
            "Routing repair permits only managed mode/usage drift; another owned "
            "control or Fable launcher setting changed. The compatibility launcher "
            "is shared by bundled Claude routes."
        )

    if isinstance(state.get("scalar_origin"), bool):
        feature = current["feature"]
        expected_feature = state.get("managed_feature")
        if not isinstance(feature, dict) or not isinstance(expected_feature, dict):
            raise ConfigurationError(
                "Routing repair cannot validate the converted multi_agent_v2 table."
            )
        repaired_feature = dict(feature)
        repaired_feature["multi_agent_mode_hint_text"] = managed["mode"]
        repaired_feature["usage_hint_text"] = managed["usage"]
        if not _strict_equal(repaired_feature, expected_feature):
            raise ConfigurationError(
                "Routing repair permits only managed mode/usage drift; the converted "
                "multi_agent_v2 table has other changes."
            )

    key_paths = {
        "mode": "features.multi_agent_v2.multi_agent_mode_hint_text",
        "usage": "features.multi_agent_v2.usage_hint_text",
    }
    edits = [
        {
            "keyPath": key_paths[field],
            "value": managed[field],
            "mergeStrategy": "replace",
        }
        for field in drifted
    ]
    rollback = [
        {
            "keyPath": key_paths[field],
            "value": current[field],
            "mergeStrategy": "replace",
        }
        for field in drifted
    ]
    rendered = " and ".join(drifted)
    label = "hint" if len(drifted) == 1 else "hints"
    print(f"Config: {app.config_path}")
    print(f"Will restore saved managed {rendered} {label} only.")
    print(
        "Will preserve the restore snapshot, seat routes, namespace, spawn metadata, "
        "bundled Claude launcher enablement, credentials, chats, and sessions."
    )
    subscription_configured = any(
        isinstance(route, dict)
        and route.get("kind") in {"fable", "claude_subscription"}
        for route in (state.get("planner"), state.get("advisor"))
    )
    if subscription_configured:
        configured_model = next(
            route.get("model")
            for route in (state.get("planner"), state.get("advisor"))
            if isinstance(route, dict)
            and route.get("kind") in {"fable", "claude_subscription"}
        )
        label = (
            "Claude Fable 5"
            if configured_model == FABLE_MODEL
            else "Claude Opus 5"
        )
        print(
            f"This repair does not change {label} authentication or request "
            "re-authentication."
        )
    if not apply:
        print("Dry run only. Re-run with --repair --apply after reviewing this preview.")
        return 0

    result = _batch_write(app, edits, version, reload_user_config=True)
    if result.get("status") == "okOverridden":
        try:
            _restore_pre_repair_hints(
                app,
                rollback,
                {field: current[field] for field in drifted},
                result.get("version"),
                workspace,
            )
        except ConfigurationError as rollback_exc:
            raise ConfigurationError(
                "A higher-priority layer overrides the repaired policy, and restoring "
                f"the pre-repair hints failed: {rollback_exc}"
            ) from rollback_exc
        raise ConfigurationError(
            "A higher-priority layer overrides the repaired policy; the pre-repair "
            "managed hints were restored."
        )
    if result.get("status") != "ok":
        raise ConfigurationError(
            f"Unexpected config write status: {result.get('status')!r}"
        )

    verify_result = app.request(
        "config/read",
        {"includeLayers": True, "cwd": str(workspace)},
    )
    verify_config, verify_version = _user_layer(verify_result)
    verify_current = _current_values(verify_config)
    effective_config = verify_result.get("config")
    effective_current = _current_values(
        effective_config if isinstance(effective_config, dict) else {}
    )
    if not _managed_matches(state, verify_current):
        raise ConfigurationError(
            "The user routing fields changed after Codex accepted the repair. That "
            "newer edit was preserved; saved restore state remains available."
        )
    if not _managed_matches(state, effective_current):
        try:
            _restore_pre_repair_hints(
                app,
                rollback,
                {field: current[field] for field in drifted},
                verify_version,
                workspace,
            )
        except ConfigurationError as rollback_exc:
            raise ConfigurationError(
                "Repair readback was overridden, and restoring the pre-repair hints "
                f"failed: {rollback_exc}"
            ) from rollback_exc
        raise ConfigurationError(
            "Repair did not become effective in this workspace; the pre-repair "
            "managed hints were restored."
        )

    state_path = app.codex_home / STATE_FILENAME
    if _read_state(state_path) != state:
        raise ConfigurationError(
            "Saved routing state changed concurrently during repair. It was not "
            "overwritten; run status before any further routing change."
        )

    print(
        "Native routing policy repaired; fully quit and reopen Codex, then start a "
        "new task so the current policy and MCP bridge are loaded together."
    )
    return 0


def _disable(
    app: AppServer,
    config: dict[str, Any],
    version: str | None,
    state: dict[str, Any] | None,
    state_revision: str | None,
    apply: bool,
) -> int:
    current = _current_values(config)
    state_path = app.codex_home / STATE_FILENAME
    if state is None:
        managed_mode = _is_managed(current["mode"])
        managed_usage = _is_managed(current["usage"])
        if not (managed_mode or managed_usage):
            print("Native routing is already inactive.")
            return 0
        raise ConfigurationError(
            "Cannot disable managed routing hints because saved restore state is "
            "missing. No config field was changed. Review the hints, then run a "
            "fresh explicit Luna Max setup to create new restore state or remove "
            "the stale hints manually."
        )
    else:
        if not _managed_matches(state, current):
            raise ConfigurationError(
                "Managed routing fields were edited after setup. Refusing to erase "
                "those changes; restore the managed values or remove them manually."
            )
        previous = state.get("previous")
        if not isinstance(previous, dict):
            raise ConfigurationError("Routing state has no restore data.")
        scalar_origin = state.get("scalar_origin")
        if isinstance(scalar_origin, bool):
            if current["feature"] != state.get("managed_feature"):
                raise ConfigurationError(
                    "The converted multi_agent_v2 table gained other changes. Refusing "
                    "to restore its original boolean form because that would erase them."
                )
            edits = [
                {
                    "keyPath": "features.multi_agent_v2",
                    "value": scalar_origin,
                    "mergeStrategy": "replace",
                }
            ]
            rollback = [
                {
                    "keyPath": "features.multi_agent_v2",
                    "value": current["feature"],
                    "mergeStrategy": "replace",
                }
            ]
        else:
            edits = [
                edit
                for edit in (
                    snapshot_edit(
                        "features.multi_agent_v2.hide_spawn_agent_metadata",
                        previous.get("metadata", {"known": False}),
                    ),
                    snapshot_edit(
                        "features.multi_agent_v2.tool_namespace",
                        previous.get("namespace", {"known": False}),
                    ),
                    snapshot_edit(
                        "features.multi_agent_v2.multi_agent_mode_hint_text",
                        previous.get("mode", {"known": False}),
                    ),
                    snapshot_edit(
                        "features.multi_agent_v2.usage_hint_text",
                        previous.get("usage", {"known": False}),
                    ),
                )
                if edit is not None
            ]
            rollback = [
                edit
                for edit in (
                    snapshot_edit(
                        "features.multi_agent_v2.hide_spawn_agent_metadata",
                        snapshot(current["metadata"]),
                    ),
                    snapshot_edit(
                        "features.multi_agent_v2.tool_namespace",
                        snapshot(current["namespace"]),
                    ),
                    snapshot_edit(
                        "features.multi_agent_v2.multi_agent_mode_hint_text",
                        snapshot(current["mode"]),
                    ),
                    snapshot_edit(
                        "features.multi_agent_v2.usage_hint_text",
                        snapshot(current["usage"]),
                    ),
                )
                if edit is not None
            ]
        previous_mcp = previous.get("mcp")
        if isinstance(previous_mcp, dict):
            edits.extend(
                edit
                for edit in (
                    snapshot_edit(fable_key_path(server), previous_mcp[server])
                    for server in previous_mcp
                )
                if edit is not None
            )
            rollback.extend(
                edit
                for edit in (
                    snapshot_edit(fable_key_path(server), snapshot(current["mcp"][server]))
                    for server in previous_mcp
                )
                if edit is not None
            )
        print("Will restore the pre-setup values of every owned routing field.")
    if not apply:
        print("Dry run only. Re-run with --disable --apply after reviewing this preview.")
        return 0
    _require_state_lock_backend()
    result = _batch_write(app, edits, version, reload_user_config=True)
    if result.get("status") not in {"ok", "okOverridden"}:
        raise ConfigurationError(f"Unexpected config write status: {result.get('status')!r}")
    try:
        _remove_state_cas(state_path, state_revision)
    except ConfigurationError as state_exc:
        try:
            rollback_result = _batch_write(
                app,
                rollback,
                result.get("version"),
                reload_user_config=True,
            )
            if rollback_result.get("status") not in {"ok", "okOverridden"}:
                raise ConfigurationError(
                    f"unexpected rollback status {rollback_result.get('status')!r}"
                )
        except ConfigurationError as rollback_exc:
            raise ConfigurationError(
                "Saved routing state changed concurrently and was preserved, but "
                f"the disable config rollback failed: {rollback_exc}"
            ) from rollback_exc
        raise ConfigurationError(
            "Saved routing state changed concurrently and was preserved; the disable "
            "config change was rolled back."
        ) from state_exc
    print("Native routing disabled. Start a new Codex task to clear the loaded policy.")
    return 0


def main() -> int:
    args = parse_args()
    try:
        _validate_args(args)
        target = resolve_binary(args.codex_bin)
        binaries = discover_compatibility_binaries(target, args.compat_bin)
        if args.status:
            return _status(
                target,
                args.codex_home,
                binaries,
                args.require_effective,
            )
        # Disable must remain available when the policy itself is what makes an
        # older shared-config client incompatible.
        _compatibility_report(
            binaries,
            args.allow_incompatible_client or args.disable,
        )

        with AppServer(target, args.codex_home) as app:
            workspace = Path.cwd().resolve()
            read_result = app.request(
                "config/read",
                {"includeLayers": True, "cwd": str(workspace)},
            )
            config, version = _user_layer(read_result)
            if version is None and app.config_path.exists():
                raise ConfigurationError(
                    "Could not obtain the user config version needed for a safe write."
                )
            state_path = app.codex_home / STATE_FILENAME
            state, state_revision = _read_state_with_revision(state_path)
            _validate_state_config(state, app.config_path)
            current = _current_values(config)
            legacy_marker_migration = (
                state is not None
                and _managed_matches(state, current)
                and not _is_two_lane_policy(current)
            )
            if args.disable:
                return _disable(
                    app,
                    config,
                    version,
                    state,
                    state_revision,
                    args.apply,
                )
            if args.repair:
                return _repair(
                    app,
                    config,
                    version,
                    state,
                    workspace,
                    args.apply,
                )

            catalog: dict[str, dict[str, Any]] = {}
            if (
                args.executor_model
                or args.executor_fallback_model
                or args.planner_model
                or args.advisor_model
                or args.designer_model
            ):
                try:
                    catalog = load_models(app)
                except ConfigurationError:
                    if not args.confirm_unlisted_models:
                        raise

            if args.executor_model:
                requested_executor_effort = (
                    LANE_EFFORT
                    if args.executor_effort == "auto"
                    else args.executor_effort
                )
                executor_effort = resolve_model_effort(
                    "Executor",
                    args.executor_model,
                    requested_executor_effort,
                    catalog,
                    args.confirm_unlisted_models and not args.executor_fallback_model,
                )
                executor = {
                    "kind": "model",
                    "model": args.executor_model,
                    "effort": executor_effort,
                }
            else:
                executor = {"kind": "agent", "agent": args.executor_agent}

            saved_executor_fallback = (
                state.get("executor_fallback")
                if isinstance(state, dict)
                and isinstance(state.get("executor_fallback"), dict)
                else None
            )
            if args.clear_executor_fallback:
                executor_fallback: dict[str, Any] | None = None
            elif args.executor_fallback_model:
                fallback_effort = resolve_model_effort(
                    "Executor fallback",
                    args.executor_fallback_model,
                    args.executor_fallback_effort,
                    catalog,
                    False,
                )
                executor_fallback = {
                    "kind": "model",
                    "model": args.executor_fallback_model,
                    "effort": fallback_effort,
                }
            else:
                executor_fallback = saved_executor_fallback
            if executor_fallback is not None:
                if executor["kind"] != "model":
                    raise ConfigurationError(
                        "A custom executor agent cannot retain or use an executor fallback; "
                        "pass --clear-executor-fallback."
                    )
                if executor["model"] not in catalog:
                    raise ConfigurationError(
                        "A primary executor with a saved fallback must be present in "
                        "this App Server model catalog; clear the fallback or choose "
                        "a listed primary model."
                    )
                if executor["model"] == executor_fallback["model"]:
                    raise ConfigurationError(
                        "Executor fallback must differ from the primary executor model."
                    )
                if executor_fallback is saved_executor_fallback:
                    resolve_model_effort(
                        "Saved executor fallback",
                        executor_fallback["model"],
                        executor_fallback["effort"],
                        catalog,
                        False,
                    )

            planner: dict[str, Any] | None = None
            advisor: dict[str, Any] | None = None
            designer: dict[str, Any] | None = None
            subscription_auth: dict[str, str] | None = None
            subscription_server = (
                select_fable_server()
                if (
                    args.planner_fable
                    or args.planner_opus
                    or args.advisor_fable
                    or args.advisor_opus
                )
                else None
            )
            if args.planner_model:
                planner_effort = resolve_model_effort(
                    "Planner",
                    args.planner_model,
                    args.planner_effort,
                    catalog,
                    args.confirm_unlisted_models,
                )
                planner = {
                    "kind": "model",
                    "model": args.planner_model,
                    "effort": planner_effort,
                }
            elif args.planner_agent:
                planner = {"kind": "agent", "agent": args.planner_agent}
            elif args.planner_fable:
                planner = {
                    "kind": "fable",
                    "model": FABLE_MODEL,
                    "effort": normalize_fable_effort(args.planner_effort),
                    "server": subscription_server,
                }
            elif args.planner_opus:
                planner = {
                    "kind": "claude_subscription",
                    "model": OPUS_MODEL,
                    "effort": normalize_opus_effort(args.planner_effort),
                    "server": subscription_server,
                }

            if args.advisor_model:
                advisor_effort = resolve_model_effort(
                    "Advisor",
                    args.advisor_model,
                    args.advisor_effort,
                    catalog,
                    args.confirm_unlisted_models,
                )
                advisor = {
                    "kind": "model",
                    "model": args.advisor_model,
                    "effort": advisor_effort,
                }
            elif args.advisor_agent:
                advisor = {"kind": "agent", "agent": args.advisor_agent}
            elif args.advisor_fable:
                advisor = {
                    "kind": "fable",
                    "model": FABLE_MODEL,
                    "effort": normalize_fable_effort(args.advisor_effort),
                    "server": subscription_server,
                }
            elif args.advisor_opus:
                advisor = {
                    "kind": "claude_subscription",
                    "model": OPUS_MODEL,
                    "effort": normalize_opus_effort(args.advisor_effort),
                    "server": subscription_server,
                }

            preserved_subscription_seats: list[str] = []
            if legacy_marker_migration and isinstance(state, dict):
                for seat, requested in (("planner", planner), ("advisor", advisor)):
                    existing_route = state.get(seat)
                    if (
                        requested is None
                        and isinstance(existing_route, dict)
                        and existing_route.get("kind")
                        in {"fable", "claude_subscription"}
                    ):
                        if seat == "planner":
                            planner = dict(existing_route)
                        else:
                            advisor = dict(existing_route)
                        preserved_subscription_seats.append(seat)

            if args.designer_model:
                designer_effort = resolve_model_effort(
                    "Designer",
                    args.designer_model,
                    args.designer_effort,
                    catalog,
                    args.confirm_unlisted_models,
                )
                designer = {
                    "kind": "model",
                    "model": args.designer_model,
                    "effort": designer_effort,
                }
            validate_planning_routes(planner, advisor)
            subscription_prerequisites = {
                (route["model"], route["effort"])
                for route in (planner, advisor)
                if isinstance(route, dict)
                and route.get("kind") in {"fable", "claude_subscription"}
            }
            for model, effort in sorted(subscription_prerequisites):
                subscription_auth = verify_claude_prerequisites(model, effort)

            verified_agents = verify_agent_routes(
                app.codex_home,
                workspace,
                executor,
                planner,
                advisor,
            )
            mode, usage = build_policy(
                executor, planner, advisor, designer, executor_fallback
            )
            new_state, edits, rollback = _prepare_setup_state(
                config,
                state,
                mode,
                usage,
                executor,
                executor_fallback,
                planner,
                advisor,
                designer,
                app.config_path,
                args.replace_existing_policy,
            )
            print(f"Config: {app.config_path}")
            print("Orchestrator: model selected when each Codex task starts")
            print(f"Executor: {_route_summary(executor)}")
            print(
                "Executor fallback: "
                + (
                    f"{_route_summary(executor_fallback)} "
                    "(user-authorized; callability unverified)"
                    if executor_fallback is not None
                    else "none"
                )
            )
            print(f"Planner: {_route_summary(planner) if planner else 'root'}")
            print(f"Advisor: {_route_summary(advisor) if advisor else 'none'}")
            print(f"Designer: {_route_summary(designer) if designer else 'none'}")
            if preserved_subscription_seats:
                print(
                    "Legacy migration preserved existing sealed seat(s): "
                    + ", ".join(preserved_subscription_seats)
                )
            if args.planner_fable and args.planner_effort in FABLE_EFFORT_ALIASES:
                print(
                    f"Planner effort alias: {args.planner_effort} -> "
                    f"{planner['effort']} (Claude Code effective value)"
                )
            if args.advisor_fable and args.advisor_effort in FABLE_EFFORT_ALIASES:
                print(
                    f"Advisor effort alias: {args.advisor_effort} -> "
                    f"{advisor['effort']} (Claude Code effective value)"
                )
            if subscription_auth is not None:
                configured_subscription = next(
                    route
                    for route in (planner, advisor)
                    if isinstance(route, dict)
                    and route.get("kind") in {"fable", "claude_subscription"}
                )
                subscription_label = (
                    "Claude Opus 5"
                    if configured_subscription.get("model") == OPUS_MODEL
                    else "Claude Fable 5"
                )
                print(
                    f"{subscription_label} login: ready — first-party; "
                    "setup makes no model call"
                )
            if verified_agents:
                print(
                    "Custom-agent files: "
                    + ", ".join(str(path) for path in verified_agents)
                )
            print("Delegation: Codex decides when it helps; no fixed worker count")
            print("Fork mode: none for every routed child")
            print(
                f"Tool namespace: {ROUTING_TOOL_NAMESPACE} "
                "(required for routed spawn metadata on current v2 clients)"
            )
            if not args.apply:
                print("Dry run only. Re-run with --apply after reviewing this preview.")
                return 0

            _require_state_lock_backend()
            result = _batch_write(app, edits, version, reload_user_config=True)
            if result.get("status") == "okOverridden":
                try:
                    rollback_result = _batch_write(
                        app,
                        rollback,
                        result.get("version"),
                        reload_user_config=True,
                    )
                    if rollback_result.get("status") not in {"ok", "okOverridden"}:
                        raise ConfigurationError(
                            "unexpected rollback status "
                            f"{rollback_result.get('status')!r}"
                        )
                except ConfigurationError as rollback_exc:
                    raise ConfigurationError(
                        "A higher-priority config layer overrides this routing policy, "
                        "and automatic rollback failed. The user layer may still contain "
                        f"the managed fields; run status before continuing: {rollback_exc}"
                    ) from rollback_exc
                raise ConfigurationError(
                    "A higher-priority config layer overrides this routing policy; "
                    "the user config change was rolled back."
                )
            if result.get("status") != "ok":
                raise ConfigurationError(
                    f"Unexpected config write status: {result.get('status')!r}"
                )
            try:
                new_state_revision = _write_state_cas(
                    state_path,
                    new_state,
                    state_revision,
                )
            except (ConfigurationError, OSError) as state_exc:
                try:
                    rollback_result = _batch_write(
                        app,
                        rollback,
                        result.get("version"),
                        reload_user_config=True,
                    )
                    if rollback_result.get("status") not in {"ok", "okOverridden"}:
                        raise ConfigurationError(
                            "unexpected rollback status "
                            f"{rollback_result.get('status')!r}"
                        )
                except ConfigurationError as rollback_exc:
                    raise ConfigurationError(
                        "Config was written but state persistence and automatic rollback "
                        "both failed; the user config may still contain managed fields. "
                        f"State error: {state_exc}; rollback: {rollback_exc}"
                    ) from state_exc
                raise ConfigurationError(
                    f"Could not persist restore state; config write was rolled back: {state_exc}"
                ) from state_exc

            verify_result = app.request(
                "config/read",
                {"includeLayers": True, "cwd": str(workspace)},
            )
            verify_config, verify_version = _user_layer(verify_result)
            verify_current = _current_values(verify_config)
            effective_config = verify_result.get("config")
            effective_current = _current_values(
                effective_config if isinstance(effective_config, dict) else {}
            )
            user_matches = _managed_matches(new_state, verify_current)
            effective_matches = _managed_matches(new_state, effective_current)
            if not user_matches:
                raise ConfigurationError(
                    "The user routing fields changed after Codex accepted the write. "
                    "That newer edit was preserved; restore state was retained for "
                    "diagnosis. Run status and resolve the managed-field conflict "
                    "before setup or disable."
                )
            if not effective_matches:
                try:
                    rollback_result = _batch_write(
                        app,
                        rollback,
                        verify_version,
                        reload_user_config=True,
                    )
                    if rollback_result.get("status") not in {"ok", "okOverridden"}:
                        raise ConfigurationError(
                            "unexpected rollback status "
                            f"{rollback_result.get('status')!r}"
                        )
                    if state is None:
                        _remove_state_cas(state_path, new_state_revision)
                    else:
                        _write_state_cas(state_path, state, new_state_revision)
                except (ConfigurationError, OSError) as rollback_exc:
                    raise ConfigurationError(
                        "Codex accepted the write but current-workspace effective "
                        "readback did not match, and "
                        f"automatic rollback failed: {rollback_exc}"
                    ) from rollback_exc
                raise ConfigurationError(
                    "Codex accepted the user-layer write, but current-workspace "
                    "effective readback did not match; the prior config and restore "
                    "state were reinstated."
                )
            print(
                "Native routing policy installed. Start a new Codex task, select a "
                "v2 model such as current Sol or Terra as orchestrator, and use "
                "Codex normally."
            )
            return 0
    except (ConfigurationError, OSError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
