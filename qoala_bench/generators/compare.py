from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from qoala_bench.config import (
    GeneratorCompareParams,
    NodeProgramFromCompilator,
    RootConfig,
)
from qoala_bench.dataset import copy_program_iqoala
from qoala_bench.mp_runner import NodeSpec, TaskSpec, run_tasks_multiprocess
from qoala_bench.registry import register_generator


def _resolve_node_program_path(
    node_name: str,
    file_path: str,
    copied: Dict[str, Any],
    task_dir,
) -> str:
    if isinstance(copied, dict) and node_name in copied:
        return str(copied[node_name])

    base = file_path.split("/")[-1]
    if isinstance(copied, dict) and base in copied:
        return str(copied[base])

    candidate = task_dir / file_path
    if candidate.exists():
        return str(candidate)

    raise FileNotFoundError(
        f"Cannot resolve program path for node '{node_name}'. "
        f"Tried copied['{node_name}'], copied['{base}'], and '{candidate}'."
    )


def _resolve_node_file_path(
    n,
    comp_state: Dict[str, Any],
    *,
    compilator_variant: str | None = None,
    program_variant: str | None = None,
) -> str:
    """
    Resolve params.nodes[*].file_path.

    Supports:
      1) legacy string paths (returns as-is)
      2) NodeProgramFromCompilator refs (old style)
      3) None (new style): resolve from comp_state using node_name + program_variant

    Expected comp_state layout (new translator):
      comp_state["outputs"][<compilator_variant>][<source>]["translator"][<program_variant>] -> path
      comp_state["outputs"][<compilator_variant>][<source>]["optimizer"][<pass_name>] -> path
      comp_state["outputs"][<compilator_variant>][<source>]["python"] -> path
    """
    fp = getattr(n, "file_path", None)

    # 1) legacy: string path
    if isinstance(fp, str):
        return fp

    # helper: default compilator variant
    def _pick_variant() -> str:
        if compilator_variant is not None:
            return compilator_variant
        outs = comp_state.get("outputs", {})
        if isinstance(outs, dict) and len(outs) == 1:
            return next(iter(outs.keys()))
        raise ValueError(
            "compilator_variant is required when comp_state contains multiple variants "
            f"(available: {list(outs.keys())})"
        )

    # 3) NEW style: file_path omitted in YAML -> resolve by node_name + program_variant
    if fp is None:
        v = _pick_variant()
        if program_variant is None:
            raise ValueError(
                f"Node '{getattr(n, 'node_name', '<unknown>')}' has no file_path; "
                "program_variant is required to resolve compiled translator output."
            )
        try:
            return str(
                comp_state["outputs"][v][n.node_name]["translator"][program_variant]
            )
        except KeyError as e:
            raise KeyError(
                f"Cannot resolve compiled program for node='{n.node_name}', "
                f"compilator_variant='{v}', program_variant='{program_variant}'. Missing: {e}"
            )

    # 2) old style: NodeProgramFromCompilator in YAML
    if isinstance(fp, NodeProgramFromCompilator):
        ref = fp.from_compilator
        v = compilator_variant or ref.variant
        src = ref.source

        try:
            entry = comp_state["outputs"][v][src]
        except KeyError as e:
            raise KeyError(
                f"Cannot resolve from_compilator: variant='{v}', source='{src}'. Missing: {e}"
            )

        if ref.stage == "optimizer":
            if ref.pass_name is None:
                raise ValueError(
                    "from_compilator.pass_name is required when stage=='optimizer'"
                )
            try:
                return str(entry["optimizer"][ref.pass_name])
            except KeyError as e:
                raise KeyError(
                    f"Cannot resolve optimizer pass '{ref.pass_name}' for variant='{v}', source='{src}'. Missing: {e}"
                )

        if ref.stage == "translator":
            # New layout: translator is dict keyed by program_variant
            pv = program_variant or ref.program_variant
            if pv is None:
                raise ValueError(
                    "from_compilator.program_variant (or program_variant arg) is required "
                    "when stage=='translator'"
                )
            try:
                return str(entry["translator"][pv])
            except KeyError as e:
                raise KeyError(
                    f"Cannot resolve translator output for variant='{v}', source='{src}', program_variant='{pv}'. Missing: {e}"
                )

        # python stage output
        try:
            return str(entry[ref.stage])
        except KeyError as e:
            raise KeyError(
                f"Cannot resolve stage='{ref.stage}' for variant='{v}', source='{src}'. Missing: {e}"
            )

    raise TypeError(f"Unsupported file_path type: {type(fp)}")


