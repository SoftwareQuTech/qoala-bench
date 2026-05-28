"""Tests for :mod:`qoala_bench.generators`.

Both bundled generators (:mod:`compare` and :mod:`heuristic`) import
:mod:`qoala_bench.mp_runner` at module load, which in turn pulls in
NetSquid and qoala-sim. The whole file is skipped when those aren't
available.

The end-to-end ``generate`` methods drive a NetSquid simulation and
need integration fixtures (real iqoala programs, working
multiprocessing). Here we cover the pure-Python helpers that the
generators delegate to for resolving program paths:

* :func:`compare._resolve_node_program_path` and the analogous
  function in :mod:`heuristic` — the legacy program-copy resolver
  (``copy_program_iqoala`` returns a mapping; the resolver picks the
  right entry).
* :func:`compare._resolve_node_file_path` — the compilator-state
  resolver, including the NEW-style string-omitted path that
  auto-detects the compilator variant when only one is present.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

# Skip the entire module if the heavy deps aren't available.
pytest.importorskip("qoala")
pytest.importorskip("netsquid")

from qoala_bench.config import FromCompilatorRef, NodeProgramFromCompilator  # noqa: E402
from qoala_bench.generators import compare as _compare  # noqa: E402
from qoala_bench.generators import heuristic as _heuristic  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(name="alice", file_path="alice.iqoala", num_qubits=1, inputs=None):
    """Build a duck-typed node object with the attributes the resolvers read."""
    return SimpleNamespace(
        node_name=name,
        file_path=file_path,
        num_qubits=num_qubits,
        inputs=inputs or {},
    )


def _comp_state(variant="bqc", source="client", paths=None):
    """Build a minimal comp_state dict that the resolvers can navigate."""
    return {
        "outputs": {
            variant: {
                source: paths or {},
            }
        }
    }


# ---------------------------------------------------------------------------
# compare._resolve_node_program_path  (legacy path resolution)
# ---------------------------------------------------------------------------


class TestCompareResolveProgramPath:
    """Exercises every branch of the legacy program-copy resolver."""

    def test_prefers_node_name_key_in_copied_map(self, tmp_path):
        copied = {"alice": tmp_path / "copied" / "alice.iqoala"}
        out = _compare._resolve_node_program_path(
            node_name="alice",
            file_path="alice.iqoala",
            copied=copied,
            task_dir=tmp_path,
        )
        assert out == str(copied["alice"])

    def test_falls_back_to_basename_key(self, tmp_path):
        # The copied map has only the basename, not the node name.
        copied = {"alice.iqoala": tmp_path / "alice.iqoala"}
        out = _compare._resolve_node_program_path(
            node_name="alice",
            file_path="alice.iqoala",
            copied=copied,
            task_dir=tmp_path,
        )
        assert out == str(copied["alice.iqoala"])

    def test_falls_back_to_task_dir_when_copied_has_no_entry(self, tmp_path):
        # Pre-create the file under task_dir so the existence check passes.
        (tmp_path / "alice.iqoala").write_text("# dummy")
        out = _compare._resolve_node_program_path(
            node_name="alice",
            file_path="alice.iqoala",
            copied={},
            task_dir=tmp_path,
        )
        assert out == str(tmp_path / "alice.iqoala")

    def test_raises_when_no_resolution_succeeds(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Cannot resolve program path"):
            _compare._resolve_node_program_path(
                node_name="alice",
                file_path="alice.iqoala",
                copied={},
                task_dir=tmp_path,
            )


# ---------------------------------------------------------------------------
# heuristic._resolve_node_program_path  (same shape as the compare version)
# ---------------------------------------------------------------------------


class TestHeuristicResolveProgramPath:
    def test_prefers_node_name_key_in_copied_map(self, tmp_path):
        copied = {"alice": tmp_path / "x.iqoala"}
        out = _heuristic._resolve_node_program_path(
            node_name="alice",
            file_path="alice.iqoala",
            copied=copied,
            task_dir=tmp_path,
        )
        assert out == str(copied["alice"])

    def test_raises_when_no_resolution_succeeds(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _heuristic._resolve_node_program_path(
                node_name="alice",
                file_path="alice.iqoala",
                copied={},
                task_dir=tmp_path,
            )


# ---------------------------------------------------------------------------
# compare._resolve_node_file_path  (compilator-state resolution)
# ---------------------------------------------------------------------------


class TestCompareResolveNodeFilePath:
    """The new translator-output resolver. Exercises every branch."""

    def test_legacy_string_path_returned_unchanged(self):
        n = _make_node(file_path="explicit/path.iqoala")
        out = _compare._resolve_node_file_path(
            n, comp_state={"outputs": {}}, program_variant="unoptimized"
        )
        assert out == "explicit/path.iqoala"

    def test_resolves_translator_output_from_single_variant(self):
        n = _make_node(name="client", file_path=None)
        comp_state = _comp_state(
            variant="bqc",
            source="client",
            paths={
                "translator": {
                    "unoptimized": "/build/client.unoptimized.iqoala",
                    "optimized": "/build/client.optimized.iqoala",
                },
            },
        )
        out = _compare._resolve_node_file_path(
            n, comp_state=comp_state, program_variant="optimized"
        )
        assert out == "/build/client.optimized.iqoala"

    def test_translator_resolution_requires_program_variant(self):
        n = _make_node(file_path=None)
        comp_state = _comp_state(paths={"translator": {"unoptimized": "x"}})
        with pytest.raises(ValueError, match="program_variant is required"):
            _compare._resolve_node_file_path(n, comp_state=comp_state)

    def test_translator_resolution_requires_explicit_variant_when_multiple(self):
        n = _make_node(file_path=None)
        comp_state = {
            "outputs": {
                "bqc": {"client": {"translator": {"unoptimized": "x"}}},
                "other": {"client": {"translator": {"unoptimized": "y"}}},
            }
        }
        with pytest.raises(ValueError, match="compilator_variant is required"):
            _compare._resolve_node_file_path(
                n, comp_state=comp_state, program_variant="unoptimized"
            )

    def test_translator_resolution_with_explicit_variant_picks_correct_path(self):
        n = _make_node(name="client", file_path=None)
        comp_state = {
            "outputs": {
                "bqc": {"client": {"translator": {"opt": "/bqc/c.iqoala"}}},
                "rot": {"client": {"translator": {"opt": "/rot/c.iqoala"}}},
            }
        }
        out = _compare._resolve_node_file_path(
            n,
            comp_state=comp_state,
            compilator_variant="rot",
            program_variant="opt",
        )
        assert out == "/rot/c.iqoala"

    def test_translator_resolution_missing_variant_raises(self):
        n = _make_node(name="client", file_path=None)
        comp_state = _comp_state(paths={"translator": {"opt": "x"}})
        with pytest.raises(KeyError):
            _compare._resolve_node_file_path(
                n, comp_state=comp_state, program_variant="MISSING"
            )

    def test_node_program_from_compilator_optimizer_stage(self):
        ref = FromCompilatorRef(
            variant="bqc",
            source="client",
            stage="optimizer",
            pass_name="step4_opt",
        )
        n = _make_node(file_path=NodeProgramFromCompilator(from_compilator=ref))
        comp_state = _comp_state(
            paths={"optimizer": {"step4_opt": "/build/step4_opt.mlir"}}
        )
        out = _compare._resolve_node_file_path(n, comp_state=comp_state)
        assert out == "/build/step4_opt.mlir"

    def test_node_program_from_compilator_translator_stage(self):
        ref = FromCompilatorRef(
            variant="bqc",
            source="client",
            stage="translator",
            program_variant="optimized",
        )
        n = _make_node(file_path=NodeProgramFromCompilator(from_compilator=ref))
        comp_state = _comp_state(
            paths={"translator": {"optimized": "/out/opt.iqoala"}}
        )
        out = _compare._resolve_node_file_path(n, comp_state=comp_state)
        assert out == "/out/opt.iqoala"

    def test_node_program_from_compilator_python_stage(self):
        ref = FromCompilatorRef(variant="bqc", source="client", stage="python")
        n = _make_node(file_path=NodeProgramFromCompilator(from_compilator=ref))
        comp_state = _comp_state(paths={"python": "/build/client.hir.mlir"})
        out = _compare._resolve_node_file_path(n, comp_state=comp_state)
        assert out == "/build/client.hir.mlir"

    def test_node_program_from_compilator_unknown_source_raises(self):
        ref = FromCompilatorRef(
            variant="bqc",
            source="missing-source",
            stage="translator",
            program_variant="optimized",
        )
        n = _make_node(file_path=NodeProgramFromCompilator(from_compilator=ref))
        comp_state = _comp_state(paths={"translator": {"optimized": "x"}})
        with pytest.raises(KeyError):
            _compare._resolve_node_file_path(n, comp_state=comp_state)

    def test_unsupported_file_path_type_raises(self):
        # file_path is something we don't recognise (int, here) — should be
        # rejected with a clear TypeError.
        n = _make_node(file_path=12345)
        with pytest.raises(TypeError, match="Unsupported file_path type"):
            _compare._resolve_node_file_path(
                n, comp_state={"outputs": {}}, program_variant="opt"
            )
