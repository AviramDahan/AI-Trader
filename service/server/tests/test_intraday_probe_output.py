"""Pure probe output contract; no image, DB, provider or trading calls."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[3] / 'scripts' / 'entry_intraday_compatibility_probe.py'
    spec = importlib.util.spec_from_file_location('intraday_output_probe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PHASES = (
    'identity_bridge', 'identity_candidate', 'old_seed', 'candidate_preserve_v1',
    'candidate_intraday', 'bridge_creation_blocked', 'bridge_pending',
    'bridge_restart', 'candidate_emergency', 'bridge_emergency',
    'old_reader_refused10', 'bridge_restore10', 'bridge_restored_exits',
    'bridge_resume', 'bridge_expiry', 'bridge_final',
)


@pytest.mark.parametrize('phase', PHASES)
def test_success_emits_one_json_line_and_keeps_library_noise_on_stderr(probe, monkeypatch, capsys, phase):
    seen = []
    def bootstrap(value):
        seen.append(('bootstrap', value))
        print('[INFO] Database initialized')
    def run(value):
        seen.append(('run', value))
        print('synthetic library status')
        print('existing stderr status', file=sys.stderr)
        probe.DETAILS['synthetic_phase_completed'] = True
    monkeypatch.setattr(probe, 'bootstrap', bootstrap)
    monkeypatch.setattr(probe, 'run', run)
    monkeypatch.setattr(sys, 'argv', ['probe.py', phase])
    monkeypatch.setenv('BUILD_SHA', 'a'*40)
    probe.main()
    output = capsys.readouterr()
    lines = output.out.splitlines()
    assert len(lines) == 1
    receipt = json.loads(lines[0])
    assert receipt['phase'] == phase and receipt['status'] == 'PASS'
    assert receipt['build_sha'] == 'a'*40
    assert receipt['synthetic_phase_completed'] is True
    assert len(receipt['probe_sha256']) == 64
    assert output.err.splitlines() == ['[INFO] Database initialized',
                                      'synthetic library status', 'existing stderr status']
    assert seen == [('bootstrap', phase), ('run', phase)]


@pytest.mark.parametrize('failed_stage', ['bootstrap', 'run'])
def test_failed_phase_raises_without_a_pass_or_any_stdout(probe, monkeypatch, capsys, failed_stage):
    seen = []
    def operation(stage):
        def call(value):
            seen.append(stage)
            print('synthetic noise before failure')
            if stage == failed_stage:
                raise AssertionError('synthetic required phase assertion failed')
        return call
    monkeypatch.setattr(probe, 'bootstrap', operation('bootstrap'))
    monkeypatch.setattr(probe, 'run', operation('run'))
    monkeypatch.setattr(sys, 'argv', ['probe.py', 'old_seed'])
    with pytest.raises(AssertionError, match='synthetic required phase assertion failed'):
        probe.main()
    output = capsys.readouterr()
    assert output.out == '' and 'PASS' not in output.out
    assert output.err.splitlines() == ['synthetic noise before failure']*len(seen)
    assert seen == (['bootstrap'] if failed_stage == 'bootstrap' else ['bootstrap', 'run'])


def test_unknown_phase_does_not_run_or_emit_success(probe, monkeypatch, capsys):
    def forbidden(value):
        raise AssertionError('invalid phase reached library code')
    monkeypatch.setattr(probe, 'bootstrap', forbidden)
    monkeypatch.setattr(probe, 'run', forbidden)
    monkeypatch.setattr(sys, 'argv', ['probe.py', 'unsupported'])
    with pytest.raises(SystemExit, match='exact_intraday_test_phase_required'):
        probe.main()
    assert capsys.readouterr().out == ''