@register_generator("compare")
class CompareGenerator:
    def generate(self, cfg: RootConfig, dataset, comp_state=None) -> object:
        gen_params = cfg.pipeline.generator.params
        assert isinstance(gen_params, GeneratorCompareParams)

        # Load params.json (hardware/link defaults)
        with open((dataset.root / cfg.params.config_path), "r", encoding="utf-8") as f:
            config_dict: Dict[str, Any] = json.load(f)

        # Nodes come from SAME YAML under params.nodes
        cfg_nodes = getattr(cfg.params, "nodes", None)
        if not cfg_nodes or len(cfg_nodes) < 2:
            raise ValueError("Config must define params.nodes with at least 2 nodes.")

        tasks: List[TaskSpec] = []

        for prog in gen_params.programs:
            program_variant = getattr(prog, "program_variant", None)

            # If program_variant is requested, comp_state must exist
            if program_variant is not None and comp_state is None:
                raise ValueError(
                    "program_variant was set but comp_state is None. "
                    "Did cli.py pass comp_state to generator (gen.generate(..., comp_state=...))?"
                )

            # Compilator mode
            if program_variant is not None:
                node_specs: List[NodeSpec] = []
                for n in cfg_nodes:
                    resolved = _resolve_node_file_path(
                        n,
                        comp_state,
                        compilator_variant=None,  # auto-detect from single variant
                        program_variant=program_variant,  # "unoptimized" or "optimized"
                    )
                    node_specs.append(
                        NodeSpec(
                            node_name=n.node_name,
                            file_path=resolved,
                            num_qubits=int(n.num_qubits),
                            inputs=dict(n.inputs or {}),
                        )
                    )

                tasks.append(
                    TaskSpec(
                        label=prog.label,
                        nodes=node_specs,
                        config=config_dict,
                    )
                )
                continue

            # --- Legacy mode: copy from program_dir ---
            task_dir = dataset.artifacts_programs / prog.label
            copied = copy_program_iqoala(prog.program_dir, task_dir)

            node_specs = []
            for n in cfg_nodes:
                if not isinstance(n.file_path, str):
                    raise ValueError(
                        "Legacy mode expects params.nodes[*].file_path to be a string (e.g. 'alice.iqoala')."
                    )

                resolved_program = _resolve_node_program_path(
                    node_name=n.node_name,
                    file_path=n.file_path,
                    copied=copied,
                    task_dir=task_dir,
                )

                node_specs.append(
                    NodeSpec(
                        node_name=n.node_name,
                        file_path=resolved_program,
                        num_qubits=int(n.num_qubits),
                        inputs=dict(n.inputs or {}),
                    )
                )

            tasks.append(
                TaskSpec(
                    label=prog.label,
                    nodes=node_specs,
                    config=config_dict,
                )
            )

        elapsed = run_tasks_multiprocess(
            tasks=tasks,
            raw_root=str(dataset.raw),
            iterations=cfg.execution.iterations,
            cpu_count=cfg.execution.cpu_count,
            on_failure=cfg.execution.on_failure,
        )

        timing_path = os.path.join(str(dataset.root), "simulation_timing.json")
        with open(timing_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "simulation_wall_time_seconds": round(elapsed, 2),
                    "iterations": cfg.execution.iterations,
                    "num_tasks": len(tasks),
                    "cpu_count": cfg.execution.cpu_count,
                },
                f,
                indent=2,
            )

        return {"dataset_dir": str(dataset.root)}
