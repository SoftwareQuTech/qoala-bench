"""Tests for :mod:`qoala_bench.params_schema`.

The schema validator is pure-Python and dependency-free, so we can
exercise every failure mode in isolation. Each test constructs a
valid baseline config (via :func:`_valid_config`) and mutates one
field to provoke the targeted error.
"""

from __future__ import annotations

import pytest

from qoala_bench.params_schema import (
    REQUIRED_CONFIG_KEYS,
    ConfigValidationError,
    validate_simulation_config,
)


def _valid_config() -> dict:
    """A baseline valid config; tests mutate copies of this."""
    return {
        "t1": 1e9,
        "t2": 1e9,
        "single_gate_duration": 100,
        "two_gate_duration": 200,
        "single_gate_fid": 0.99,
        "two_gate_fid": 0.95,
        "single_gate_error": 0.01,
        "two_gate_error": 0.05,
        "host_instr_time": 1,
        "host_peer_latency": 1,
        "qnos_instr_time": 1,
        "latency": 100,
        "link_duration": 1000,
        "link_fid": 0.9,
    }


def test_valid_config_passes_through_unchanged():
    cfg = _valid_config()
    result = validate_simulation_config(cfg)
    assert result == cfg


def test_returns_plain_dict_when_given_mapping():
    cfg = _valid_config()
    # Returns a *new* dict — the caller can mutate it freely.
    result = validate_simulation_config(cfg)
    assert isinstance(result, dict)
    assert result is not cfg


def test_required_keys_constant_matches_baseline():
    # Catches accidental drift between REQUIRED_CONFIG_KEYS and the
    # baseline used in this test module.
    assert set(_valid_config().keys()) == REQUIRED_CONFIG_KEYS


@pytest.mark.parametrize("missing_key", sorted(REQUIRED_CONFIG_KEYS))
def test_missing_required_key_raises(missing_key):
    cfg = _valid_config()
    del cfg[missing_key]
    with pytest.raises(ConfigValidationError, match="missing keys"):
        validate_simulation_config(cfg)


def test_extra_keys_rejected_by_default():
    cfg = _valid_config()
    cfg["extra_unknown_field"] = 1
    with pytest.raises(ConfigValidationError, match="unexpected extra keys"):
        validate_simulation_config(cfg)


def test_extra_keys_accepted_when_allowed():
    cfg = _valid_config()
    cfg["extra_unknown_field"] = 1
    result = validate_simulation_config(cfg, allow_extra_keys=True)
    assert result["extra_unknown_field"] == 1


@pytest.mark.parametrize("key", sorted(REQUIRED_CONFIG_KEYS))
def test_non_numeric_value_rejected(key):
    cfg = _valid_config()
    cfg[key] = "not-a-number"
    with pytest.raises(ConfigValidationError, match="non-numeric"):
        validate_simulation_config(cfg)


@pytest.mark.parametrize("fid_key", ["single_gate_fid", "two_gate_fid", "link_fid"])
def test_fidelity_out_of_range_rejected(fid_key):
    for bad in (-0.1, 0.0, 1.1, 2.0):
        cfg = _valid_config()
        cfg[fid_key] = bad
        with pytest.raises(ConfigValidationError, match="must be in"):
            validate_simulation_config(cfg)


@pytest.mark.parametrize("err_key", ["single_gate_error", "two_gate_error"])
def test_error_rate_out_of_range_rejected(err_key):
    for bad in (-0.01, 1.0, 1.5):
        cfg = _valid_config()
        cfg[err_key] = bad
        with pytest.raises(ConfigValidationError, match="must be in"):
            validate_simulation_config(cfg)


@pytest.mark.parametrize(
    "nonneg_key",
    [
        "t1",
        "t2",
        "single_gate_duration",
        "two_gate_duration",
        "host_instr_time",
        "host_peer_latency",
        "qnos_instr_time",
        "latency",
        "link_duration",
    ],
)
def test_negative_duration_rejected(nonneg_key):
    cfg = _valid_config()
    cfg[nonneg_key] = -1
    with pytest.raises(ConfigValidationError, match="must be >="):
        validate_simulation_config(cfg)


def test_zero_duration_accepted():
    cfg = _valid_config()
    for k in (
        "single_gate_duration",
        "two_gate_duration",
        "host_instr_time",
        "host_peer_latency",
        "qnos_instr_time",
        "latency",
        "link_duration",
    ):
        cfg[k] = 0
    # No exception expected.
    validate_simulation_config(cfg)


def test_integer_and_float_both_accepted():
    cfg = _valid_config()
    cfg["t1"] = 1_000_000_000  # int
    cfg["t2"] = 1.5e9  # float
    validate_simulation_config(cfg)
