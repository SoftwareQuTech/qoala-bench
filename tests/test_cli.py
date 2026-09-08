"""Tests for the CLI dispatch in :mod:`qoala_bench.cli`.

The CLI's three commands all delegate to heavier helpers
(``run_compilator``, ``run_add_steps``, an analyser instance). We
substitute those helpers via ``monkeypatch`` so the tests exercise
only the argument-parsing, validation, and dispatch logic and do not
require ``qoala-opt`` / ``qoala-translate`` / NetSquid to be available.
"""

from __future__ import annotations

import pytest
import yaml

from qoala_bench import cli
from qoala_bench.analyzers.base import AnalyzeResult, DataAnalyzer


def _minimal_config_dict():
    """Same shape as the one in test_config.py — kept local on purpose."""
    return {
        "version": 1,
        "name": "test-bench",
        "author": "tester",
        "params": {
            "config_path": "params.json",
            "nodes": [
                {"node_name": "client", "num_qubits": 1, "inputs": {}},
                {"node_name": "server", "num_qubits": 1, "inputs": {}},
            ],
            "qstate_formalism": "DM",
        },
        "execution": {"iterations": 1, "cpu_count": 1},
        "pipeline": {
            "generator": {
                "type": "compare",
                "params": {
                    "programs": [{"label": "a", "program_variant": "unoptimized"}]
                },
            },
            "analyzer": {
                "type": "noop",
                "params": {},
            },
        },
    }


def _write_yaml_pair(tmp_path):
    """Write a benchmark YAML plus its params.json into tmp_path."""
    params = tmp_path / "params.json"
    params.write_text(
        '{"t1":1, "t2":1, "single_gate_duration":1, "two_gate_duration":1,'
        '"single_gate_fid":0.99, "two_gate_fid":0.99, "single_gate_error":0.01,'
        '"two_gate_error":0.01, "host_instr_time":1, "host_peer_latency":1,'
        '"qnos_instr_time":1, "latency":1, "link_duration":1, "link_fid":0.99}'
    )
    cfg = _minimal_config_dict()
    cfg["params"]["config_path"] = "params.json"
    yaml_path = tmp_path / "bench.yaml"
    yaml_path.write_text(yaml.safe_dump(cfg))
    return yaml_path


# ---------------------------------------------------------------------------
# cmd_generate
# ---------------------------------------------------------------------------


def test_cmd_generate_compilation_only_short_circuits_simulation(tmp_path, monkeypatch):
    """With --compilation-only and compilator disabled, generate exits cleanly."""
    yaml_path = _write_yaml_pair(tmp_path)
    monkeypatch.chdir(tmp_path)

    # The minimal config has no compilator section, so run_compilator isn't
    # invoked. With compilation_only=True, no generator is invoked either.
    rc = cli.cmd_generate(str(yaml_path), output_name="my-run", compilation_only=True)
    assert rc == 0
    assert (tmp_path / "results" / "my-run").is_dir()
    assert (tmp_path / "results" / "my-run" / "dataset.yaml").is_file()


def test_cmd_generate_invokes_registered_generator(tmp_path, monkeypatch):
    """Without --compilation-only, the registered generator is dispatched."""
    yaml_path = _write_yaml_pair(tmp_path)
    monkeypatch.chdir(tmp_path)

    calls = []

    class _Recorder:
        def generate(self, cfg, dataset, comp_state=None):
            calls.append({"name": cfg.name, "dataset_root": dataset.root})

    monkeypatch.setitem(cli.GENERATOR_REGISTRY, "compare", _Recorder)

    rc = cli.cmd_generate(str(yaml_path), output_name="run-2", compilation_only=False)
    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["name"] == "test-bench"


def test_cmd_generate_unknown_generator_raises(tmp_path, monkeypatch):
    yaml_path = _write_yaml_pair(tmp_path)
    monkeypatch.chdir(tmp_path)

    # Pretend nothing is registered for the "compare" name.
    monkeypatch.setattr(cli, "GENERATOR_REGISTRY", {})

    with pytest.raises(ValueError, match="Unknown generator type"):
        cli.cmd_generate(str(yaml_path), output_name="run-3", compilation_only=False)


# ---------------------------------------------------------------------------
# cmd_add_steps
# ---------------------------------------------------------------------------


def test_cmd_add_steps_returns_1_when_compilator_disabled(tmp_path, monkeypatch):
    yaml_path = _write_yaml_pair(tmp_path)
    monkeypatch.chdir(tmp_path)

    # The minimal config has no compilator section, so add-steps should
    # report an error without calling run_add_steps.
    sentinel = []

    def _should_not_be_called(*a, **kw):
        sentinel.append(("called", a, kw))

    monkeypatch.setattr(cli, "run_add_steps", _should_not_be_called)

    rc = cli.cmd_add_steps(str(yaml_path), str(tmp_path / "results" / "any"))
    assert rc == 1
    assert sentinel == []


