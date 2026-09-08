"""Tests for the Pydantic models in :mod:`qoala_bench.config`.

Covers the model-level validators (node-list invariants, the
discriminated-union generator type, the heuristic generator's "one of"
constraint) and the YAML loader. Each test builds a minimal valid
config in code and mutates one field to provoke the targeted failure.
"""

from __future__ import annotations

import copy

import pytest
import yaml
from pydantic import ValidationError

from qoala_bench.config import (
    AnalyzerModel,
    NodeConfigModel,
    ParamsModel,
    RootConfig,
    inject_run_metadata,
    load_config_yaml,
)


def _minimal_root_config_dict() -> dict:
    """Smallest dict that successfully validates as ``RootConfig``."""
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
        "execution": {
            "iterations": 1,
            "cpu_count": 1,
        },
        "pipeline": {
            "generator": {
                "type": "compare",
                "params": {
                    "programs": [
                        {"label": "a", "program_variant": "unoptimized"},
                    ],
                },
            },
            "analyzer": {
                "type": "simple",
                "params": {"node": "client", "outcome_key": "%3", "success_value": 0},
            },
        },
    }


def test_minimal_root_config_validates():
    cfg = RootConfig.model_validate(_minimal_root_config_dict())
    assert cfg.name == "test-bench"
    assert cfg.params.qstate_formalism == "DM"
    assert cfg.execution.iterations == 1
    assert len(cfg.params.nodes) == 2


def test_root_config_injected_fields_default_to_none():
    cfg = RootConfig.model_validate(_minimal_root_config_dict())
    assert cfg.uuid is None
    assert cfg.ran is None
    assert cfg.dataset_version is None


def test_load_config_yaml_round_trips(tmp_path):
    path = tmp_path / "bench.yaml"
    path.write_text(yaml.safe_dump(_minimal_root_config_dict()))

    cfg = load_config_yaml(str(path))
    assert cfg.name == "test-bench"
    assert cfg.params.nodes[0].node_name == "client"


def test_inject_run_metadata_fills_uuid_ran_and_version():
    cfg = RootConfig.model_validate(_minimal_root_config_dict())
    out = inject_run_metadata(cfg, "deadbeef")

    assert out.uuid == "deadbeef"
    assert out.dataset_version == 1
    assert out.ran is not None
    # Parseable as ISO-8601 with timezone.
    from datetime import datetime

    parsed = datetime.fromisoformat(out.ran)
    assert parsed.tzinfo is not None


def test_params_requires_at_least_two_nodes():
    d = _minimal_root_config_dict()
    d["params"]["nodes"] = [{"node_name": "only", "num_qubits": 1, "inputs": {}}]
    with pytest.raises(ValidationError, match="at least 2 nodes"):
        RootConfig.model_validate(d)


def test_params_rejects_duplicate_node_names():
    d = _minimal_root_config_dict()
    d["params"]["nodes"] = [
        {"node_name": "same", "num_qubits": 1, "inputs": {}},
        {"node_name": "same", "num_qubits": 1, "inputs": {}},
    ]
    with pytest.raises(ValidationError, match="duplicate node_name"):
        RootConfig.model_validate(d)


def test_params_rejects_empty_file_path_string():
    d = _minimal_root_config_dict()
    d["params"]["nodes"][0]["file_path"] = "   "
    with pytest.raises(ValidationError, match="empty file_path"):
        RootConfig.model_validate(d)


def test_node_config_rejects_zero_qubits():
    with pytest.raises(ValidationError):
        NodeConfigModel.model_validate(
            {"node_name": "x", "num_qubits": 0, "inputs": {}}
        )


def test_generator_compare_discriminator():
    cfg = RootConfig.model_validate(_minimal_root_config_dict())
    assert cfg.pipeline.generator.type == "compare"
    assert len(cfg.pipeline.generator.params.programs) == 1


def test_generator_heuristic_requires_exactly_one_program_source():
    d = _minimal_root_config_dict()
    d["pipeline"]["generator"] = {
        "type": "heuristic",
        "params": {"label": "h", "program_dir": "x", "program_variant": "unoptimized"},
    }
    with pytest.raises(ValidationError, match="exactly one"):
        RootConfig.model_validate(d)


def test_generator_heuristic_rejects_neither_program_source():
    d = _minimal_root_config_dict()
    d["pipeline"]["generator"] = {
        "type": "heuristic",
        "params": {"label": "h"},
    }
    with pytest.raises(ValidationError, match="exactly one"):
        RootConfig.model_validate(d)


def test_analyzer_params_default_to_empty_dict():
    m = AnalyzerModel.model_validate({"type": "simple"})
    assert m.params == {}


def test_qstate_formalism_must_be_dm_or_ket():
    d = _minimal_root_config_dict()
    d["params"]["qstate_formalism"] = "BLOCH"
    with pytest.raises(ValidationError):
        RootConfig.model_validate(d)


def test_execution_on_failure_must_be_stop_or_continue():
    d = _minimal_root_config_dict()
    d["execution"]["on_failure"] = "panic"
    with pytest.raises(ValidationError):
        RootConfig.model_validate(d)


def test_compilator_section_optional():
    cfg = RootConfig.model_validate(_minimal_root_config_dict())
    assert cfg.pipeline.compilator is None


def test_params_model_can_be_validated_directly():
    payload = copy.deepcopy(_minimal_root_config_dict()["params"])
    m = ParamsModel.model_validate(payload)
    assert m.config_path == "params.json"
    assert len(m.nodes) == 2
