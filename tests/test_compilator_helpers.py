"""Tests for the pure helpers in :mod:`qoala_bench.compilator`.

These functions are private to the compilator module but are all
deterministic, dependency-free helpers — exactly the kind of code where
unit tests pay off most. The big orchestration functions
(``run_compilator``, ``run_add_steps``, ``_compile_one_source``) drive
subprocesses, threads, and process pools and are out of scope here;
those would need integration fixtures with real or mocked
``qoala-opt``/``qoala-translate`` binaries.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from qoala_bench.compilator import (
    _format_cli_value,
    _json_get,
    _resolve_relative_to_yaml,
    _sha256_bytes,
    _sha256_file,
    _stats,
    _step_label,
    _subst,
)


# ---------------------------------------------------------------------------
# _sha256_bytes / _sha256_file
# ---------------------------------------------------------------------------


def test_sha256_bytes_known_vector():
    # SHA-256 of an empty byte string is a well-known constant.
    expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert _sha256_bytes(b"") == expected


def test_sha256_bytes_distinguishes_inputs():
    assert _sha256_bytes(b"alpha") != _sha256_bytes(b"beta")


def test_sha256_file_returns_none_for_missing_file(tmp_path):
    assert _sha256_file(tmp_path / "does-not-exist.bin") is None


def test_sha256_file_matches_sha256_bytes(tmp_path):
    path = tmp_path / "blob.bin"
    payload = b"qoala-bench test payload"
    path.write_bytes(payload)
    assert _sha256_file(path) == _sha256_bytes(payload)


def test_sha256_file_returns_none_for_directory(tmp_path):
    assert _sha256_file(tmp_path) is None


# ---------------------------------------------------------------------------
# _stats
# ---------------------------------------------------------------------------


def test_stats_returns_empty_dict_for_empty_input():
    assert _stats([]) == {}


def test_stats_single_sample_yields_constant_percentiles():
    s = _stats([1.5])
    assert s["n"] == 1
    assert s["min_s"] == 1.5
    assert s["max_s"] == 1.5
    assert s["mean_s"] == 1.5
    assert s["stdev_s"] == 0.0
    # With only one sample every percentile collapses to that sample.
    assert s["p50_s"] == 1.5
    assert s["p90_s"] == 1.5
    assert s["p95_s"] == 1.5


def test_stats_basic_statistics_on_known_input():
    times = [1.0, 2.0, 3.0, 4.0, 5.0]
    s = _stats(times)
    assert s["n"] == 5
    assert s["min_s"] == 1.0
    assert s["max_s"] == 5.0
    assert s["mean_s"] == pytest.approx(3.0)
    # Population stdev of [1,2,3,4,5]: sqrt(2)
    assert s["stdev_s"] == pytest.approx(math.sqrt(2))
    # p50 of [1..5] is the middle element (linear interpolation between
    # indices (n-1)*0.5 = 2 → ts_sorted[2] = 3.0).
    assert s["p50_s"] == 3.0


def test_stats_percentile_interpolates_between_samples():
    # For [10, 20], (n-1)*p=1*0.5=0.5 → 10 + (20-10)*0.5 = 15.
    s = _stats([10.0, 20.0])
    assert s["p50_s"] == 15.0


# ---------------------------------------------------------------------------
# _resolve_relative_to_yaml
# ---------------------------------------------------------------------------


def test_resolve_relative_to_yaml_passes_absolute_through(tmp_path):
    yaml = tmp_path / "bench.yaml"
    abs_path = "/etc/hostname"  # any abs path — we don't read it
    out = _resolve_relative_to_yaml(yaml, abs_path)
    assert out == Path(abs_path)


def test_resolve_relative_to_yaml_anchors_relative_at_yaml_dir(tmp_path):
    yaml = tmp_path / "subdir" / "bench.yaml"
    yaml.parent.mkdir(parents=True)
    out = _resolve_relative_to_yaml(yaml, "sibling.json")
    assert out == (tmp_path / "subdir" / "sibling.json").resolve()


# ---------------------------------------------------------------------------
# _json_get
# ---------------------------------------------------------------------------


def test_json_get_dotted_path():
    d = {"a": {"b": {"c": 7}}}
    assert _json_get(d, "a.b.c") == 7


def test_json_get_top_level_key():
    assert _json_get({"x": 42}, "x") == 42


def test_json_get_missing_key_raises():
    with pytest.raises(KeyError, match="a.missing"):
        _json_get({"a": {}}, "a.missing")


def test_json_get_into_non_dict_raises():
    with pytest.raises(KeyError, match="a.b"):
        _json_get({"a": "string"}, "a.b")


# ---------------------------------------------------------------------------
# _format_cli_value
# ---------------------------------------------------------------------------


def test_format_cli_value_bool_true_lowercase():
    assert _format_cli_value(True) == "true"


def test_format_cli_value_bool_false_lowercase():
    assert _format_cli_value(False) == "false"


def test_format_cli_value_int_unchanged():
    assert _format_cli_value(42) == "42"


def test_format_cli_value_whole_float_becomes_int():
    # Many CLI flags reject scientific notation; whole-number floats
    # must be emitted as plain ints.
    assert _format_cli_value(1.0) == "1"
    assert _format_cli_value(1e10) == "10000000000"


def test_format_cli_value_fractional_float_uses_g_format():
    assert _format_cli_value(0.5) == "0.5"
    assert _format_cli_value(1.5) == "1.5"


def test_format_cli_value_string_passes_through():
    assert _format_cli_value("foo") == "foo"


# ---------------------------------------------------------------------------
# _subst
# ---------------------------------------------------------------------------


def test_subst_mapping_tokens_replaced():
    s = _subst(
        "{source_name}.{variant}.iqoala",
        json_cfg={},
        variables={},
        mapping={"source_name": "client", "variant": "bqc"},
    )
    assert s == "client.bqc.iqoala"


def test_subst_var_tokens_replaced_and_formatted():
    s = _subst(
        "n={var:n} flag={var:on}",
        json_cfg={},
        variables={"n": 3, "on": True},
        mapping={},
    )
    assert s == "n=3 flag=true"


def test_subst_unknown_var_raises_key_error():
    with pytest.raises(KeyError, match="var:unknown"):
        _subst(
            "{var:unknown}",
            json_cfg={},
            variables={"known": 1},
            mapping={},
        )


def test_subst_json_tokens_replaced():
    s = _subst(
        "--t1={json:t1} --gate={json:gates.single.dur}",
        json_cfg={"t1": 1e9, "gates": {"single": {"dur": 100}}},
        variables={},
        mapping={},
    )
    assert s == "--t1=1000000000 --gate=100"


def test_subst_multiple_tokens_of_same_kind():
    s = _subst(
        "{var:a}-{var:b}-{var:a}",
        json_cfg={},
        variables={"a": "alpha", "b": "beta"},
        mapping={},
    )
    assert s == "alpha-beta-alpha"


def test_subst_no_tokens_returns_input_unchanged():
    assert _subst("plain string", json_cfg={}, variables={}, mapping={}) == "plain string"


# ---------------------------------------------------------------------------
# _step_label
# ---------------------------------------------------------------------------


def test_step_label_known_key():
    assert _step_label("python") == "Python → HIR"


def test_step_label_translator_prefix_formatted():
    assert _step_label("translator:unoptimized") == "Translate (unoptimized)"


def test_step_label_optimizer_prefix_formatted():
    assert _step_label("optimizer:my-custom-pass") == "Optimize (my-custom-pass)"


def test_step_label_unknown_returned_as_is():
    assert _step_label("something:else") == "something:else"
