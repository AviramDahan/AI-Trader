"""Execute the workflow's exact inline observer with synthetic time/I/O only."""
import builtins
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/hetzner-deploy.yml"
SHA = "a" * 40
OLD_SHA = "b" * 40
ENDPOINT = "https://2-28-100-77.sslip.io/health"
OBSERVER_NAME = "Verify server pull-deployment and all-role readiness marker"
WINDOW = 112 * 60
MAX_BODY = 16 * 1024
FAILURE = "Deployment not verified; inspect server deployment service. No success assumed."


def workflow():
    # BaseLoader retains the literal GitHub `on` key rather than YAML1.1 bool.
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def observer_source():
    steps = workflow()["jobs"]["deploy"]["steps"]
    step = next(item for item in steps if item["name"] == OBSERVER_NAME)
    lines = step["run"].strip().splitlines()
    assert lines[0] == "python - <<'PY'" and lines[-1] == "PY"
    return "\n".join(lines[1:-1]) + "\n"


def forbidden(*_args, **_kwargs):
    raise AssertionError("Observer fixture forbids real network/process/file I/O")


@pytest.fixture(autouse=True)
def deny_real_io(monkeypatch):
    import socket
    import subprocess
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= 10
        self.sleeps.append(seconds)
        self.now += seconds


class Response:
    def __init__(self, clock, body, read_seconds=0, read_error=None, status=200):
        self.clock = clock
        self.body = body
        self.read_seconds = read_seconds
        self.read_error = read_error
        self.status = status
        self.read_sizes = []
        self.closed = False
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def read(self, size=-1):
        self.read_sizes.append(size)
        self.clock.now += self.read_seconds
        if self.read_error:
            raise self.read_error
        end = len(self.body) if size < 0 else self.offset + size
        value = self.body[self.offset:end]
        self.offset += len(value)
        return value


def payload(build=SHA, marker=SHA):
    return json.dumps({"build_sha": build, "deployed_sha": marker}).encode()


def execute(responder, source=None):
    """Responder may only construct synthetic Response objects or raise."""
    clock = Clock()
    calls, responses, printed = [], [], []

    def urlopen(url, *, timeout):
        assert url == ENDPOINT
        assert 0 < timeout <= 10
        calls.append({"at": clock.now, "timeout": timeout})
        response = responder(clock, calls[-1])
        responses.append(response)
        return response

    fake_urllib = SimpleNamespace(request=SimpleNamespace(urlopen=urlopen))
    modules = {"os": SimpleNamespace(environ={"SHA": SHA}), "json": json,
               "time": clock, "urllib.request": fake_urllib}

    def import_fixture(name, *_args, **_kwargs):
        if name not in modules:
            raise AssertionError("Unexpected observer import: " + name)
        return modules[name]

    safe_builtins = dict(vars(builtins), __import__=import_fixture, open=forbidden)
    safe_builtins["print"] = lambda *args, **_kwargs: printed.append(" ".join(map(str, args)))
    namespace = {"__builtins__": safe_builtins}
    failure = None
    try:
        exec(compile(source or observer_source(), str(WORKFLOW), "exec"), namespace)
    except SystemExit as exc:
        failure = str(exc.code)
    return SimpleNamespace(clock=clock, calls=calls, responses=responses,
                           printed=printed, failure=failure, namespace=namespace)


def test_known_1137_second_convergence_is_observed():
    def delayed(clock, _call):
        return Response(clock, payload(marker=SHA if clock.now >= 1137 else OLD_SHA))

    result = execute(delayed)
    assert result.failure is None, (
        f"Exact marker at1137s was missed: calls={len(result.calls)}, "
        f"elapsed={result.clock.now}, failure={result.failure}")
    assert result.clock.now >= 1137
    assert result.printed == ["Backend deployment and all-role readiness PASS: " + SHA]
    assert result.responses and all(response.closed for response in result.responses)


