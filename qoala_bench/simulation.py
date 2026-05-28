"""Simulation stage of the benchmark pipeline.

Reads a generated ``dataset.yaml``, dispatches each simulation entry
to a NetSquid worker process (managed by :mod:`qoala_bench.mp_runner`),
and writes the raw per-iteration results as gzipped pickle files under
``raw/<label>/results-N.pkl.gz`` inside the dataset folder.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

import netsquid as ns

from qoala.lang.ehi import UnitModule
from qoala.lang.parse import QoalaParser
from qoala.lang.program import QoalaProgram
from qoala.runtime.config import (
    ClassicalConnectionConfig,
    LatenciesConfig,
    NtfConfig,
    ProcNodeConfig,
    ProcNodeNetworkConfig,
    TopologyConfig,
)
from qoala.runtime.program import BatchResult, ProgramBatch, ProgramInput
from qoala.runtime.statistics import SchedulerStatistics
from qoala.runtime.task import TaskGraph
from qoala.runtime.taskbuilder import QoalaGraphFromProgramBuilder
from qoala.sim.build import build_network_from_config
from qoala.util.runner import AppResult, create_batch

# Fixed internal ids (NOT configurable via YAML)
# ALICE_ID = 1
# BOB_ID = 0


def create_procnode_cfg(
    name: str, node_id: int, num_qubits: int, determ: bool, config: Dict[str, Any]
) -> ProcNodeConfig:
    """Creates a processing node configuration."""
    return ProcNodeConfig(
        node_name=name,
        node_id=node_id,
        topology=TopologyConfig.uniform_t1t2_qubits_uniform_any_gate_duration_and_noise(
            num_qubits=num_qubits,
            t1=config["t1"],
            t2=config["t2"],
            single_gate_duration=config["single_gate_duration"],
            two_gate_duration=config["two_gate_duration"],
            single_gate_fid=config["single_gate_fid"],
            two_gate_fid=config["two_gate_fid"],
        ),
        latencies=LatenciesConfig(
            host_instr_time=config["host_instr_time"],
            host_peer_latency=config["host_peer_latency"],
            qnos_instr_time=config["qnos_instr_time"],
        ),
        ntf=NtfConfig.from_cls_name("GenericNtf"),
        determ_sched=determ,
        is_predictable=True,
    )


def load_program(path: str) -> QoalaProgram:
    """Loads a Qoala program from a file."""
    with open(path, encoding="utf-8") as file:
        text = file.read()
    return QoalaParser(text).parse()


def _set_qstate_formalism(config: Dict[str, Any]) -> None:
    """
    Set NetSquid qstate formalism.
    Default is DM to match your previous behavior.
    You can optionally set config["qstate_formalism"] to "DM" or "KET".
    """
    formalism = str(config.get("qstate_formalism", "DM")).upper()
    if formalism == "DM":
        ns.set_qstate_formalism(ns.QFormalism.DM)
    elif formalism == "KET":
        ns.set_qstate_formalism(ns.QFormalism.KET)
    else:
        raise ValueError(
            f"Unsupported qstate_formalism '{formalism}'. Use 'DM' or 'KET'."
        )


def _build_full_mesh_cconns(
    node_ids: List[int], latency: int
) -> List[ClassicalConnectionConfig]:
    cconns: List[ClassicalConnectionConfig] = []
    for i in range(len(node_ids)):
        for j in range(i + 1, len(node_ids)):
            cconns.append(
                ClassicalConnectionConfig.from_nodes(
                    node_ids[i], node_ids[j], latency=latency
                )
            )
    return cconns


def _peer_id_inputs(nodes: List[Dict[str, Any]], self_name: str) -> Dict[str, int]:
    """
    For a given node, create a dict like:
      {"alice_id": 0, "bob_id": 1, ...} excluding self.
    """
    name_to_id = {n["node_name"]: i for i, n in enumerate(nodes)}
    out: Dict[str, int] = {}
    for name, nid in name_to_id.items():
        if name == self_name:
            continue
        out[f"{name}_id"] = nid
    return out


def run(
    nodes: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> Tuple[AppResult, int, Dict[str, TaskGraph]]:
    """
    Run a single simulation for N nodes described by YAML.

    Each node dict must include:
      - node_name: str
      - file_path: str
      - num_qubits: int
      - inputs: dict (optional)

    Returns:
      (AppResult, seed, task_graphs_by_node_name)
    """
    if len(nodes) < 2:
        raise ValueError("Need at least 2 nodes.")

    ns.sim_reset()

    # Assign stable IDs based on YAML order
    node_id_map = {n["node_name"]: i for i, n in enumerate(nodes)}
    node_ids = list(node_id_map.values())

    # Build per-node proc configs
    procnode_cfgs: List[ProcNodeConfig] = []
    for n in nodes:
        name = n["node_name"]
        node_id = node_id_map[name]
        num_qubits = int(n["num_qubits"])
        procnode_cfgs.append(
            create_procnode_cfg(name, node_id, num_qubits, determ=True, config=config)
        )

    # Build network config (imperfect links + full mesh classical comms)
    network_cfg = ProcNodeNetworkConfig.from_nodes_imperfect_links(
        nodes=procnode_cfgs,
        link_duration=config["link_duration"],
        link_fid=config["link_fid"],
    )
    network_cfg.cconns = _build_full_mesh_cconns(node_ids, latency=config["latency"])

    # Load programs
    programs: Dict[str, QoalaProgram] = {}
    for n in nodes:
        programs[n["node_name"]] = load_program(n["file_path"])

    # Setup NetSquid RNG
    ns.sim_reset()
    ns.set_qstate_formalism(ns.QFormalism.DM)
    seed = random.randint(0, 1000)
    ns.set_random_state(seed=seed)

    network = build_network_from_config(network_cfg)

    # Submit batches for each node
    batches: Dict[str, ProgramBatch] = {}

    # Create inputs: include id map so programs can look up peers
    # (and still merge in node-specific YAML inputs)
    for n in nodes:
        name = n["node_name"]
        node = network.nodes[name]
        unit_module = UnitModule.from_full_ehi(node.memmgr.get_ehi())

        base_inputs = _peer_id_inputs(nodes, self_name=name)
        node_inputs = n.get("inputs") or {}
        prog_input = ProgramInput({**base_inputs, **node_inputs})

        batch_info = create_batch(programs[name], unit_module, [prog_input], 1)
        batches[name] = node.submit_batch(batch_info)

    # Initialize remote pids for each node (everyone knows everyone)
    for local_name in batches.keys():
        local_node = network.nodes[local_name]
        remote_pids = {
            batches[remote_name].batch_id: [
                p.pid for p in batches[remote_name].instances
            ]
            for remote_name in batches.keys()
            if remote_name != local_name
        }
        local_node.initialize_processes(remote_pids)

    # Build and upload task graphs from compiled block precedences
    task_graphs: Dict[str, TaskGraph] = {}
    for n in nodes:
        name = n["node_name"]
        node = network.nodes[name]
        program = programs[name]
        pid = batches[name].instances[0].pid

        base_inputs = _peer_id_inputs(nodes, self_name=name)
        node_inputs = n.get("inputs") or {}
        prog_input_dict = {**base_inputs, **node_inputs}

        builder = QoalaGraphFromProgramBuilder()
        graph = builder.build(
            program,
            pid,
            ehi=node.memmgr.get_ehi(),
            network_ehi=node.scheduler._network_ehi,
            prog_input=prog_input_dict,
        )
        node.scheduler.upload_task_graph(graph)
        task_graphs[name] = graph

    network.start()
    ns.sim_run()

    results: Dict[str, BatchResult] = {}
    statistics: Dict[str, SchedulerStatistics] = {}
    for n in nodes:
        name = n["node_name"]
        node = network.nodes[name]
        results[name] = node.scheduler.get_batch_results()[0]
        statistics[name] = node.scheduler.get_statistics()

    total_duration = ns.sim_time()

    return AppResult(results, statistics, total_duration), seed, task_graphs
