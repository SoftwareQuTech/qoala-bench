"""Pydantic models for the benchmark YAML schema.

This module defines the typed Python representation of the YAML
configuration files that drive every ``qoala-bench`` run. The root
model is :class:`BenchmarkConfig`; it groups the program parameters
(:class:`ParamsConfig`), execution settings (:class:`ExecutionConfig`),
and the pipeline stages (:class:`PipelineConfig`, which itself
contains a :class:`CompilatorConfig`, a :class:`GeneratorConfig`, and
an :class:`AnalyzerConfig`). :func:`load_config_yaml` is the entry
point used by :mod:`qoala_bench.cli` to read and validate a YAML file
into a :class:`BenchmarkConfig` instance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, model_validator


class MetadataModel(BaseModel):
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class ParamsModel(BaseModel):
    config_path: str
    nodes: List[NodeConfigModel]
    qstate_formalism: Literal["DM", "KET"] = "DM"

    @model_validator(mode="after")
    def validate_nodes(self) -> "ParamsModel":
        if self.nodes is None or len(self.nodes) < 2:
            raise ValueError("params.nodes must contain at least 2 nodes")

        names = [n.node_name for n in self.nodes]
        if len(set(names)) != len(names):
            raise ValueError(f"params.nodes contains duplicate node_name(s): {names}")

        # IMPORTANT: file_path is optional when using compilator mode.
        # We only reject explicit empty strings (common mistake).
        for n in self.nodes:
            if isinstance(n.file_path, str) and n.file_path.strip() == "":
                raise ValueError(f"Node '{n.node_name}' has empty file_path")

        return self


class ExecutionModel(BaseModel):
    iterations: int = 1
    cpu_count: int = 2
    on_failure: Literal["stop", "continue"] = "stop"
    store_logs: bool = False
    log_level: Literal["INFO", "DEBUG"] = "INFO"


class GeneratorHeuristicParams(BaseModel):
    label: str
    program_dir: Optional[str] = None
    program_variant: Optional[str] = None  # e.g. "unoptimized" / "optimized"

    @model_validator(mode="after")
    def validate_one_of(self) -> "GeneratorHeuristicParams":
        if (self.program_dir is None) == (self.program_variant is None):
            raise ValueError(
                "Heuristic generator params must set exactly one of "
                "'program_dir' or 'program_variant'."
            )
        return self


class GeneratorCompareProgram(BaseModel):
    label: str
    program_dir: Optional[str] = None
    program_variant: Optional[str] = None

    @model_validator(mode="after")
    def validate_one_of(self) -> "GeneratorCompareProgram":
        if (self.program_dir is None) == (self.program_variant is None):
            raise ValueError(
                f"Compare program '{self.label}' must set exactly one of "
                f"'program_dir' or 'program_variant'."
            )
        return self


class GeneratorCompareParams(BaseModel):
    programs: List[GeneratorCompareProgram]


# Discriminated union so pydantic doesn't try the wrong params model first
class HeuristicGeneratorModel(BaseModel):
    type: Literal["heuristic"]
    params: GeneratorHeuristicParams


class CompareGeneratorModel(BaseModel):
    type: Literal["compare"]
    params: GeneratorCompareParams


GeneratorModel = Union[HeuristicGeneratorModel, CompareGeneratorModel]


class AnalyzerModel(BaseModel):
    type: str
    params: Dict[str, Any] = Field(default_factory=dict)


class PipelineModel(BaseModel):
    compilator: Optional[CompilatorModel] = None
    generator: GeneratorModel = Field(discriminator="type")
    analyzer: AnalyzerModel


class RootConfig(BaseModel):
    version: int = 1
    name: str
    author: str
    metadata: MetadataModel = Field(default_factory=MetadataModel)

    params: ParamsModel
    execution: ExecutionModel
    pipeline: PipelineModel

    # injected fields (written into dataset.yaml)
    uuid: Optional[str] = None
    ran: Optional[str] = None
    dataset_version: Optional[int] = None


def load_config_yaml(path: str) -> RootConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return RootConfig.model_validate(raw)


def inject_run_metadata(cfg: RootConfig, uuid_str: str) -> RootConfig:
    cfg.uuid = uuid_str
    cfg.ran = datetime.now(timezone.utc).isoformat()
    cfg.dataset_version = 1
    return cfg


# -------------------------
# Compilator models
# -------------------------


class PythonSourceModel(BaseModel):
    name: str
    source_file: str
    function: str  # e.g. "client_line_graph"
    method: str = "compile"  # fixed: call <function>.<method>(...)

    method_args: List[Any] = Field(default_factory=list)
    method_kwargs: Dict[str, Any] = Field(default_factory=dict)

    # example: (_, hir) -> pick index 1
    result_tuple_index: int = 1

    # output file name (not templated with json; only simple tokens)
    output_file: str = "{source_name}.hir.mlir"


class OptimizerPassModel(BaseModel):
    name: str
    flags: List[str] = Field(default_factory=list)  # supports {json:key} and {var:name}
    source_flags: Dict[str, List[str]] = Field(
        default_factory=dict
    )  # per-source flag overrides
    output_file: str = "{source_name}.{pass}.mlir"
    depends_on: Optional[str] = (
        None  # if None => previous pass, else named earlier pass
    )


class OptimizerToolModel(BaseModel):
    bin: str
    base_flags: List[str] = Field(default_factory=list)  # supports {json:*}, {var:*}


class TranslatorToolModel(BaseModel):
    bin: str
    base_flags: List[str] = Field(default_factory=list)
    flags: List[str] = Field(default_factory=list)  # global translator flags (optional)


class ToolsModel(BaseModel):
    optimizer: OptimizerToolModel
    translator: TranslatorToolModel


class ProgramVariantModel(BaseModel):
    name: str  # e.g. "unoptimized" / "optimized"
    input_pass: str  # optimizer pass name to translate from
    flags: List[str] = Field(default_factory=list)
    output_file: str = "{source_name}.{program_variant}.iqoala"


class VariantModel(BaseModel):
    name: str
    optimizer_passes: List[OptimizerPassModel] = Field(default_factory=list)

    # Multiple translator outputs
    program_variants: List[ProgramVariantModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_pass_graph(self) -> "VariantModel":
        names = [p.name for p in self.optimizer_passes]
        if len(names) != len(set(names)):
            raise ValueError(
                f"Duplicate optimizer pass names in variant '{self.name}': {names}"
            )

        # Validate depends_on points backwards (or to the special "python" sentinel)
        seen = set()
        for p in self.optimizer_passes:
            if (
                p.depends_on is not None
                and p.depends_on != "python"
                and p.depends_on not in seen
            ):
                raise ValueError(
                    f"Variant '{self.name}': pass '{p.name}' depends_on '{p.depends_on}' "
                    f"which is not defined earlier."
                )
            seen.add(p.name)

        pass_names = set(names)

        # If optimizer passes exist, program_variants must exist and each input_pass must refer to a pass
        if self.optimizer_passes:
            if not self.program_variants:
                raise ValueError(
                    f"Variant '{self.name}': program_variants is required when optimizer_passes is non-empty."
                )
            for pv in self.program_variants:
                if pv.input_pass not in pass_names:
                    raise ValueError(
                        f"Variant '{self.name}': program_variants[{pv.name}].input_pass='{pv.input_pass}' "
                        f"is not a pass name in optimizer_passes. Available: {sorted(pass_names)}"
                    )
        else:
            # No optimizer passes: you can allow translating directly from python output
            # In that case, input_pass can be omitted OR set to 'python'
            for pv in self.program_variants:
                if pv.input_pass not in ("python", "", None):
                    raise ValueError(
                        f"Variant '{self.name}': has no optimizer_passes, so program_variants[{pv.name}].input_pass "
                        f"must be 'python' (or empty). Got '{pv.input_pass}'."
                    )

        return self


class CompilatorPythonRuntimeModel(BaseModel):
    venv_python: Optional[str] = None  # optional python executable to use
    workdir: str = "."  # resolved relative to YAML location
    extra_sys_path: List[str] = Field(default_factory=list)


class CompilatorModel(BaseModel):
    enabled: bool = True
    artifact_subdir: str = "compilator"
    repeats: int = Field(default=15, ge=1)
    on_failure: Literal["stop", "continue"] = "stop"

    python: CompilatorPythonRuntimeModel = Field(
        default_factory=CompilatorPythonRuntimeModel
    )
    python_sources: List[PythonSourceModel]
    tools: ToolsModel

    # values substituted in args/flags: {var:name}
    variables: Dict[str, Any] = Field(default_factory=dict)

    variants: List[VariantModel] = Field(
        default_factory=lambda: [VariantModel(name="default")]
    )

    @model_validator(mode="after")
    def validate_unique_names(self) -> "CompilatorModel":
        src_names = [s.name for s in self.python_sources]
        if len(src_names) != len(set(src_names)):
            raise ValueError(f"Duplicate python_sources names: {src_names}")
        var_names = [v.name for v in self.variants]
        if len(var_names) != len(set(var_names)):
            raise ValueError(f"Duplicate variants names: {var_names}")
        return self


# -------------------------
# Node program reference from compilator output
# -------------------------


class FromCompilatorRef(BaseModel):
    variant: str  # compilator VariantModel.name, e.g. "bqc"
    source: str  # python_sources name: "client"/"server"
    stage: Literal["translator", "python", "optimizer"]
    pass_name: Optional[str] = None
    program_variant: Optional[str] = None  # translator output selector

    @model_validator(mode="after")
    def validate_stage(self) -> "FromCompilatorRef":
        if self.stage == "optimizer" and not self.pass_name:
            raise ValueError(
                "from_compilator: pass_name is required when stage=='optimizer'"
            )
        if self.stage == "translator" and not self.program_variant:
            raise ValueError(
                "from_compilator: program_variant is required when stage=='translator'"
            )
        return self


class NodeProgramFromCompilator(BaseModel):
    from_compilator: FromCompilatorRef


NodeProgramPath = Union[str, NodeProgramFromCompilator]


class NodeConfigModel(BaseModel):
    node_name: str
    file_path: Optional[NodeProgramPath] = None
    num_qubits: int = Field(..., ge=1)
    inputs: Dict[str, Any] = Field(default_factory=dict)
