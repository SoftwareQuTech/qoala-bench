from __future__ import annotations

import gc
import gzip
import json
import multiprocessing
import os
import pickle
import time
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List

from tqdm import tqdm

from qoala_bench.simulation import run

if TYPE_CHECKING:
    from multiprocessing.sharedctypes import Synchronized


@dataclass(frozen=True)
class NodeSpec:
    """
    Describes one node in a simulation task.

    Assumptions:
      - file_path points to the (possibly copied) .iqoala program file for that node.
      - inputs are per-node dict inputs (may be empty).
      - num_qubits is per-node.
    """

    node_name: str
    file_path: str
    num_qubits: int
    inputs: Dict[str, Any]


@dataclass(frozen=True)
class TaskSpec:
    """
    One "scenario" to run multiple iterations of.
    """

    label: str
    nodes: List[NodeSpec]
    config: Dict[str, Any]


def _queue_listener(result_queue: multiprocessing.Queue):
    """
    Writes:
      raw/<label>/app_results.pkl.gz (append pickle)
      raw/<label>/seeds.jsonl.gz (append jsonl)
    """
    while True:
        msg = result_queue.get()
        if msg == "STOP":
            break

        out_dir: str = msg["out_dir"]
        record_type: str = msg["type"]  # "result" | "seed"

        os.makedirs(out_dir, exist_ok=True)

        if record_type == "result":
            result = msg.get("result")
            if result is not None:
                result_file = os.path.join(out_dir, "app_results.pkl.gz")
                with gzip.open(result_file, "ab") as f:
                    pickle.dump(result, f, protocol=pickle.HIGHEST_PROTOCOL)
                    f.flush()

        elif record_type == "seed":
            seed_record = msg["seed_record"]
            seed_file = os.path.join(out_dir, "seeds.jsonl.gz")
            with gzip.open(seed_file, "at", encoding="utf-8") as f:
                f.write(json.dumps(seed_record) + "\n")
                f.flush()


def _worker_run_one_iteration(
    result_queue: multiprocessing.Queue,
    task: TaskSpec,
    out_dir: str,
    iteration: int,
    on_failure: str,
    done_counter: "Synchronized[int]",
):
    """
    Runs a single simulation iteration for an N-node task.

    Always records seed info (and errors) to seeds.jsonl.gz.
    If success, also records AppResult into app_results.pkl.gz.
    """
    try:
        # Convert NodeSpec list into the dict format expected by simulation.run(...)
        nodes_payload: List[Dict[str, Any]] = [
            {
                "node_name": n.node_name,
                "file_path": n.file_path,
                "num_qubits": int(n.num_qubits),
                "inputs": dict(n.inputs) if n.inputs is not None else {},
            }
            for n in task.nodes
        ]

        app_result, seed, _task_graphs = run(
            nodes=nodes_payload,
            config=task.config,
        )

        # Write result
        result_queue.put(
            {
                "type": "result",
                "label": task.label,
                "out_dir": out_dir,
                "result": app_result,
            }
        )

        # Seed record
        seed_record = {
            "iteration": iteration,
            "seed": seed,
            "status": "ok",
            "num_nodes": len(task.nodes),
            "nodes": [n.node_name for n in task.nodes],
            "sim_time": getattr(app_result, "total_duration", None)
            or getattr(app_result, "duration", None),
        }
        result_queue.put(
            {
                "type": "seed",
                "label": task.label,
                "out_dir": out_dir,
                "seed_record": seed_record,
            }
        )

    except Exception:
        tb = traceback.format_exc()
        seed_record = {
            "iteration": iteration,
            "seed": None,
            "status": "error",
            "num_nodes": len(task.nodes),
            "nodes": [n.node_name for n in task.nodes],
            "error": tb,
        }
        result_queue.put(
            {
                "type": "seed",
                "label": task.label,
                "out_dir": out_dir,
                "seed_record": seed_record,
            }
        )

        if on_failure == "stop":
            raise

    finally:
        with done_counter.get_lock():
            done_counter.value += 1


def run_tasks_multiprocess(
    tasks: List[TaskSpec],
    raw_root: str,
    iterations: int,
    cpu_count: int,
    on_failure: str,
) -> float:
    """
    Schedules tasks across processes.
    - total work = len(tasks) * iterations
    - listener uses one core, so we run at most cpu_count-1 workers concurrently
    Returns elapsed wall-clock time in seconds.
    """
    t_start = time.monotonic()
    result_queue: multiprocessing.Queue = multiprocessing.Queue()
    listener = multiprocessing.Process(target=_queue_listener, args=(result_queue,))
    listener.start()

    done_counter = multiprocessing.Value("i", 0)

    active: set[multiprocessing.Process] = set()
    total = len(tasks) * iterations
    idx = 0

    task_labels = ", ".join(t.label for t in tasks)
    pbar = tqdm(total=total, desc=f"Simulating [{task_labels}]", unit="iter")

    def task_for_index(k: int):
        task_index = k // iterations
        iteration_index = k % iterations
        task = tasks[task_index]
        out_dir = os.path.join(raw_root, task.label)
        return task, iteration_index, out_dir

    while idx < total or active:
        while len(active) < max(1, cpu_count - 1) and idx < total:
            task, it_i, out_dir = task_for_index(idx)
            p = multiprocessing.Process(
                target=_worker_run_one_iteration,
                args=(result_queue, task, out_dir, it_i, on_failure, done_counter),
            )
            p.start()
            active.add(p)
            idx += 1

        finished = []
        for p in list(active):
            if not p.is_alive():
                p.join()
                finished.append(p)
        for p in finished:
            active.remove(p)

        # Update progress bar from shared counter
        current = done_counter.value
        if current > pbar.n:
            pbar.update(current - pbar.n)

        if active:
            time.sleep(0.1)

    # Final update
    current = done_counter.value
    if current > pbar.n:
        pbar.update(current - pbar.n)
    pbar.close()

    # cleanup
    for p in list(active):
        p.terminate()
        p.join()
        active.remove(p)

    result_queue.put("STOP")
    listener.join()

    del result_queue, listener
    gc.collect()

    return time.monotonic() - t_start
