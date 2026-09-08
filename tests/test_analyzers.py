"""Tests for the bundled analyser implementations.

``NoopAnalyzer`` is trivially testable. ``SimpleAnalyzer`` depends on
the :class:`qoala.util.runner.AppResult` shape; we substitute a stub
that mimics the shape used by ``SimpleAnalyzer._extract_results`` so
the test does not require the qoala-sim runtime to be installed.
"""

from __future__ import annotations

import csv
import gzip
import pickle
from types import SimpleNamespace

import pytest

# ``analyzers.simple`` imports ``qoala.util.runner.AppResult``; skip the
# whole module if qoala-sim isn't installed locally.
pytest.importorskip("qoala")

# These imports register the analysers in the registry as a side effect.
import qoala_bench.analyzers.noop  # noqa: E402, F401
import qoala_bench.analyzers.simple  # noqa: E402, F401
from qoala_bench.analyzers.base import AnalyzeResult, DataAnalyzer  # noqa: E402
from qoala_bench.analyzers.noop import NoopAnalyzer  # noqa: E402
from qoala_bench.registry import ANALYZER_REGISTRY  # noqa: E402

# ---------------------------------------------------------------------------
# Base class / registry wiring
# ---------------------------------------------------------------------------


def test_noop_analyzer_registered_under_noop_name():
    assert ANALYZER_REGISTRY["noop"] is NoopAnalyzer


def test_simple_analyzer_registered_under_simple_name():
    # The class object is registered, not an instance; we check by name to
    # avoid coupling this test to the SimpleAnalyzer import path.
    assert "simple" in ANALYZER_REGISTRY
    assert issubclass(ANALYZER_REGISTRY["simple"], DataAnalyzer)


# ---------------------------------------------------------------------------
# NoopAnalyzer
# ---------------------------------------------------------------------------


def test_noop_analyzer_returns_dataset_list_unchanged():
    result = NoopAnalyzer().analyze(["a", "b", "c"], {"any": "params"})
    assert isinstance(result, AnalyzeResult)
    assert result.outputs == {"datasets": ["a", "b", "c"], "note": "noop analyzer"}


def test_noop_analyzer_with_empty_input():
    result = NoopAnalyzer().analyze([], {})
    assert result.outputs == {"datasets": [], "note": "noop analyzer"}


# ---------------------------------------------------------------------------
# SimpleAnalyzer
# ---------------------------------------------------------------------------


def _make_fake_app_result(node: str, outcomes: list, timestamps: list):
    """Build a stub that mimics qoala's AppResult shape.

    ``SimpleAnalyzer._extract_results`` only reads
    ``app_result.batch_results[node].results`` (a list of objects with a
    ``.values`` dict) and ``app_result.batch_results[node].timestamps``
    (a list of ``(start, end)`` tuples). Anything compatible with those
    accessors will do.
    """
    batch = SimpleNamespace(
        results=[SimpleNamespace(values=v) for v in outcomes],
        timestamps=timestamps,
    )
    return SimpleNamespace(batch_results={node: batch})


def _write_pkl_gz(path, payload):
    with gzip.open(path, "wb") as f:
        pickle.dump(payload, f)


def _make_dataset_dir(tmp_path, label, app_results):
    """Build a dataset folder containing one task with the given results."""
    raw = tmp_path / "raw" / label
    raw.mkdir(parents=True)
    for i, ar in enumerate(app_results):
        _write_pkl_gz(raw / f"results-{i}.pkl.gz", ar)
    (tmp_path / "analysis").mkdir(parents=True)
    return tmp_path