def assert_failed_closed(result):
    assert result.failure == FAILURE
    assert result.printed == []
    assert result.responses == [] or all(response.closed for response in result.responses)


def test_immediate_exact_marker_passes_with_bounded_read_and_context_closure():
    result = execute(lambda clock, _call: Response(clock, payload()))
    assert result.failure is None
    assert len(result.calls) == 1
    assert result.clock.sleeps == []
    assert result.responses[0].closed
    assert result.responses[0].read_sizes == [MAX_BODY + 1]


@pytest.mark.parametrize("body", [
    payload(marker=OLD_SHA), payload(build=OLD_SHA), payload(OLD_SHA, OLD_SHA),
    b'{}', b'{"build_sha": true, "deployed_sha": true}',
    json.dumps({"build_sha": SHA}).encode(),
    json.dumps({"deployed_sha": SHA}).encode(),
])
def test_both_exact_sha_fields_are_required(body):
    result = execute(lambda clock, _call: Response(clock, body))
    assert_failed_closed(result)
    assert result.clock.now == WINDOW
    assert len(result.calls) == WINDOW // 10
    assert all(call["at"] < WINDOW for call in result.calls)


@pytest.mark.parametrize("body", [b'{', b'[]', b'null', b'"text"', b'42', b'true', b'\xff'])
def test_malformed_or_nonobject_json_is_not_readiness(body):
    result = execute(lambda clock, _call: Response(clock, body))
    assert_failed_closed(result)
    assert result.clock.now == WINDOW


def test_oversized_otherwise_valid_json_is_rejected_and_reads_are_bounded():
    body = payload() + b' ' * (MAX_BODY + 100 - len(payload()))
    result = execute(lambda clock, _call: Response(clock, body))
    assert_failed_closed(result)
    assert all(response.read_sizes == [MAX_BODY + 1] for response in result.responses)
    assert all(response.offset == MAX_BODY + 1 for response in result.responses)


def test_exact_size_limit_valid_json_is_accepted():
    body = payload() + b' ' * (MAX_BODY - len(payload()))
    result = execute(lambda clock, _call: Response(clock, body))
    assert result.failure is None
    assert result.responses[0].closed


@pytest.mark.parametrize("status", [201, 202, 204, 206, 301, 503, None])
def test_only_http_200_can_pass_even_with_exact_fields(status):
    result = execute(lambda clock, _call: Response(clock, payload(), status=status))
    assert_failed_closed(result)


def test_network_outages_consume_the_real_clock_budget():
    def unavailable(clock, call):
        clock.now += call["timeout"]
        raise TimeoutError("synthetic timeout; no network")

    result = execute(unavailable)
    assert_failed_closed(result)
    assert result.clock.now == WINDOW
    assert len(result.calls) == WINDOW // 20
    assert len(result.clock.sleeps) == WINDOW // 20


def test_remaining_budget_bounds_request_timeout_and_sleep():
    def near_deadline(clock, call):
        if len(calls_seen) == 0:
            calls_seen.append(call)
            # Deliberate overrun demonstrates resolver/whole-call limitation.
            clock.now += WINDOW - 13
            return Response(clock, payload(marker=OLD_SHA))
        clock.now += call["timeout"]
        raise TimeoutError("synthetic final timeout")

    calls_seen = []
    result = execute(near_deadline)
    assert_failed_closed(result)
    assert [call["timeout"] for call in result.calls] == [10, 3]
    assert result.clock.sleeps == [10]
    assert result.clock.now == WINDOW


def test_sleep_is_shortened_to_remaining_budget_without_late_poll():
    def near_deadline(clock, _call):
        clock.now = WINDOW - 2.5
        return Response(clock, payload(marker=OLD_SHA))

    result = execute(near_deadline)
    assert_failed_closed(result)
    assert result.clock.sleeps == [2.5]
    assert len(result.calls) == 1


