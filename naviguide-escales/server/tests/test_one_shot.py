"""Passages uniques : estimation sans appel, empreinte, verrou, reprise."""
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import llm_budget
import one_shot

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "one_shot.py"
REPO = Path(__file__).resolve().parents[3]
_SECRET_KEYS = (
    "NEBIUS_API_KEY",
    "NVIDIA_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "TAVILY_API_KEY",
)


@pytest.fixture(autouse=True)
def _isolated_one_shot(tmp_path, monkeypatch):
    saved = dict(one_shot.REGISTRY)
    monkeypatch.setenv(one_shot.ENV_DIR, str(tmp_path / "one-shot"))
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    monkeypatch.delenv("NAVIGUIDE_LLM_BACKGROUND", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_DAILY_USD", raising=False)
    for tier in llm_budget.TIERS:
        monkeypatch.delenv(f"NAVIGUIDE_LLM_DAILY_TOKENS_{tier.upper()}", raising=False)
    yield
    one_shot.REGISTRY.clear()
    one_shot.REGISTRY.update(saved)


def _forbid_network(monkeypatch):
    def connect(self, address):
        raise AssertionError("réseau interdit")

    def create_connection(*args, **kwargs):
        raise AssertionError("réseau interdit")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create_connection)


def _watch_execute(monkeypatch):
    seen: list[str] = []

    def execute(call):
        seen.append(call.call_id)
        raise AssertionError("appel")

    monkeypatch.setattr(one_shot.REGISTRY[one_shot.FIXTURE_JOB], "execute", execute)
    return seen


def test_registry_holds_fixture_and_vl_route():
    assert list(one_shot.REGISTRY) == [one_shot.FIXTURE_JOB, "vl_route_bm", "stories_177"]


def test_estimate_makes_no_call(monkeypatch, capsys):
    _forbid_network(monkeypatch)

    def allow_forbidden(_tier):
        raise AssertionError("allow")

    monkeypatch.setattr(llm_budget, "allow", allow_forbidden)
    seen = _watch_execute(monkeypatch)
    code = one_shot.main(["--job", one_shot.FIXTURE_JOB, "--estimate"])
    captured = capsys.readouterr()
    assert code == 0
    assert seen == []
    assert captured.err == ""
    est = one_shot.build_estimate(one_shot.FIXTURE_JOB)
    assert seen == []
    assert est["calls"] == 3
    assert f"fingerprint: {est['fingerprint']}" in captured.out
    assert f"calls: {est['calls']}" in captured.out
    manual = 0.0
    tokens = 0
    for item in est["items"]:
        manual = round(
            manual
            + llm_budget.estimate_usd(
                item["tier"], item["prompt_tokens"], item["completion_tokens"]
            ),
            8,
        )
        tokens += item["prompt_tokens"] + item["completion_tokens"]
    assert est["usd"] == manual
    assert est["tokens"] == tokens
    assert est["caps"]["tokens"] == {tier: llm_budget.daily_cap(tier) for tier in llm_budget.TIERS}
    assert est["caps"]["usd"] is None
    assert one_shot.fingerprint_for(est) == est["fingerprint"]
    assert not (Path(os.environ[one_shot.ENV_DIR])).exists()