# ---------------------------------------------------------------------------
# cmd_analyze
# ---------------------------------------------------------------------------


class _DummyAnalyzer(DataAnalyzer):
    last_call = None

    def analyze(self, dataset_dirs, params):
        type(self).last_call = {"dirs": list(dataset_dirs), "params": dict(params)}
        return AnalyzeResult(outputs={"ok": True, "n": len(dataset_dirs)})


def _make_dataset(tmp_path, name: str, analyzer_type: str = "dummy", params=None):
    root = tmp_path / name
    root.mkdir()
    ds_yaml = {
        "pipeline": {
            "analyzer": {
                "type": analyzer_type,
                "params": params or {},
            }
        }
    }
    (root / "dataset.yaml").write_text(yaml.safe_dump(ds_yaml))
    return root


def test_cmd_analyze_dispatches_to_registered_analyzer(tmp_path, monkeypatch):
    ds = _make_dataset(tmp_path, "d1", params={"k": "v"})
    monkeypatch.setitem(cli.ANALYZER_REGISTRY, "dummy", _DummyAnalyzer)

    rc = cli.cmd_analyze([str(ds)])
    assert rc == 0
    assert _DummyAnalyzer.last_call == {"dirs": [str(ds)], "params": {"k": "v"}}


def test_cmd_analyze_accepts_multiple_consistent_datasets(tmp_path, monkeypatch):
    a = _make_dataset(tmp_path, "a", params={})
    b = _make_dataset(tmp_path, "b", params={})
    monkeypatch.setitem(cli.ANALYZER_REGISTRY, "dummy", _DummyAnalyzer)

    rc = cli.cmd_analyze([str(a), str(b)])
    assert rc == 0
    assert _DummyAnalyzer.last_call["dirs"] == [str(a), str(b)]


def test_cmd_analyze_rejects_mixed_analyzer_types(tmp_path, monkeypatch):
    a = _make_dataset(tmp_path, "a", analyzer_type="dummy")
    b = _make_dataset(tmp_path, "b", analyzer_type="other")

    with pytest.raises(ValueError, match="must specify the same analyzer type"):
        cli.cmd_analyze([str(a), str(b)])


def test_cmd_analyze_rejects_unknown_analyzer_type(tmp_path, monkeypatch):
    a = _make_dataset(tmp_path, "a", analyzer_type="not-registered")
    # Make sure "not-registered" really isn't there.
    monkeypatch.delitem(cli.ANALYZER_REGISTRY, "not-registered", raising=False)

    with pytest.raises(ValueError, match="Unknown analyzer type"):
        cli.cmd_analyze([str(a)])


def test_cmd_analyze_raises_on_missing_dataset_yaml(tmp_path):
    bare = tmp_path / "no-yaml-here"
    bare.mkdir()

    with pytest.raises(FileNotFoundError, match="Missing dataset.yaml"):
        cli.cmd_analyze([str(bare)])


def test_cmd_analyze_raises_with_empty_input():
    with pytest.raises(ValueError, match="No dataset dirs"):
        cli.cmd_analyze([])


# ---------------------------------------------------------------------------
# main() dispatch
# ---------------------------------------------------------------------------


def test_main_dispatches_generate(monkeypatch):
    calls = {}

    def fake_generate(config_path, output_name=None, compilation_only=False):
        calls["generate"] = (config_path, output_name, compilation_only)
        return 0

    monkeypatch.setattr(cli, "cmd_generate", fake_generate)
    monkeypatch.setattr(
        "sys.argv", ["qs", "generate", "bench.yaml", "-o", "out", "--compilation-only"]
    )

    rc = cli.main()
    assert rc == 0
    assert calls["generate"] == ("bench.yaml", "out", True)


def test_main_dispatches_analyze(monkeypatch):
    captured = {}

    def fake_analyze(dirs):
        captured["dirs"] = dirs
        return 0

    monkeypatch.setattr(cli, "cmd_analyze", fake_analyze)
    monkeypatch.setattr("sys.argv", ["qs", "analyze", "a", "b"])

    rc = cli.main()
    assert rc == 0
    assert captured["dirs"] == ["a", "b"]


def test_main_dispatches_add_steps(monkeypatch):
    captured = {}

    def fake_add_steps(config, dataset, repeats_override=None):
        captured["args"] = (config, dataset, repeats_override)
        return 0

    monkeypatch.setattr(cli, "cmd_add_steps", fake_add_steps)
    monkeypatch.setattr(
        "sys.argv",
        ["qs", "add-steps", "bench.yaml", "results/run", "--repeats", "7"],
    )

    rc = cli.main()
    assert rc == 0
    assert captured["args"] == ("bench.yaml", "results/run", 7)


def test_main_requires_a_subcommand(monkeypatch):
    monkeypatch.setattr("sys.argv", ["qs"])
    with pytest.raises(SystemExit):
        cli.main()