@pytest.mark.parametrize("overrun", [0, 0.1, 100])
def test_exact_marker_at_or_after_deadline_cannot_pass(overrun):
    def late(clock, _call):
        clock.now = WINDOW - 1
        return Response(clock, payload(), read_seconds=1 + overrun)

    result = execute(late)
    assert_failed_closed(result)
    assert len(result.calls) == 1
    assert result.clock.sleeps == []


def test_read_exceptions_close_every_response_and_do_not_pass():
    result = execute(lambda clock, _call: Response(
        clock, b'', read_seconds=1, read_error=OSError("synthetic truncated read")))
    assert_failed_closed(result)
    assert result.responses
    assert WINDOW <= result.clock.now <= WINDOW + 1


def test_parsing_time_is_checked_before_success(monkeypatch):
    real_loads = json.loads
    current_clock = []

    def slow_parse(raw):
        data = real_loads(raw)
        current_clock[0].now = WINDOW
        return data

    def response(clock, _call):
        current_clock.append(clock)
        return Response(clock, payload())

    monkeypatch.setattr(json, "loads", slow_parse)
    result = execute(response)
    assert_failed_closed(result)


def test_workflow_event_permissions_ci_and_concurrency_guards_remain_exact():
    document = workflow()
    assert document["on"] == {"workflow_run": {
        "workflows": ["Cloud readiness (no deployment)"],
        "types": ["completed"], "branches": ["main"]}}
    assert document["permissions"] == {"actions": "read", "contents": "read"}
    assert document["concurrency"] == {
        "group": "hetzner-production-deploy", "cancel-in-progress": "false"}
    job = document["jobs"]["deploy"]
    assert job["if"] == ("github.event.workflow_run.conclusion == 'success' && "
                         "github.event.workflow_run.event == 'push' && "
                         "github.event.workflow_run.head_repository.full_name == github.repository")
    ci, observer = job["steps"]
    assert ci["name"] == "Require CI success for the exact same commit"
    assert ci["uses"] == "actions/github-script@v7"
    assert ci["with"]["script"] == """const sha = context.payload.workflow_run.head_sha;
for (let n=0;n<60;n++) {
  const r = await github.rest.actions.listWorkflowRunsForRepo({...context.repo, head_sha:sha, branch:'main', event:'push', per_page:100});
  const ci=r.data.workflow_runs.find(x=>x.name==='CI');
  if(ci?.conclusion==='success') return;
  if(ci?.status==='completed') throw new Error('CI did not pass');
  await new Promise(resolve=>setTimeout(resolve,10000));
}
throw new Error('CI not complete; no deployment');
"""
    assert observer["env"] == {"SHA": "${{ github.event.workflow_run.head_sha }}"}
    assert "uses" not in observer  # Inline: no new checkout/script trust surface.


def test_workflow_time_budgets_have_bounded_external_backstops():
    job = workflow()["jobs"]["deploy"]
    ci, observer = job["steps"]
    assert int(job["timeout-minutes"]) == 125
    assert int(ci["timeout-minutes"]) == 11
    assert int(observer["timeout-minutes"]) == 113
    assert 11 + 113 < 125
    result = execute(lambda clock, _call: Response(clock, payload(marker=OLD_SHA)))
    assert_failed_closed(result)
    assert result.clock.now == WINDOW
    assert WINDOW == 5 * 60 + 85 * 60 + 20 * 60 + 2 * 60
    assert WINDOW < int(observer["timeout-minutes"]) * 60
    service = dict(line.split('=', 1) for line in
        (ROOT / 'deploy/systemd/ai-trader-deploy.service').read_text().splitlines() if '=' in line)
    assert int(service['TimeoutStartSec']) == 85 * 60
    assert int(service['TimeoutStopSec']) == 20 * 60
    assert service['KillMode'] == 'mixed'


def test_execution_harness_denies_nonallowlisted_imports_and_file_io():
    with pytest.raises(AssertionError, match="Unexpected observer import"):
        execute(forbidden, source="import socket")
    with pytest.raises(AssertionError, match="forbids real"):
        execute(forbidden, source="open('not-a-real-file')")