def test_estimate_reads_the_post_caps(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_FAST", "12345")
    est = one_shot.build_estimate(one_shot.FIXTURE_JOB)
    assert est["caps"]["tokens"]["fast"] == 12345
    assert est["caps"]["usd"] is None
    first = est["fingerprint"]
    raw = str(llm_budget.estimate_usd("fast", 1, 0) * 100)
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_USD", raw)
    second = one_shot.build_estimate(one_shot.FIXTURE_JOB)
    assert second["caps"]["usd"] == llm_budget.daily_usd_cap()
    assert second["fingerprint"] != first


def test_run_refuses_missing_or_wrong_fingerprint(monkeypatch, tmp_path, capsys):
    _forbid_network(monkeypatch)
    seen = _watch_execute(monkeypatch)
    assert one_shot.main(["--job", one_shot.FIXTURE_JOB, "--run"]) == 2
    assert "empreinte manquante" in capsys.readouterr().err
    assert one_shot.main(
        ["--job", one_shot.FIXTURE_JOB, "--run", "--i-have-read-the-estimate", "deadbeef"]
    ) == 2
    assert "empreinte différente" in capsys.readouterr().err
    assert seen == []
    assert not (tmp_path / "one-shot").exists()


def test_run_refuses_when_lock_exists(monkeypatch, tmp_path):
    _forbid_network(monkeypatch)
    seen = _watch_execute(monkeypatch)
    lock = tmp_path / "one-shot" / one_shot.FIXTURE_JOB / ".done"
    lock.parent.mkdir(parents=True)
    lock.write_text("{}\n", encoding="utf-8")
    fingerprint = one_shot.build_estimate(one_shot.FIXTURE_JOB)["fingerprint"]
    with pytest.raises(one_shot.Refused) as refused:
        one_shot.run(one_shot.FIXTURE_JOB, fingerprint)
    assert refused.value.code == "locked"
    assert seen == []


def test_run_stops_at_token_cap(monkeypatch, tmp_path):
    _forbid_network(monkeypatch)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_FAST", "100")
    seen: list[str] = []

    def execute(call):
        seen.append(call.call_id)
        llm_budget.record(call.tier, call.prompt_tokens, call.completion_tokens)

    calls = [
        one_shot.PlannedCall("a", "fast", 100, 0),
        one_shot.PlannedCall("b", "fast", 100, 0),
    ]
    one_shot.register(one_shot.Job("probe", lambda: list(calls), execute))
    fingerprint = one_shot.build_estimate("probe")["fingerprint"]
    with pytest.raises(one_shot.StoppedAtCap) as stopped:
        one_shot.run("probe", fingerprint)
    assert stopped.value.call_id == "b"
    assert stopped.value.completed == ["a"]
    assert seen == ["a"]
    progress = json.loads((tmp_path / "one-shot" / "probe" / "progress.json").read_text(encoding="utf-8"))
    assert progress["completed"] == ["a"]
    assert progress["fingerprint"] == fingerprint
    assert "usd" not in progress
    assert not one_shot.lock_exists("probe")


def test_resume_does_not_replay_paid_calls(monkeypatch):
    _forbid_network(monkeypatch)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_FAST", "100")
    state = {"day": "2026-01-01"}
    monkeypatch.setattr(llm_budget, "today", lambda: state["day"])
    seen: list[str] = []

    def execute(call):
        seen.append(call.call_id)
        llm_budget.record(call.tier, call.prompt_tokens, call.completion_tokens)

    calls = [
        one_shot.PlannedCall("a", "fast", 100, 0),
        one_shot.PlannedCall("b", "fast", 100, 0),
    ]
    one_shot.register(one_shot.Job("probe", lambda: list(calls), execute))
    fingerprint = one_shot.build_estimate("probe")["fingerprint"]
    with pytest.raises(one_shot.StoppedAtCap):
        one_shot.run("probe", fingerprint)
    state["day"] = "2026-01-02"
    result = one_shot.run("probe", fingerprint)
    assert seen == ["a", "b"]
    assert result["completed"] == ["a", "b"]
    assert one_shot.lock_exists("probe")
    done = json.loads(one_shot.lock_path("probe").read_text(encoding="utf-8"))
    assert "usd" not in done
    with pytest.raises(one_shot.Refused) as refused:
        one_shot.run("probe", fingerprint)
    assert refused.value.code == "locked"
    assert seen == ["a", "b"]


def test_failed_call_is_retried_without_replaying_the_previous(monkeypatch):
    _forbid_network(monkeypatch)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    seen: list[str] = []

    def execute(call):
        seen.append(call.call_id)
        if call.call_id == "b":
            raise RuntimeError("panne")

    calls = [
        one_shot.PlannedCall("a", "fast", 10, 0),
        one_shot.PlannedCall("b", "fast", 10, 0),
    ]
    job = one_shot.Job("probe", lambda: list(calls), execute)
    one_shot.register(job)
    fingerprint = one_shot.build_estimate("probe")["fingerprint"]
    with pytest.raises(RuntimeError):
        one_shot.run("probe", fingerprint)
    assert seen == ["a", "b"]

    def execute_ok(call):
        seen.append(call.call_id)

    job.execute = execute_ok
    result = one_shot.run("probe", fingerprint)
    assert result["completed"] == ["a", "b"]
    assert seen == ["a", "b", "b"]
    assert one_shot.lock_exists("probe")


def test_mode_off_stops_before_any_call(monkeypatch):
    _forbid_network(monkeypatch)
    seen = _watch_execute(monkeypatch)
    fingerprint = one_shot.build_estimate(one_shot.FIXTURE_JOB)["fingerprint"]
    with pytest.raises(one_shot.StoppedAtCap) as stopped:
        one_shot.run(one_shot.FIXTURE_JOB, fingerprint)
    assert stopped.value.completed == []
    assert seen == []
    assert not one_shot.lock_exists(one_shot.FIXTURE_JOB)


def test_lock_directory_inside_the_repo_is_refused(monkeypatch):
    inside = REPO / "naviguide-simulator" / "server" / "voyage_data" / "one-shot-test"
    monkeypatch.setenv(one_shot.ENV_DIR, str(inside))
    fingerprint = one_shot.build_estimate(one_shot.FIXTURE_JOB)["fingerprint"]
    with pytest.raises(one_shot.OneShotError) as err:
        one_shot.run(one_shot.FIXTURE_JOB, fingerprint)
    assert err.value.code == "bad-dir"
    assert not inside.exists()


def test_default_directory_is_outside_the_repo(monkeypatch, tmp_path):
    monkeypatch.delenv(one_shot.ENV_DIR, raising=False)
    monkeypatch.setattr(one_shot.Path, "home", lambda: tmp_path)
    got = one_shot.data_dir()
    assert got == (tmp_path / ".local" / "share" / "naviguide" / "one-shot").resolve()
    assert REPO.resolve() not in got.parents


def test_there_is_no_force_switch(capsys):
    with pytest.raises(SystemExit) as exited:
        one_shot.main(
            [
                "--job",
                one_shot.FIXTURE_JOB,
                "--run",
                "--force",
                "--i-have-read-the-estimate",
                "aa",
            ]
        )
    assert exited.value.code == 2
    with pytest.raises(SystemExit) as help_exit:
        one_shot.main(["--help"])
    assert help_exit.value.code == 0
    text = capsys.readouterr().out
    assert "--force" not in text
    assert "--i-have-read-the-estimate" in text


def test_env_example_documents_the_directory_without_a_value():
    text = (REPO / "infra" / "vps" / "naviguide" / "simulator.env.example").read_text(encoding="utf-8")
    mentions = [line for line in text.splitlines() if "NAVIGUIDE_ONE_SHOT_DIR" in line]
    assert mentions == ["#NAVIGUIDE_ONE_SHOT_DIR="]


def test_script_estimate_and_second_run_refusal(tmp_path):
    env = os.environ.copy()
    env["NAVIGUIDE_LLM_MODE"] = "off"
    env[one_shot.ENV_DIR] = str(tmp_path / "locks")
    env["NAVIGUIDE_VOYAGE_DIR"] = str(tmp_path / "voyage")
    env.pop("NAVIGUIDE_LLM_BACKGROUND", None)
    env.pop("NAVIGUIDE_LLM_DAILY_USD", None)
    for tier in llm_budget.TIERS:
        env.pop(f"NAVIGUIDE_LLM_DAILY_TOKENS_{tier.upper()}", None)
    for key in _SECRET_KEYS:
        env.pop(key, None)
    estimate = subprocess.run(
        [sys.executable, str(SCRIPT), "--job", one_shot.FIXTURE_JOB, "--estimate"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert estimate.returncode == 0, estimate.stderr
    fingerprint = ""
    for line in estimate.stdout.splitlines():
        if line.startswith("fingerprint: "):
            fingerprint = line.split(": ", 1)[1].strip()
    assert len(fingerprint) == 64
    assert not (tmp_path / "locks").exists()
    env["NAVIGUIDE_LLM_MODE"] = "on-demand"
    first = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--job",
            one_shot.FIXTURE_JOB,
            "--run",
            "--i-have-read-the-estimate",
            fingerprint,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    assert "lock: ok" in first.stdout
    second = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--job",
            one_shot.FIXTURE_JOB,
            "--run",
            "--i-have-read-the-estimate",
            fingerprint,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 2
    assert "verrou de réussite présent" in second.stderr
    assert "lock: ok" not in second.stdout


def _four_calls() -> list[one_shot.PlannedCall]:
    return [one_shot.PlannedCall(f"c{i}", "fast", 1, 0) for i in range(4)]


def test_two_threads_one_execution_and_no_duplicate_calls(monkeypatch):
    _forbid_network(monkeypatch)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    sibling = threading.Event()
    seen: list[str] = []
    calls = _four_calls()

    def execute(call):
        if call.call_id == "c0" and not sibling.wait(5):
            raise TimeoutError("l'autre lancement n'est pas arrivé")
        seen.append(call.call_id)

    one_shot.register(one_shot.Job("probe", lambda: list(calls), execute))
    fingerprint = one_shot.build_estimate("probe")["fingerprint"]
    outcomes: list[str] = []

    def worker():
        try:
            one_shot.run("probe", fingerprint)
            outcomes.append("ok")
        except one_shot.Refused as exc:
            outcomes.append(exc.code)
            sibling.set()
        except Exception as exc:
            outcomes.append(type(exc).__name__)
            sibling.set()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert [thread.is_alive() for thread in threads] == [False, False]
    assert sorted(outcomes) == ["busy", "ok"]
    assert seen == ["c0", "c1", "c2", "c3"]
    assert one_shot.lock_exists("probe")
    with pytest.raises(one_shot.Refused) as refused:
        one_shot.run("probe", fingerprint)
    assert refused.value.code == "locked"
    assert seen == ["c0", "c1", "c2", "c3"]


_CONCURRENT_WORKER = r"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.environ["ONE_SHOT_SERVER"])
import one_shot

calls = [one_shot.PlannedCall(f"c{i}", "fast", 1, 0) for i in range(4)]
log_path = Path(os.environ["ONE_SHOT_LOG"])
sibling = Path(os.environ["ONE_SHOT_SIBLING"])

def execute(call):
    if call.call_id == "c0":
        deadline = time.time() + 5
        while not sibling.exists():
            if time.time() > deadline:
                raise TimeoutError("l'autre lancement n'est pas arrivé")
            time.sleep(0.01)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(call.call_id + "\n")
        handle.flush()

one_shot.register(one_shot.Job("probe", lambda: list(calls), execute))
code = one_shot.main([
    "--job", "probe",
    "--run",
    "--i-have-read-the-estimate",
    os.environ["ONE_SHOT_FP"],
])
if code != 0:
    sibling.write_text(str(code), encoding="utf-8")
raise SystemExit(code)
"""


def test_two_processes_one_execution_and_no_duplicate_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    calls = _four_calls()
    one_shot.register(one_shot.Job("probe", lambda: list(calls), lambda _call: None))
    fingerprint = one_shot.build_estimate("probe")["fingerprint"]
    log_path = tmp_path / "calls.log"
    sibling = tmp_path / "sibling"
    env = os.environ.copy()
    env["NAVIGUIDE_LLM_MODE"] = "on-demand"
    env[one_shot.ENV_DIR] = os.environ[one_shot.ENV_DIR]
    env["NAVIGUIDE_VOYAGE_DIR"] = os.environ["NAVIGUIDE_VOYAGE_DIR"]
    env["ONE_SHOT_SERVER"] = str(ROOT / "server")
    env["ONE_SHOT_LOG"] = str(log_path)
    env["ONE_SHOT_SIBLING"] = str(sibling)
    env["ONE_SHOT_FP"] = fingerprint
    env.pop("NAVIGUIDE_LLM_BACKGROUND", None)
    env.pop("NAVIGUIDE_LLM_DAILY_USD", None)
    for tier in llm_budget.TIERS:
        env.pop(f"NAVIGUIDE_LLM_DAILY_TOKENS_{tier.upper()}", None)
    for key in _SECRET_KEYS:
        env.pop(key, None)
    procs = []
    try:
        for _ in range(2):
            procs.append(subprocess.Popen(
                [sys.executable, "-c", _CONCURRENT_WORKER],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ))
        finished = [proc.wait(timeout=15) for proc in procs]
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
    assert sorted(finished) == [0, 2]
    refused = next(proc for proc in procs if proc.returncode == 2)
    assert "un passage est déjà en cours" in refused.stderr.read()
    assert log_path.read_text(encoding="utf-8").split() == ["c0", "c1", "c2", "c3"]


_HOLD_WORKER = r"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.environ["ONE_SHOT_SERVER"])
import one_shot

calls = [one_shot.PlannedCall(f"c{i}", "fast", 1, 0) for i in range(4)]

def execute(call):
    if call.call_id == "c0":
        Path(os.environ["ONE_SHOT_READY"]).write_text("1", encoding="utf-8")
        time.sleep(30)

one_shot.register(one_shot.Job("probe", lambda: list(calls), execute))
raise SystemExit(one_shot.main([
    "--job", "probe",
    "--run",
    "--i-have-read-the-estimate",
    os.environ["ONE_SHOT_FP"],
]))
"""


def test_execution_lock_releases_when_the_process_is_killed(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    calls = _four_calls()
    seen: list[str] = []

    def execute(call):
        seen.append(call.call_id)

    one_shot.register(one_shot.Job("probe", lambda: list(calls), execute))
    fingerprint = one_shot.build_estimate("probe")["fingerprint"]
    ready = tmp_path / "ready"
    env = os.environ.copy()
    env["NAVIGUIDE_LLM_MODE"] = "on-demand"
    env[one_shot.ENV_DIR] = os.environ[one_shot.ENV_DIR]
    env["NAVIGUIDE_VOYAGE_DIR"] = os.environ["NAVIGUIDE_VOYAGE_DIR"]
    env["ONE_SHOT_SERVER"] = str(ROOT / "server")
    env["ONE_SHOT_READY"] = str(ready)
    env["ONE_SHOT_FP"] = fingerprint
    env.pop("NAVIGUIDE_LLM_BACKGROUND", None)
    env.pop("NAVIGUIDE_LLM_DAILY_USD", None)
    for tier in llm_budget.TIERS:
        env.pop(f"NAVIGUIDE_LLM_DAILY_TOKENS_{tier.upper()}", None)
    for key in _SECRET_KEYS:
        env.pop(key, None)
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLD_WORKER],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 5
        while not ready.exists():
            if proc.poll() is not None:
                raise AssertionError(proc.stderr.read())
            if time.time() > deadline:
                raise AssertionError("le processus n'a pas pris le verrou")
            time.sleep(0.02)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    result = one_shot.run("probe", fingerprint)
    assert result["completed"] == ["c0", "c1", "c2", "c3"]
    assert seen == ["c0", "c1", "c2", "c3"]
    with pytest.raises(one_shot.Refused) as refused:
        one_shot.run("probe", fingerprint)
    assert refused.value.code == "locked"


def test_run_stops_when_the_daily_usd_cap_would_be_crossed(monkeypatch, tmp_path):
    _forbid_network(monkeypatch)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    seen: list[str] = []

    def execute(call):
        seen.append(call.call_id)

    calls = [
        one_shot.PlannedCall("a", "fast", 10, 0),
        one_shot.PlannedCall("b", "fast", 10, 0),
    ]
    one_shot.register(one_shot.Job("probe", lambda: list(calls), execute))
    reserve = llm_budget.estimate_usd("fast", 0, llm_budget.max_tokens_for("fast"))
    assert reserve > 0
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_USD", str(reserve / 2))
    fingerprint = one_shot.build_estimate("probe")["fingerprint"]
    with pytest.raises(one_shot.StoppedAtCap) as stopped:
        one_shot.run("probe", fingerprint)
    assert stopped.value.reason == "usd"
    assert stopped.value.call_id == "a"
    assert stopped.value.completed == []
    assert "plafond du jour" in str(stopped.value)
    assert seen == []
    progress_path = tmp_path / "one-shot" / "probe" / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["completed"] == []
    assert "usd" not in progress
    assert progress_path.stat().st_mode & 0o777 == 0o600
    assert not one_shot.lock_exists("probe")


def test_mode_off_names_the_mode(monkeypatch):
    _forbid_network(monkeypatch)
    seen = _watch_execute(monkeypatch)
    fingerprint = one_shot.build_estimate(one_shot.FIXTURE_JOB)["fingerprint"]
    with pytest.raises(one_shot.StoppedAtCap) as stopped:
        one_shot.run(one_shot.FIXTURE_JOB, fingerprint)
    assert stopped.value.reason == "mode"
    assert stopped.value.completed == []
    assert "mode interdit" in str(stopped.value)
    assert seen == []


def test_token_cap_names_the_token_ceiling(monkeypatch):
    _forbid_network(monkeypatch)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_FAST", "100")

    def execute(call):
        llm_budget.record(call.tier, call.prompt_tokens, call.completion_tokens)

    calls = [
        one_shot.PlannedCall("a", "fast", 100, 0),
        one_shot.PlannedCall("b", "fast", 100, 0),
    ]
    one_shot.register(one_shot.Job("probe", lambda: list(calls), execute))
    fingerprint = one_shot.build_estimate("probe")["fingerprint"]
    with pytest.raises(one_shot.StoppedAtCap) as stopped:
        one_shot.run("probe", fingerprint)
    assert stopped.value.reason == "tokens"
    assert stopped.value.call_id == "b"
    assert "plafond de jetons" in str(stopped.value)


def test_success_lock_is_private(monkeypatch):
    _forbid_network(monkeypatch)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    one_shot.register(
        one_shot.Job(
            "probe",
            lambda: [one_shot.PlannedCall("a", "fast", 1, 0)],
            lambda _call: None,
        )
    )
    fingerprint = one_shot.build_estimate("probe")["fingerprint"]
    one_shot.run("probe", fingerprint)
    assert one_shot.lock_path("probe").stat().st_mode & 0o777 == 0o600
