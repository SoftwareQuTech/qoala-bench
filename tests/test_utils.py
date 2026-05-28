"""Tests for the helpers in :mod:`qoala_bench.utils`.

These cover the small file-I/O helpers (``load_config``, ``load_yaml``,
``load_all_results_from_directory``) and the :class:`SimulationResult`
dataclass. No external services or compiled binaries are needed; every
test uses ``tmp_path`` and synthetic fixtures.
"""

from __future__ import annotations

import gzip
import json
import pickle
from dataclasses import FrozenInstanceError

import pytest

from qoala_bench.utils import (
    SimulationResult,
    load_all_results_from_directory,
    load_config,
    load_yaml,
)


def test_simulation_result_stores_success_and_duration():
    r = SimulationResult(success=True, duration=42)
    assert r.success is True
    assert r.duration == 42


def test_simulation_result_is_frozen():
    r = SimulationResult(success=True, duration=1)
    with pytest.raises(FrozenInstanceError):
        r.success = False  # type: ignore[misc]


def test_load_config_reads_json(tmp_path):
    payload = {"alpha": 1, "beta": [1, 2, 3], "gamma": {"nested": True}}
    path = tmp_path / "params.json"
    path.write_text(json.dumps(payload))

    assert load_config(str(path)) == payload


def test_load_config_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "does-not-exist.json"))


def test_load_yaml_reads_mapping(tmp_path):
    path = tmp_path / "doc.yaml"
    path.write_text("alpha: 1\nbeta:\n  - 2\n  - 3\n")

    loaded = load_yaml(str(path))
    assert loaded == {"alpha": 1, "beta": [2, 3]}


def test_load_yaml_handles_empty_file(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("")

    # PyYAML returns None for an empty document; this is contract-level
    # behaviour we want to preserve.
    assert load_yaml(str(path)) is None


def _write_gzipped_pickle(path, payload):
    with gzip.open(path, "wb") as f:
        pickle.dump(payload, f)


def test_load_all_results_returns_items_in_sorted_filename_order(tmp_path):
    _write_gzipped_pickle(tmp_path / "results-2.pkl.gz", {"iter": 2})
    _write_gzipped_pickle(tmp_path / "results-0.pkl.gz", {"iter": 0})
    _write_gzipped_pickle(tmp_path / "results-1.pkl.gz", {"iter": 1})

    loaded = load_all_results_from_directory(str(tmp_path))

    assert [r["iter"] for r in loaded] == [0, 1, 2]


def test_load_all_results_ignores_non_matching_files(tmp_path):
    _write_gzipped_pickle(tmp_path / "results-0.pkl.gz", "ok")
    (tmp_path / "readme.txt").write_text("not a result")
    (tmp_path / "results.pkl").write_bytes(b"\x80\x04")  # uncompressed pickle

    loaded = load_all_results_from_directory(str(tmp_path))
    assert loaded == ["ok"]


def test_load_all_results_returns_empty_list_for_empty_directory(tmp_path):
    assert load_all_results_from_directory(str(tmp_path)) == []


def test_load_all_results_reads_multiple_objects_per_file(tmp_path):
    path = tmp_path / "results-0.pkl.gz"
    with gzip.open(path, "wb") as f:
        pickle.dump({"i": 0}, f)
        pickle.dump({"i": 1}, f)
        pickle.dump({"i": 2}, f)

    loaded = load_all_results_from_directory(str(tmp_path))
    assert [r["i"] for r in loaded] == [0, 1, 2]
