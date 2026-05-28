"""Compilation stage of the benchmark pipeline.

Invokes the user-supplied Python source files (via the
:mod:`euqalyptus` SDK) to emit HIR MLIR, then walks the configured
``optimizer_passes`` by calling ``qoala-opt`` once per pass and finally
``qoala-translate`` once per program variant. Timing statistics for
every pass are recorded into ``compilator_manifest.json`` inside the
dataset folder.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import Manager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tqdm import tqdm


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _stats(times_s: List[float]) -> Dict[str, Any]:
    if not times_s:
        return {}
    ts = list(times_s)
    ts_sorted = sorted(ts)

    def pct(p: float) -> float:
        if len(ts_sorted) == 1:
            return ts_sorted[0]
        k = (len(ts_sorted) - 1) * p
        f = int(k)
        c = min(f + 1, len(ts_sorted) - 1)
        if f == c:
            return ts_sorted[f]
        return ts_sorted[f] + (ts_sorted[c] - ts_sorted[f]) * (k - f)

    return {
        "n": len(ts),
        "min_s": min(ts),
        "max_s": max(ts),
        "mean_s": statistics.mean(ts),
        "stdev_s": statistics.pstdev(ts) if len(ts) > 1 else 0.0,
        "p50_s": pct(0.50),
        "p90_s": pct(0.90),
        "p95_s": pct(0.95),
    }


def _run_version(argv: List[str], cwd: Path) -> Dict[str, Any]:
    rec: Dict[str, Any] = {"argv": argv, "returncode": None, "stdout": "", "stderr": ""}
    try:
        p = subprocess.run(
            argv,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        rec["returncode"] = p.returncode
        rec["stdout"] = (p.stdout or "").strip()
        rec["stderr"] = (p.stderr or "").strip()
    except Exception as e:
        rec["stderr"] = f"failed: {e}"
    return rec


_PY_RUNNER = r"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source_file", required=True)
    ap.add_argument("--function", required=True)
    ap.add_argument("--method", required=True)
    ap.add_argument("--tuple_index", type=int, required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--extra_sys_path", action="append", default=[])
    ap.add_argument("--args_json", required=True)
    ap.add_argument("--kwargs_json", required=True)
    args = ap.parse_args()

    wd = Path(args.workdir).resolve()
    sys.path.insert(0, str(wd))
    for p in args.extra_sys_path:
        pp = Path(p)
        sys.path.insert(0, str((wd / pp).resolve()) if not pp.is_absolute() else str(pp))

    src = Path(args.source_file)
    if not src.is_absolute():
        src = (wd / src).resolve()

    spec = importlib.util.spec_from_file_location("qoala_user_module", str(src))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    fn = getattr(mod, args.function)
    call_args = json.loads(args.args_json)
    call_kwargs = json.loads(args.kwargs_json)

    m = getattr(fn, args.method)
    res = m(*call_args, **call_kwargs)

    hir = res[args.tuple_index] if isinstance(res, tuple) else res
    sys.stdout.write(str(hir))

if __name__ == "__main__":
    main()
"""


def _resolve_relative_to_yaml(yaml_path: Path, p: str) -> Path:
    pp = Path(p)
    if pp.is_absolute():
        return pp
    return (yaml_path.parent / pp).resolve()


def _json_get(d: Dict[str, Any], dotted: str) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(dotted)
        cur = cur[part]
    return cur


def _format_cli_value(v: Any) -> str:
    # For CLI flags, everything must be a string, but format deterministically.
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        # Whole-number floats (e.g. t2=1e10) must be emitted as plain integers
        # because many CLI options are typed uint/int and reject scientific notation.
        if v == int(v):
            return str(int(v))
        return format(v, "g")
    return str(v)


def _subst(
    s: str,
    *,
    json_cfg: Dict[str, Any],
    variables: Dict[str, Any],
    mapping: Dict[str, Any],
) -> str:
    """
    Supported tokens:
      {json:key} or {json:a.b.c}
      {var:name}
      {source_name}, {variant}, {pass}
    """
    out = s

    # simple mapping tokens
    for k, v in mapping.items():
        out = out.replace("{" + k + "}", str(v))

    # {var:*}
    # (simple scan; avoid regex to keep dependencies minimal)
    while True:
        start = out.find("{var:")
        if start == -1:
            break
        end = out.find("}", start)
        if end == -1:
            break
        key = out[start + 5 : end]
        if key not in variables:
            raise KeyError(f"var:{key}")
        out = out[:start] + _format_cli_value(variables[key]) + out[end + 1 :]

    # {json:*}
    while True:
        start = out.find("{json:")
        if start == -1:
            break
        end = out.find("}", start)
        if end == -1:
            break
        key = out[start + 6 : end]
        val = _json_get(json_cfg, key)
        out = out[:start] + _format_cli_value(val) + out[end + 1 :]

    return out


