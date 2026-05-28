from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from qoala_bench.config import GeneratorHeuristicParams, RootConfig
from qoala_bench.dataset import copy_program_iqoala
from qoala_bench.mp_runner import NodeSpec, TaskSpec, run_tasks_multiprocess
from qoala_bench.registry import register_generator


def _resolve_node_program_path(
    node_name: str,
    file_path: str,
    copied: Dict[str, Any],
    task_dir,
) -> str:
    """
    Resolve node program path after copy_program_iqoala().

    Tries:
      1) copied[node_name]
      2) copied[basename(file_path)]
      3) task_dir / file_path
    """
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


def _resolve_node_file_path(n, comp_state: Dict[str, Any]) -> str:
    """
    Resolve params.nodes[*].file_path, supporting:
      - plain string paths (legacy)
      - from_compilator refs (new)
    Expects comp_state to contain:
      comp_state["outputs"][variant][source][stage]
      and for stage=="optimizer": ...["optimizer"][pass_name]
    """
    fp = n.file_path

    # legacy: string
    if isinstance(fp, str):
        return fp

    # new: from_compilator
    if isinstance(fp, NodeProgramFromCompilator):
        ref = fp.from_compilator
        try:
            entry = comp_state["outputs"][ref.variant][ref.source]
        except KeyError as e:
            raise KeyError(
                f"Cannot resolve from_compilator: variant='{ref.variant}', source='{ref.source}'. "
                f"Missing: {e}"
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
                    f"Cannot resolve optimizer pass '{ref.pass_name}' for "
                    f"variant='{ref.variant}', source='{ref.source}'. Missing: {e}"
                )

        # python / translator
        try:
            return str(entry[ref.stage])
        except KeyError as e:
            raise KeyError(
                f"Cannot resolve stage='{ref.stage}' for variant='{ref.variant}', source='{ref.source}'. "
                f"Missing: {e}"
            )

    raise TypeError(f"Unsupported file_path type: {type(fp)}")


@register_generator("heuristic")
class HeuristicGenerator:
    def generate(self, cfg: RootConfig, dataset, comp_state=None) -> object:
        gen_params = cfg.pipeline.generator.params
        assert isinstance(gen_params, GeneratorHeuristicParams)

        # Load params.json (hardware/link defaults)
        with open((dataset.root / cfg.params.config_path), "r", encoding="utf-8") as f:
            config_dict: Dict[str, Any] = json.load(f)

        # Nodes come from the SAME YAML config under params.nodes
        cfg_nodes = getattr(cfg.params, "nodes", None)
        if not cfg_nodes or len(cfg_nodes) < 2:
            raise ValueError("Config must define params.nodes with at least 2 nodes.")

        # --- Compilator mode (preferred if comp_state provided) ---
        # Expect generator params to include `program_variant` when using compilator.
        program_variant = getattr(gen_params, "program_variant", None)
        if comp_state is not None and program_variant is not None:
            node_specs: List[NodeSpec] = []
            for n in cfg_nodes:
                node_specs.append(
                    NodeSpec(
                        node_name=n.node_name,
                        file_path=_resolve_node_file_path(n, comp_state),
                        num_qubits=int(n.num_qubits),
                        inputs=dict(n.inputs or {}),
                    )
                )

            task = TaskSpec(
                label=gen_params.label,
                nodes=node_specs,
                config=config_dict,
            )

            elapsed = run_tasks_multiprocess(
                tasks=[task],
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
                        "num_tasks": 1,
                        "cpu_count": cfg.execution.cpu_count,
                    },
                    f,
                    indent=2,
                )

            return {"dataset_dir": str(dataset.root)}

        # --- Legacy mode (copy .iqoala from program_dir) ---
        task_dir = dataset.artifacts_programs / gen_params.label
        copied = copy_program_iqoala(gen_params.program_dir, task_dir)

        node_specs: List[NodeSpec] = []
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

        task = TaskSpec(
            label=gen_params.label,
            nodes=node_specs,
            config=config_dict,
        )

        elapsed = run_tasks_multiprocess(
            tasks=[task],
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
                    "num_tasks": 1,
                    "cpu_count": cfg.execution.cpu_count,
                },
                f,
                indent=2,
            )

        return {"dataset_dir": str(dataset.root)}
