from __future__ import annotations

from typing import Any, Dict, Mapping

REQUIRED_CONFIG_KEYS = {
    "t1",
    "t2",
    "single_gate_duration",
    "two_gate_duration",
    "single_gate_fid",
    "two_gate_fid",
    "single_gate_error",
    "two_gate_error",
    "host_instr_time",
    "host_peer_latency",
    "qnos_instr_time",
    "latency",
    "link_duration",
    "link_fid",
}

# Expected numeric types (allow int or float; we'll coerce to float where sensible)
NUMERIC_KEYS = REQUIRED_CONFIG_KEYS

FIDELITY_KEYS = {"single_gate_fid", "two_gate_fid", "link_fid"}
ERROR_KEYS = {"single_gate_error", "two_gate_error"}


class ConfigValidationError(ValueError):
    pass


def validate_simulation_config(
    cfg: Mapping[str, Any],
    *,
    allow_extra_keys: bool = False,
) -> Dict[str, Any]:
    """
    Validates the simulation params JSON dict.

    - Requires the fixed set of keys.
    - Ensures values are numeric.
    - Ensures fidelities are in (0, 1] (optional but sensible).
    - Returns a plain dict (can be used as-is).

    Raises ConfigValidationError with a clear message on failure.
    """
    cfg = dict(cfg)

    missing = REQUIRED_CONFIG_KEYS - cfg.keys()
    if missing:
        raise ConfigValidationError(f"Config is missing keys: {sorted(missing)}")

    if not allow_extra_keys:
        extra = set(cfg.keys()) - REQUIRED_CONFIG_KEYS
        if extra:
            raise ConfigValidationError(
                f"Config has unexpected extra keys: {sorted(extra)}"
            )

    # type checks: must be int/float-like
    bad_types = []
    for k in NUMERIC_KEYS:
        v = cfg.get(k)
        if not isinstance(v, (int, float)):
            bad_types.append((k, type(v).__name__))
    if bad_types:
        pretty = ", ".join([f"{k}={t}" for k, t in bad_types])
        raise ConfigValidationError(f"Config has non-numeric values: {pretty}")

    # basic sanity checks (can be relaxed if you want)
    for k in FIDELITY_KEYS:
        v = float(cfg[k])
        if not (0.0 < v <= 1.0):
            raise ConfigValidationError(f"{k} must be in (0, 1], got {cfg[k]}")

    # error rates must be in [0, 1)
    for k in ERROR_KEYS:
        v = float(cfg[k])
        if not (0.0 <= v < 1.0):
            raise ConfigValidationError(f"{k} must be in [0, 1), got {cfg[k]}")

    # durations/latencies should be >= 0
    nonneg_keys = {
        "t1",
        "t2",
        "single_gate_duration",
        "two_gate_duration",
        "host_instr_time",
        "host_peer_latency",
        "qnos_instr_time",
        "latency",
        "link_duration",
    }
    for k in nonneg_keys:
        if float(cfg[k]) < 0:
            raise ConfigValidationError(f"{k} must be >= 0, got {cfg[k]}")

    return cfg
