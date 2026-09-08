"""Tests for :mod:`qoala_bench.mp_runner`.

``mp_runner`` imports :mod:`qoala_bench.simulation`, which in turn
imports NetSquid and qoala-sim. If those aren't installed, the whole
module is skipped via :func:`pytest.importorskip` calls below.

We test:

* the :class:`NodeSpec` / :class:`TaskSpec` dataclasses (frozen,
  field-preserving);
* :func:`_queue_listener`, which is the listener side of the
  producer-consumer loop used by the multiprocess driver. We drive it
  synchronously from the test thread by pushing messages onto a real
  :class:`multiprocessing.Queue` and asserting on the gzipped files it
  produces.

The full :func:`run_tasks_multiprocess` orchestration spins up
subprocesses that load real ``.iqoala`` programs into the NetSquid
runtime; that path needs integration fixtures and is out of scope for
a unit-test suite.
"""

from __future__ import annotations

import gzip
import json
import multiprocessing
import pickle

import pytest

# Skip the entire module if the heavy deps aren't available.
pytest.importorskip("qoala")
pytest.importorskip("netsquid")

from qoala_bench.mp_runner import NodeSpec, TaskSpec, _queue_listener  # noqa: E402

# ---------------------------------------------------------------------------
# NodeSpec / TaskSpec
# ---------------------------------------------------------------------------


def test_node_spec_stores_fields():
    n = NodeSpec(
        node_name="client",
        file_path="/tmp/client.iqoala",
        num_qubits=2,
        inputs={"x": 1},
    )
    assert n.node_name == "client"
    assert n.file_path == "/tmp/client.iqoala"
    assert n.num_qubits == 2
    assert n.inputs == {"x": 1}


def test_node_spec_is_frozen():
    n = NodeSpec(node_name="a", file_path="/p", num_qubits=1, inputs={})
    with pytest.raises(Exception):
        n.num_qubits = 10  # type: ignore[misc]


def test_task_spec_stores_fields():
    nodes = [
        NodeSpec("a", "/a.iqoala", 1, {}),
        NodeSpec("b", "/b.iqoala", 1, {}),
    ]
    config = {"t1": 1, "latency": 100}
    t = TaskSpec(label="lab", nodes=nodes, config=config)
    assert t.label == "lab"
    assert t.nodes == nodes
    assert t.config == config


def test_task_spec_is_frozen():
    t = TaskSpec(label="lab", nodes=[], config={})
    with pytest.raises(Exception):
        t.label = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _queue_listener
# ---------------------------------------------------------------------------


def _drain_listener(messages):
    """Run :func:`_queue_listener` against a real mp Queue.

    Pushes ``messages`` onto the queue (the caller is responsible for
    ending with ``"STOP"``), then runs the listener in the calling
    thread so it drains every queued message and exits.
    """
    q: multiprocessing.Queue = multiprocessing.Queue()
    for m in messages:
        q.put(m)
    _queue_listener(q)


def test_queue_listener_writes_pickled_result(tmp_path):
    out_dir = tmp_path / "raw" / "task"
    _drain_listener(
        [
            {
                "type": "result",
                "label": "task",
                "out_dir": str(out_dir),
                "result": {"outcome": 0, "duration": 42},
            },
            "STOP",
        ]
    )

    result_file = out_dir / "app_results.pkl.gz"
    assert result_file.is_file()
    with gzip.open(result_file, "rb") as f:
        loaded = pickle.load(f)
    assert loaded == {"outcome": 0, "duration": 42}


def test_queue_listener_appends_multiple_results_to_same_file(tmp_path):
    out_dir = tmp_path / "raw" / "task"
    _drain_listener(
        [
            {
                "type": "result",
                "label": "t",
                "out_dir": str(out_dir),
                "result": {"i": 1},
            },
            {
                "type": "result",
                "label": "t",
                "out_dir": str(out_dir),
                "result": {"i": 2},
            },
            "STOP",
        ]
    )

    loaded = []
    with gzip.open(out_dir / "app_results.pkl.gz", "rb") as f:
        while True:
            try:
                loaded.append(pickle.load(f))
            except EOFError:
                break
    assert loaded == [{"i": 1}, {"i": 2}]


def test_queue_listener_writes_seed_record_jsonl(tmp_path):
    out_dir = tmp_path / "raw" / "t"
    record = {"iteration": 0, "seed": 1234, "status": "ok"}
    _drain_listener(
        [
            {
                "type": "seed",
                "label": "t",
                "out_dir": str(out_dir),
                "seed_record": record,
            },
            "STOP",
        ]
    )

    seed_file = out_dir / "seeds.jsonl.gz"
    assert seed_file.is_file()
    with gzip.open(seed_file, "rt", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0]) == record


def test_queue_listener_skips_result_when_payload_is_none(tmp_path):
    """A ``"result"`` message with ``result=None`` must not crash and
    must not create an empty ``app_results.pkl.gz`` file."""
    out_dir = tmp_path / "raw" / "t"
    _drain_listener(
        [
            {"type": "result", "label": "t", "out_dir": str(out_dir), "result": None},
            "STOP",
        ]
    )
    # Directory exists (created by os.makedirs(out_dir, exist_ok=True)),
    # but no result file should be written.
    assert out_dir.is_dir()
    assert not (out_dir / "app_results.pkl.gz").exists()


def test_queue_listener_creates_missing_out_dir(tmp_path):
    out_dir = tmp_path / "deeply" / "nested" / "raw" / "t"
    _drain_listener(
        [
            {
                "type": "result",
                "label": "t",
                "out_dir": str(out_dir),
                "result": {"x": 1},
            },
            "STOP",
        ]
    )
    assert (out_dir / "app_results.pkl.gz").is_file()


def test_queue_listener_handles_interleaved_message_types(tmp_path):
    out_dir = tmp_path / "raw" / "t"
    _drain_listener(
        [
            {
                "type": "result",
                "label": "t",
                "out_dir": str(out_dir),
                "result": {"i": 0},
            },
            {
                "type": "seed",
                "label": "t",
                "out_dir": str(out_dir),
                "seed_record": {"iteration": 0, "status": "ok"},
            },
            {
                "type": "result",
                "label": "t",
                "out_dir": str(out_dir),
                "result": {"i": 1},
            },
            {
                "type": "seed",
                "label": "t",
                "out_dir": str(out_dir),
                "seed_record": {"iteration": 1, "status": "ok"},
            },
            "STOP",
        ]
    )

    # Both files exist and have the expected number of records.
    with gzip.open(out_dir / "app_results.pkl.gz", "rb") as f:
        results = []
        while True:
            try:
                results.append(pickle.load(f))
            except EOFError:
                break
    assert len(results) == 2

    with gzip.open(out_dir / "seeds.jsonl.gz", "rt", encoding="utf-8") as f:
        seed_lines = [line for line in f if line.strip()]
    assert len(seed_lines) == 2
