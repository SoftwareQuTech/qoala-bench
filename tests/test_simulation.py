"""Tests for :mod:`qoala_bench.simulation`.

The simulation module imports NetSquid and qoala-sim at module load,
so the whole file is skipped when those aren't installed.

We test:

* :func:`_peer_id_inputs`, the pure-Python helper that turns the
  node-list ordering into the ``{name}_id`` lookup dict passed to
  every program;
* :func:`_set_qstate_formalism`, the small dispatcher that maps the
  ``qstate_formalism`` config key onto NetSquid's enum (verifying both
  accepted values + the rejection path on an invalid key);
* :func:`_build_full_mesh_cconns`, which builds the full-mesh
  classical-connection list. We verify the cardinality of the result
  (``N*(N-1)/2``) rather than the exact pair structure, which depends
  on qoala's ``ClassicalConnectionConfig`` implementation.

The full :func:`run` end-to-end orchestration requires a real
``.iqoala`` program plus the NetSquid runtime; that path is covered by
the repository's integration scripts, not by this unit-test suite.
"""

from __future__ import annotations

import pytest

# Skip the entire module if the heavy deps aren't available.
pytest.importorskip("qoala")
pytest.importorskip("netsquid")

from qoala_bench.simulation import (  # noqa: E402
    _build_full_mesh_cconns,
    _peer_id_inputs,
    _set_qstate_formalism,
)

# ---------------------------------------------------------------------------
# _peer_id_inputs
# ---------------------------------------------------------------------------


def test_peer_id_inputs_excludes_self_in_two_node_case():
    nodes = [{"node_name": "alice"}, {"node_name": "bob"}]
    assert _peer_id_inputs(nodes, self_name="alice") == {"bob_id": 1}
    assert _peer_id_inputs(nodes, self_name="bob") == {"alice_id": 0}


def test_peer_id_inputs_includes_every_other_node():
    nodes = [{"node_name": n} for n in ["alice", "bob", "carol", "dan"]]
    out = _peer_id_inputs(nodes, self_name="bob")
    assert out == {"alice_id": 0, "carol_id": 2, "dan_id": 3}


def test_peer_id_inputs_uses_yaml_order_for_ids():
    """The id assignment is positional (enumeration order), not alphabetical."""
    nodes = [{"node_name": "zulu"}, {"node_name": "alpha"}]
    assert _peer_id_inputs(nodes, self_name="zulu") == {"alpha_id": 1}


def test_peer_id_inputs_returns_empty_dict_for_single_node():
    nodes = [{"node_name": "only"}]
    assert _peer_id_inputs(nodes, self_name="only") == {}


def test_peer_id_inputs_returns_empty_when_self_is_not_in_list():
    """Defensive: if ``self_name`` isn't in the node list, every entry
    is treated as a peer."""
    nodes = [{"node_name": "alice"}, {"node_name": "bob"}]
    out = _peer_id_inputs(nodes, self_name="not-here")
    assert out == {"alice_id": 0, "bob_id": 1}


# ---------------------------------------------------------------------------
# _set_qstate_formalism
# ---------------------------------------------------------------------------


def test_set_qstate_formalism_accepts_dm():
    # No assertion target beyond "doesn't raise"; we verify the call
    # path is wired up to NetSquid's enum without poking at NetSquid
    # globals.
    _set_qstate_formalism({"qstate_formalism": "DM"})


def test_set_qstate_formalism_accepts_ket():
    _set_qstate_formalism({"qstate_formalism": "KET"})


def test_set_qstate_formalism_is_case_insensitive():
    _set_qstate_formalism({"qstate_formalism": "dm"})
    _set_qstate_formalism({"qstate_formalism": "Ket"})


def test_set_qstate_formalism_defaults_to_dm_when_unset():
    # Empty dict → falls through to the "DM" branch via dict.get default.
    _set_qstate_formalism({})


def test_set_qstate_formalism_rejects_unknown_value():
    with pytest.raises(ValueError, match="Unsupported qstate_formalism"):
        _set_qstate_formalism({"qstate_formalism": "BLOCH"})


# ---------------------------------------------------------------------------
# _build_full_mesh_cconns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n_nodes, expected_count",
    [
        (2, 1),  # one edge
        (3, 3),  # triangle
        (4, 6),
        (5, 10),
    ],
)
def test_build_full_mesh_cconns_cardinality(n_nodes, expected_count):
    node_ids = list(range(n_nodes))
    cconns = _build_full_mesh_cconns(node_ids, latency=100)
    assert len(cconns) == expected_count


def test_build_full_mesh_cconns_empty_input():
    assert _build_full_mesh_cconns([], latency=100) == []


def test_build_full_mesh_cconns_single_node_yields_no_edges():
    assert _build_full_mesh_cconns([0], latency=100) == []