def test_simple_analyzer_computes_success_rate(tmp_path):
    SimpleAnalyzer = ANALYZER_REGISTRY["simple"]
    analyzer = SimpleAnalyzer()

    # Three iterations: two successes (value == 0), one failure (value == 1).
    fakes = [
        _make_fake_app_result("client", [{"%3": 0}], [(0, 10)]),
        _make_fake_app_result("client", [{"%3": 0}], [(0, 20)]),
        _make_fake_app_result("client", [{"%3": 1}], [(0, 30)]),
    ]
    dataset = _make_dataset_dir(tmp_path, "unoptimized", fakes)

    res = analyzer.analyze(
        [str(dataset)],
        {"node": "client", "outcome_key": "%3", "success_value": 0},
    )

    summaries = res.outputs["summaries"]
    assert len(summaries) == 1
    s = summaries[0]
    assert s["task"] == "unoptimized"
    assert s["iterations"] == 3
    assert s["success_count"] == 2
    assert s["fail_count"] == 1
    assert s["success_percentage"] == pytest.approx(66.66666, rel=1e-3)
    assert s["mean_duration"] == pytest.approx(20.0)


def test_simple_analyzer_writes_per_label_csv(tmp_path):
    SimpleAnalyzer = ANALYZER_REGISTRY["simple"]
    analyzer = SimpleAnalyzer()

    fakes = [
        _make_fake_app_result("client", [{"%3": 0}], [(0, 10)]),
        _make_fake_app_result("client", [{"%3": 1}], [(0, 20)]),
    ]
    dataset = _make_dataset_dir(tmp_path, "optimized", fakes)

    analyzer.analyze(
        [str(dataset)],
        {"node": "client", "outcome_key": "%3", "success_value": 0},
    )

    csv_path = dataset / "analysis" / "optimized_results.csv"
    assert csv_path.is_file()
    with open(csv_path, newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["success", "duration"]
    # 2 data rows
    assert len(rows) == 3
    assert rows[1] == ["True", "10"]
    assert rows[2] == ["False", "20"]


def test_simple_analyzer_writes_summary_csv_for_multiple_tasks(tmp_path):
    SimpleAnalyzer = ANALYZER_REGISTRY["simple"]
    analyzer = SimpleAnalyzer()

    fakes_a = [_make_fake_app_result("client", [{"%3": 0}], [(0, 10)])]
    fakes_b = [_make_fake_app_result("client", [{"%3": 1}], [(0, 20)])]

    # Both tasks live in the same dataset folder under raw/<label>/.
    raw = tmp_path / "raw"
    (raw / "a").mkdir(parents=True)
    (raw / "b").mkdir(parents=True)
    _write_pkl_gz(raw / "a" / "results-0.pkl.gz", fakes_a[0])
    _write_pkl_gz(raw / "b" / "results-0.pkl.gz", fakes_b[0])
    (tmp_path / "analysis").mkdir()

    analyzer.analyze(
        [str(tmp_path)],
        {"node": "client", "outcome_key": "%3", "success_value": 0},
    )

    summary_csv = tmp_path / "analysis" / "summary.csv"
    assert summary_csv.is_file()
    with open(summary_csv, newline="") as f:
        rows = list(csv.DictReader(f))
    labels = {r["task"] for r in rows}
    assert labels == {"a", "b"}


def test_simple_analyzer_per_label_outcome_key_override(tmp_path):
    SimpleAnalyzer = ANALYZER_REGISTRY["simple"]
    analyzer = SimpleAnalyzer()

    # The "unoptimized" task uses outcome key "%3"; the override map says
    # "use %7 for the unoptimized label specifically".
    fakes = [
        _make_fake_app_result("client", [{"%3": 1, "%7": 0}], [(0, 10)]),
    ]
    dataset = _make_dataset_dir(tmp_path, "unoptimized", fakes)

    res = analyzer.analyze(
        [str(dataset)],
        {
            "node": "client",
            "outcome_key": "%3",
            "success_value": 0,
            "outcome_key_by_label": {"unoptimized": "%7"},
        },
    )
    # With the override, %7 == 0 is the success path, so success_count = 1.
    s = res.outputs["summaries"][0]
    assert s["success_count"] == 1