def _run_repeated_stdout_command(
    *,
    argv: List[str],
    cwd: Path,
    repeats: int,
    stderr_log: Path,
    on_failure: str,
    on_repeat=None,
) -> Tuple[Optional[bytes], List[float], List[str], Optional[int]]:
    """
    Runs argv repeats times, captures stdout bytes each time,
    appends stderr to stderr_log, returns:
      (canonical_stdout, times, stdout_hashes, last_returncode)
    """
    times: List[float] = []
    hashes: List[str] = []
    canonical: Optional[bytes] = None
    last_rc: Optional[int] = None

    stderr_log.write_text("", encoding="utf-8")

    for _ in range(repeats):
        t0 = time.perf_counter()
        p = subprocess.run(
            argv,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        dt = time.perf_counter() - t0
        times.append(dt)
        last_rc = p.returncode
        if on_repeat is not None:
            on_repeat()

        if p.stderr:
            with stderr_log.open("ab") as f:
                f.write(p.stderr)
                if not p.stderr.endswith(b"\n"):
                    f.write(b"\n")

        if p.returncode != 0:
            if on_failure == "stop":
                return None, times, hashes, last_rc
            # continue mode: record failure and continue (still no canonical output)
            continue

        out_bytes = p.stdout
        hashes.append(_sha256_bytes(out_bytes))
        if canonical is None:
            canonical = out_bytes

    return canonical, times, hashes, last_rc


def _fail(msg: str, *, stdout: str | None = None, stderr: str | None = None) -> None:
    parts = [msg]
    if stdout:
        parts.append("\n--- stdout ---\n" + stdout)
    if stderr:
        parts.append("\n--- stderr ---\n" + stderr)
    raise RuntimeError("".join(parts))


_STEP_LABELS: Dict[str, str] = {
    "python": "Python → HIR",
    "optimizer:step1_hir_to_mir": "HIR → MIR",
    "optimizer:step2_mir_to_lir": "MIR → LIR",
    "optimizer:step3_rotfold": "Rotation folding (HIR)",
    "optimizer:step4_hir_to_mir_opt": "HIR → MIR (opt)",
    "optimizer:step5_mir_to_lir_opt": "MIR → LIR (opt)",
    "optimizer:step4_opt": "Reorder blocks",
    "optimizer:step6_reorder": "Reorder blocks",
    "optimizer:step_esp_unopt": "ESP analysis (unopt.)",
    "optimizer:step_qmem_unopt": "Qmem-eff analysis (unopt.)",
    "optimizer:step_esp_opt": "ESP analysis (opt.)",
    "optimizer:step_qmem_opt": "Qmem-eff analysis (opt.)",
}


def _step_label(step: str) -> str:
    if step in _STEP_LABELS:
        return _STEP_LABELS[step]
    if step.startswith("translator:"):
        return f"Translate ({step[len('translator:'):]})"
    if step.startswith("optimizer:"):
        return f"Optimize ({step[len('optimizer:'):]})"
    return step


def _drain_progress(
    queue, bars: dict, stop_event: threading.Event, n_sources: int = 1
) -> None:
    """Background thread: drains the progress queue and updates tqdm bars.

    With n_sources > 1, each step receives n_sources events per "repeat round"
    (one from each source running in parallel).  To keep the bar total equal to
    comp.repeats we only emit one bar tick every n_sources queue events, so the
    bar still fills up to 100% when all sources finish.
    """
    step_counts: Dict[str, int] = {}

    def _maybe_update(step: str) -> None:
        count = step_counts.get(step, 0) + 1
        step_counts[step] = count
        bar = bars.get(step)
        if bar is not None and count % n_sources == 0:
            bar.update(1)

    while True:
        try:
            step = queue.get(timeout=0.05)
            _maybe_update(step)
        except Exception:
            if stop_event.is_set():
                # Drain remaining items before exiting
                while True:
                    try:
                        step = queue.get_nowait()
                        _maybe_update(step)
                    except Exception:
                        break
                break


def _compile_one_source(task: dict) -> dict:
    """
    Worker: compile one (variant, source) pair through the full pipeline.
    All arguments are plain-dict serialisable so the function works inside a
    ProcessPoolExecutor worker.  Returns::

        {"src_name": str, "src_rec": dict, "outputs": dict}

    where *outputs* mirrors the outputs_index sub-entry for this source.
    """
    src_name = task["src_name"]
    var_name = task["var_name"]
    out_dir = Path(task["out_dir"])
    log_dir = Path(task["log_dir"])
    runner_path = Path(task["runner_path"])
    python_exe = task["python_exe"]
    workdir = Path(task["workdir"])
    json_cfg = task["json_cfg"]
    variables = task["variables"]
    repeats = task["repeats"]
    on_failure = task["on_failure"]
    optimizer_bin = task["optimizer_bin"]
    optimizer_base_flags = task["optimizer_base_flags"]
    translator_bin = task["translator_bin"]
    translator_base_flags = task["translator_base_flags"]
    translator_global_flags = task["translator_global_flags"]
    optimizer_passes = task["optimizer_passes"]  # list of dicts
    program_variants = task["program_variants"]  # list of dicts
    extra_sys_path = task.get("extra_sys_path", [])
    progress_queue = task.get("progress_queue")

    def _report(step: str) -> None:
        if progress_queue is not None:
            progress_queue.put(step)

    mapping_base = {"source_name": src_name, "variant": var_name}
    src_rec: Dict[str, Any] = {"name": src_name, "stages": []}
    outputs: Dict[str, Any] = {"python": None, "optimizer": {}, "translator": {}}

    # ---- helpers ----
    def res_arg(a: Any) -> Any:
        if not isinstance(a, str):
            return a
        if a.startswith("{var:") and a.endswith("}"):
            key = a[5:-1]
            if key not in variables:
                raise KeyError(f"var:{key}")
            return variables[key]
        if a.startswith("{json:") and a.endswith("}"):
            return _json_get(json_cfg, a[6:-1])
        return _subst(a, json_cfg=json_cfg, variables=variables, mapping=mapping_base)

    # ---- Stage: python ----
    py_out_name = _subst(
        task["src_output_file"],
        json_cfg=json_cfg,
        variables=variables,
        mapping=mapping_base,
    )
    py_out_path = (out_dir / py_out_name).resolve()

    args_json = json.dumps([res_arg(a) for a in task["src_method_args"]])
    kwargs_json = json.dumps(
        {k: res_arg(v) for k, v in task["src_method_kwargs"].items()}
    )

    py_argv = [
        python_exe,
        str(runner_path),
        "--source_file",
        _subst(
            task["src_source_file"],
            json_cfg=json_cfg,
            variables=variables,
            mapping=mapping_base,
        ),
        "--function",
        task["src_function"],
        "--method",
        task["src_method"],
        "--tuple_index",
        str(task["src_result_tuple_index"]),
        "--workdir",
        str(workdir),
        "--args_json",
        args_json,
        "--kwargs_json",
        kwargs_json,
    ]
    for p in extra_sys_path:
        py_argv += ["--extra_sys_path", p]

    py_stderr = log_dir / f"{src_name}.python.stderr.log"
    py_canon, py_times, py_hashes, py_rc = _run_repeated_stdout_command(
        argv=py_argv,
        cwd=workdir,
        repeats=repeats,
        stderr_log=py_stderr,
        on_failure=on_failure,
        on_repeat=lambda: _report("python"),
    )
    py_det = (len(set(py_hashes)) <= 1) if py_hashes else False
    if py_rc not in (0, None) and on_failure == "stop":
        _fail(
            f"python stage failed for source={src_name} variant={var_name} rc={py_rc}\n"
            f"cwd={workdir}\nargv={' '.join(py_argv)}\nstderr_log={py_stderr}",
            stderr=(
                py_stderr.read_text(encoding="utf-8", errors="replace")
                if py_stderr.exists()
                else None
            ),
        )
    if py_hashes and not py_det and on_failure == "stop":
        _fail(
            f"Non-deterministic python output for source={src_name} variant={var_name}"
        )
    if py_canon is not None:
        py_out_path.write_bytes(py_canon)

    src_rec["stages"].append(
        {
            "stage": "python",
            "output_path": str(py_out_path),
            "output_sha256": _sha256_file(py_out_path),
            "deterministic": py_det,
            "stats": _stats(py_times),
            "stderr_log": str(py_stderr),
            "argv_example": py_argv,
        }
    )
    outputs["python"] = str(py_out_path)

    # ---- Stages: optimizer passes ----
    pass_outputs: Dict[str, Path] = {}
    pass_order = [p["name"] for p in optimizer_passes]

    for i, pdef in enumerate(optimizer_passes):
        if pdef["depends_on"] is None:
            input_path = py_out_path if i == 0 else pass_outputs[pass_order[i - 1]]
            depends = "previous" if i > 0 else "python"
        elif pdef["depends_on"] == "python":
            input_path = py_out_path
            depends = "python"
        else:
            input_path = pass_outputs[pdef["depends_on"]]
            depends = pdef["depends_on"]

        pm = dict(mapping_base)
        pm["pass"] = pdef["name"]
        out_name = _subst(
            pdef["output_file"], json_cfg=json_cfg, variables=variables, mapping=pm
        )
        out_path = (out_dir / out_name).resolve()

        base_flags = [
            _subst(f, json_cfg=json_cfg, variables=variables, mapping=pm)
            for f in optimizer_base_flags
        ]
        raw_flags = pdef.get("source_flags", {}).get(src_name) or pdef["flags"]
        pass_flags = [
            _subst(f, json_cfg=json_cfg, variables=variables, mapping=pm)
            for f in raw_flags
        ]
        opt_argv = [optimizer_bin] + base_flags + pass_flags + [str(input_path)]

        opt_stderr = log_dir / f"{src_name}.optimizer.{pdef['name']}.stderr.log"
        _step_key = f"optimizer:{pdef['name']}"
        opt_canon, opt_times, opt_hashes, opt_rc = _run_repeated_stdout_command(
            argv=opt_argv,
            cwd=workdir,
            repeats=repeats,
            stderr_log=opt_stderr,
            on_failure=on_failure,
            on_repeat=lambda s=_step_key: _report(s),
        )
        opt_det = (len(set(opt_hashes)) <= 1) if opt_hashes else False
        if opt_rc not in (0, None) and on_failure == "stop":
            _fail(
                f"optimizer pass failed source={src_name} variant={var_name} "
                f"pass={pdef['name']} rc={opt_rc}\n"
                f"cwd={workdir}\nargv={' '.join(opt_argv)}\nstderr_log={opt_stderr}",
                stderr=(
                    opt_stderr.read_text(encoding="utf-8", errors="replace")
                    if opt_stderr.exists()
                    else None
                ),
            )
        if opt_hashes and not opt_det:
            _fail(
                f"Non-deterministic optimizer output source={src_name} variant={var_name} "
                f"pass={pdef['name']}\ncwd={workdir}\nargv={' '.join(opt_argv)}",
                stderr=(
                    opt_stderr.read_text(encoding="utf-8", errors="replace")
                    if opt_stderr.exists()
                    else None
                ),
            )
        if opt_canon is not None:
            out_path.write_bytes(opt_canon)

        pass_outputs[pdef["name"]] = out_path
        outputs["optimizer"][pdef["name"]] = str(out_path)
        src_rec["stages"].append(
            {
                "stage": "optimizer",
                "pass": pdef["name"],
                "depends_on": depends,
                "input_path": str(input_path),
                "output_path": str(out_path),
                "output_sha256": _sha256_file(out_path),
                "deterministic": opt_det,
                "stats": _stats(opt_times),
                "stderr_log": str(opt_stderr),
                "argv_example": opt_argv,
            }
        )

    # ---- Stage: translator ----
    outputs["translator"] = {}
    for pv in program_variants:
        if optimizer_passes:
            tr_input = pass_outputs[pv["input_pass"]]
            tr_input_meta = {"kind": "optimizer_pass", "pass": pv["input_pass"]}
        else:
            tr_input = py_out_path
            tr_input_meta = {"kind": "python"}

        pm = dict(mapping_base)
        pm["program_variant"] = pv["name"]
        tr_out_name = _subst(
            pv["output_file"], json_cfg=json_cfg, variables=variables, mapping=pm
        )
        tr_out_path = (out_dir / tr_out_name).resolve()

        tr_base = [
            _subst(f, json_cfg=json_cfg, variables=variables, mapping=pm)
            for f in translator_base_flags
        ]
        tr_global = [
            _subst(f, json_cfg=json_cfg, variables=variables, mapping=pm)
            for f in translator_global_flags
        ]
        tr_variant = [
            _subst(f, json_cfg=json_cfg, variables=variables, mapping=pm)
            for f in pv["flags"]
        ]
        tr_argv = [translator_bin] + tr_base + tr_global + tr_variant + [str(tr_input)]

        tr_stderr = log_dir / f"{src_name}.translator.{pv['name']}.stderr.log"
        _tr_key = f"translator:{pv['name']}"
        tr_canon, tr_times, tr_hashes, tr_rc = _run_repeated_stdout_command(
            argv=tr_argv,
            cwd=workdir,
            repeats=repeats,
            stderr_log=tr_stderr,
            on_failure=on_failure,
            on_repeat=lambda s=_tr_key: _report(s),
        )
        tr_det = (len(set(tr_hashes)) <= 1) if tr_hashes else False
        if tr_rc not in (0, None) and on_failure == "stop":
            _fail(
                f"translator failed source={src_name} variant={var_name} "
                f"program_variant={pv['name']} rc={tr_rc}\n"
                f"cwd={workdir}\nargv={' '.join(tr_argv)}\nstderr_log={tr_stderr}",
                stderr=(
                    tr_stderr.read_text(encoding="utf-8", errors="replace")
                    if tr_stderr.exists()
                    else None
                ),
            )
        if tr_hashes and not tr_det:
            _fail(
                f"Non-deterministic translator output source={src_name} variant={var_name} "
                f"program_variant={pv['name']}",
                stderr=(
                    tr_stderr.read_text(encoding="utf-8", errors="replace")
                    if tr_stderr.exists()
                    else None
                ),
            )
        if tr_canon is not None:
            tr_out_path.write_bytes(tr_canon)

        outputs["translator"][pv["name"]] = str(tr_out_path)
        src_rec["stages"].append(
            {
                "stage": "translator",
                "program_variant": pv["name"],
                "input": tr_input_meta,
                "input_path": str(tr_input),
                "output_path": str(tr_out_path),
                "output_sha256": _sha256_file(tr_out_path),
                "deterministic": tr_det,
                "stats": _stats(tr_times),
                "stderr_log": str(tr_stderr),
                "argv_example": tr_argv,
            }
        )

    return {"src_name": src_name, "src_rec": src_rec, "outputs": outputs}


def _add_steps_source(task: dict) -> dict:
    """
    Worker: run new optimizer passes on an already-compiled source.

    Unlike _compile_one_source, this function does not run the python or
    translator stages — it only runs optimizer passes that are new (not yet
    present in the manifest).  It receives the existing output paths so that
    depends_on references can be resolved without recomputation.

    Returns::

        {"src_name": str, "new_stages": [stage_record, ...]}
    """
    src_name = task["src_name"]
    var_name = task["var_name"]
    out_dir = Path(task["out_dir"])
    log_dir = Path(task["log_dir"])
    workdir = Path(task["workdir"])
    json_cfg = task["json_cfg"]
    variables = task["variables"]
    repeats = task["repeats"]
    on_failure = task["on_failure"]
    optimizer_bin = task["optimizer_bin"]
    optimizer_base_flags = task["optimizer_base_flags"]
    new_passes = task["new_passes"]  # list of {name, flags, output_file, depends_on}
    existing_outputs = task["existing_outputs"]  # {pass_name: output_path_str}
    progress_queue = task.get("progress_queue")

    def _report(step: str) -> None:
        if progress_queue is not None:
            progress_queue.put(step)

    mapping_base = {"source_name": src_name, "variant": var_name}

    # Running map of all known outputs (existing + newly computed in this call)
    all_outputs: Dict[str, str] = dict(existing_outputs)
    new_stages: List[Dict[str, Any]] = []

    for pdef in new_passes:
        depends_on = pdef["depends_on"]
        if depends_on is None:
            raise ValueError(
                f"New pass {pdef['name']!r} must specify an explicit depends_on "
                f"(source={src_name})"
            )
        if depends_on not in all_outputs:
            raise ValueError(
                f"Pass {pdef['name']!r} depends on {depends_on!r} which is not "
                f"available (source={src_name}). "
                f"Available: {sorted(all_outputs)}"
            )
        input_path = Path(all_outputs[depends_on])

        pm = dict(mapping_base)
        pm["pass"] = pdef["name"]
        out_name = _subst(
            pdef["output_file"], json_cfg=json_cfg, variables=variables, mapping=pm
        )
        out_path = (out_dir / out_name).resolve()

        base_flags = [
            _subst(f, json_cfg=json_cfg, variables=variables, mapping=pm)
            for f in optimizer_base_flags
        ]
        raw_flags = pdef.get("source_flags", {}).get(src_name) or pdef["flags"]
        pass_flags = [
            _subst(f, json_cfg=json_cfg, variables=variables, mapping=pm)
            for f in raw_flags
        ]
        opt_argv = [optimizer_bin] + base_flags + pass_flags + [str(input_path)]

        opt_stderr = log_dir / f"{src_name}.optimizer.{pdef['name']}.stderr.log"
        _step_key = f"optimizer:{pdef['name']}"
        canon, times, hashes, rc = _run_repeated_stdout_command(
            argv=opt_argv,
            cwd=workdir,
            repeats=repeats,
            stderr_log=opt_stderr,
            on_failure=on_failure,
            on_repeat=lambda s=_step_key: _report(s),
        )
        det = (len(set(hashes)) <= 1) if hashes else False
        if rc not in (0, None) and on_failure == "stop":
            _fail(
                f"add-steps optimizer pass failed source={src_name} "
                f"pass={pdef['name']} rc={rc}\n"
                f"cwd={workdir}\nargv={' '.join(opt_argv)}\nstderr_log={opt_stderr}",
                stderr=(
                    opt_stderr.read_text(encoding="utf-8", errors="replace")
                    if opt_stderr.exists()
                    else None
                ),
            )
        if canon is not None:
            out_path.write_bytes(canon)

        all_outputs[pdef["name"]] = str(out_path)
        new_stages.append(
            {
                "stage": "optimizer",
                "pass": pdef["name"],
                "depends_on": depends_on,
                "input_path": str(input_path),
                "output_path": str(out_path),
                "output_sha256": _sha256_file(out_path),
                "deterministic": det,
                "stats": _stats(times),
                "stderr_log": str(opt_stderr),
                "argv_example": opt_argv,
            }
        )

    return {"src_name": src_name, "new_stages": new_stages}


def run_add_steps(
    cfg,
    dataset_folder: str,
    yaml_path: str,
    repeats_override: Optional[int] = None,
) -> None:
    """
    Run additional optimizer passes on an existing compiled dataset.

    Reads the compilator manifest from *dataset_folder*, compares its pass list
    against the passes declared in *cfg* (loaded from *yaml_path*), and runs
    only the passes that are missing.  The manifest is updated in-place when
    done.

    If *repeats_override* is given it overrides comp.repeats for this run.
    """
    manifest_path = (
        Path(dataset_folder)
        / "artifacts"
        / "compilator"
        / "compilator"
        / "compilator_manifest.json"
    )
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    comp = cfg.pipeline.compilator
    effective_repeats = (
        repeats_override if repeats_override is not None else comp.repeats
    )

    json_cfg = json.loads(
        Path(manifest["params_json_path"]).read_text(encoding="utf-8")
    )
    workdir = Path(manifest["workdir"])
    variables = dict(comp.variables or {})

    # Build lookup: {var_name: {src_name: {pass_name: output_path_str}}}
    existing_by_var: Dict[str, Dict[str, Dict[str, str]]] = {}
    for var_rec in manifest["variants"]:
        existing_by_var[var_rec["name"]] = {}
        for src_rec in var_rec["sources"]:
            outputs: Dict[str, str] = {}
            for stage in src_rec["stages"]:
                if stage["stage"] == "python":
                    outputs["python"] = stage["output_path"]
                elif stage["stage"] == "optimizer":
                    outputs[stage["pass"]] = stage["output_path"]
            existing_by_var[var_rec["name"]][src_rec["name"]] = outputs

    n_sources = len(comp.python_sources)

    for var in comp.variants:
        var_name = var.name
        var_rec = next((v for v in manifest["variants"] if v["name"] == var_name), None)
        if var_rec is None:
            print(
                f"[add-steps] Warning: variant {var_name!r} not in manifest, skipping"
            )
            continue

        # Determine new passes by comparing against the first source's existing steps
        ref_src = comp.python_sources[0].name
        done = set(existing_by_var[var_name].get(ref_src, {}).keys())
        new_passes = [p for p in var.optimizer_passes if p.name not in done]

        if not new_passes:
            print(
                f"[add-steps] [{var_name}] All passes already present, nothing to add."
            )
            continue

        print(
            f"[add-steps] [{var_name}] Adding {len(new_passes)} new pass(es): "
            f"{[p.name for p in new_passes]}"
        )

        out_dir = manifest_path.parent / var_name / "outputs"
        log_dir = manifest_path.parent / var_name / "logs"
        out_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        step_keys = [f"optimizer:{p.name}" for p in new_passes]
        prefix = f"[{var_name}]"

        tasks = [
            {
                "src_name": src.name,
                "var_name": var_name,
                "existing_outputs": existing_by_var[var_name].get(src.name, {}),
                "new_passes": [
                    {
                        "name": p.name,
                        "flags": list(p.flags),
                        "output_file": p.output_file,
                        "depends_on": p.depends_on,
                    }
                    for p in new_passes
                ],
                "out_dir": str(out_dir),
                "log_dir": str(log_dir),
                "workdir": str(workdir),
                "json_cfg": json_cfg,
                "variables": variables,
                "repeats": effective_repeats,
                "on_failure": comp.on_failure,
                "optimizer_bin": comp.tools.optimizer.bin,
                "optimizer_base_flags": list(comp.tools.optimizer.base_flags or []),
            }
            for src in comp.python_sources
        ]

        results: Dict[str, dict] = {}
        with Manager() as mgr:
            progress_queue = mgr.Queue()
            for t in tasks:
                t["progress_queue"] = progress_queue

            bars = {
                step: tqdm(
                    total=effective_repeats,
                    desc=f"{prefix} {_step_label(step)}",
                    unit="compile",
                    leave=True,
                )
                for step in step_keys
            }

            stop_event = threading.Event()
            drain_thread = threading.Thread(
                target=_drain_progress,
                args=(progress_queue, bars, stop_event, n_sources),
                daemon=True,
            )
            drain_thread.start()

            max_workers = getattr(getattr(cfg, "execution", None), "cpu_count", None)
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                future_to_src = {
                    executor.submit(_add_steps_source, t): t["src_name"] for t in tasks
                }
                for future in as_completed(future_to_src):
                    src_name = future_to_src[future]
                    results[src_name] = future.result()

            stop_event.set()
            drain_thread.join()
            for bar in bars.values():
                bar.close()

        # Merge new stages into the manifest
        for src in comp.python_sources:
            src_name = src.name
            if src_name not in results:
                continue
            src_rec = next(s for s in var_rec["sources"] if s["name"] == src_name)
            src_rec["stages"].extend(results[src_name]["new_stages"])

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[add-steps] Manifest updated: {manifest_path}")


def run_compilator(cfg, dataset, yaml_path: str, out_dir: Path) -> dict:
    """
    Runs compilation pipeline and returns:
      {
        "outputs": outputs_index,
        "manifest_path": ".../compilator_manifest.json"
      }

    outputs_index[variant][source]["python"] -> path
    outputs_index[variant][source]["optimizer"][pass_name] -> path
    outputs_index[variant][source]["translator"] -> path
    """
    comp = getattr(cfg.pipeline, "compilator", None)
    if comp is None or not comp.enabled:
        return {"outputs": {}}

    yaml_p = Path(yaml_path).resolve()

    # Load copied params.json from dataset
    params_json_path = (Path(dataset.root) / cfg.params.config_path).resolve()
    json_cfg = json.loads(params_json_path.read_text(encoding="utf-8"))

    workdir = _resolve_relative_to_yaml(yaml_p, comp.python.workdir).resolve()
    python_exe = comp.python.venv_python or sys.executable

    base = Path(out_dir)
    base.mkdir(parents=True, exist_ok=True)

    # write python runner
    runner_path = (base / "_py_compile_runner.py").resolve()
    runner_path.write_text(_PY_RUNNER, encoding="utf-8")

    manifest: Dict[str, Any] = {
        "yaml_path": str(yaml_p),
        "workdir": str(workdir),
        "repeats": comp.repeats,
        "on_failure": comp.on_failure,
        "params_json_path": str(params_json_path),
        "params_json_sha256": _sha256_file(params_json_path),
        "versions": {
            "python": _run_version([python_exe, "--version"], workdir),
            "optimizer": _run_version([comp.tools.optimizer.bin, "--version"], workdir),
            "translator": _run_version(
                [comp.tools.translator.bin, "--version"], workdir
            ),
        },
        "variants": [],
    }

    outputs_index: Dict[str, Dict[str, Dict[str, Any]]] = {}
    variables = dict(comp.variables or {})

    n_sources = len(comp.python_sources)
    max_workers = cfg.execution.cpu_count

    for var in comp.variants:
        var_dir = base / var.name
        var_out_dir = var_dir / "outputs"
        log_dir = var_dir / "logs"
        var_out_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        outputs_index[var.name] = {}
        var_rec: Dict[str, Any] = {"name": var.name, "sources": []}

        # Build one task-dict per source — all plain Python so they pickle cleanly
        tasks = [
            {
                "src_name": src.name,
                "src_source_file": src.source_file,
                "src_function": src.function,
                "src_method": src.method,
                "src_method_args": list(src.method_args),
                "src_method_kwargs": dict(src.method_kwargs or {}),
                "src_result_tuple_index": src.result_tuple_index,
                "src_output_file": src.output_file,
                "var_name": var.name,
                "optimizer_passes": [
                    {
                        "name": p.name,
                        "flags": list(p.flags),
                        "source_flags": dict(p.source_flags),
                        "output_file": p.output_file,
                        "depends_on": p.depends_on,
                    }
                    for p in var.optimizer_passes
                ],
                "program_variants": [
                    {
                        "name": pv.name,
                        "input_pass": pv.input_pass,
                        "flags": list(pv.flags),
                        "output_file": pv.output_file,
                    }
                    for pv in var.program_variants
                ],
                "out_dir": str(var_out_dir),
                "log_dir": str(log_dir),
                "runner_path": str(runner_path),
                "python_exe": python_exe,
                "workdir": str(workdir),
                "json_cfg": json_cfg,
                "variables": variables,
                "repeats": comp.repeats,
                "on_failure": comp.on_failure,
                "optimizer_bin": comp.tools.optimizer.bin,
                "optimizer_base_flags": list(comp.tools.optimizer.base_flags),
                "translator_bin": comp.tools.translator.bin,
                "translator_base_flags": list(comp.tools.translator.base_flags),
                "translator_global_flags": list(comp.tools.translator.flags or []),
                "extra_sys_path": list(comp.python.extra_sys_path or []),
            }
            for src in comp.python_sources
        ]

        # Determine progress bar labels for this variant (step order matches pipeline)
        step_keys = ["python"]
        for p in var.optimizer_passes:
            step_keys.append(f"optimizer:{p.name}")
        for pv in var.program_variants:
            step_keys.append(f"translator:{pv.name}")

        # Run sources in parallel; preserve original source ordering in manifest
        results: Dict[str, dict] = {}
        src_labels = [t["src_name"] for t in tasks]
        with Manager() as mgr:
            progress_queue = mgr.Queue()
            for t in tasks:
                t["progress_queue"] = progress_queue

            # One tqdm bar per compilation step; total = repeats (regardless of
            # number of sources — the drain thread normalises by n_sources).
            bar_total = comp.repeats
            prefix = f"[{var.name}]"
            bars = {
                step: tqdm(
                    total=bar_total,
                    desc=f"{prefix} {_step_label(step)}",
                    unit="compile",
                    leave=True,
                )
                for step in step_keys
            }

            stop_event = threading.Event()
            drain_thread = threading.Thread(
                target=_drain_progress,
                args=(progress_queue, bars, stop_event, n_sources),
                daemon=True,
            )
            drain_thread.start()

            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                future_to_src = {
                    executor.submit(_compile_one_source, t): t["src_name"]
                    for t in tasks
                }
                for future in as_completed(future_to_src):
                    src_name = future_to_src[future]
                    results[src_name] = future.result()  # re-raises on worker error

            stop_event.set()
            drain_thread.join()
            for bar in bars.values():
                bar.close()

        for src_name in src_labels:
            r = results[src_name]
            var_rec["sources"].append(r["src_rec"])
            outputs_index[var.name][src_name] = r["outputs"]

        manifest["variants"].append(var_rec)
    manifest_path = base / "compilator_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {"outputs": outputs_index, "manifest_path": str(manifest_path)}
