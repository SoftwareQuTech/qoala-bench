#!/usr/bin/env python3
"""Run every example under ``examples/`` end-to-end and report the outcome.

This is the script behind ``make examples``. Each entry in :data:`EXAMPLES`
names one of the YAML configurations shipped in this directory, the mode it
is run in, and whether it needs the ``qoala-opt``/``qoala-translate``
binaries from qoala-mlir. For every example the runner invokes the same CLI
a user would type::

    python -m qoala_bench.cli generate <config> -o <dataset-name>
    python -m qoala_bench.cli analyze results/<dataset-name>

Datasets land under ``results/<dataset-name>``; the runner deletes a
previous dataset of the same name first, because ``generate`` refuses to
write into an existing folder. The examples are checked for *running*, not
for a particular success rate — the noisy hardware configurations do not
produce a deterministic outcome.

Run ``python examples/run_examples.py --help`` for the available options.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# Binaries that the compilator stage shells out to. The example YAMLs refer
# to them by bare name, so they are resolved through PATH.
TOOL_BINARIES = ("qoala-opt", "qoala-translate")

# Default cap on execution.iterations. The shipped configs are sized for
# real experiments (up to 10_000 iterations); an example run only has to
# show that the pipeline works.
DEFAULT_MAX_ITERATIONS = 100


@dataclass(frozen=True)
class Example:
    """One example invocation of the qoala-bench CLI."""

    name: str
    config: str
    description: str
    needs_tools: bool = False
    compilation_only: bool = False
    # Extra CLI flags appended to the `generate` call.
    generate_flags: List[str] = field(default_factory=list)

    @property
    def dataset(self) -> str:
        """Name of the dataset folder created under ``results/``."""
        return f"example-{self.name}"


EXAMPLES: List[Example] = [
    Example(
        name="teleport-prepare-first",
        config="examples/teleport/heuristic-prepare_first.yaml",
        description=(
            "Heuristic generator over a hand-written .iqoala pair "
            "(prepare-first teleport schedule); no compiler toolchain needed."
        ),
    ),
    Example(
        name="teleport-entangle-first",
        config="examples/teleport/heuristic-entangle_first.yaml",
        description=(
            "Same program compiled the other way round (entangle-first "
            "schedule), run through the heuristic generator."
        ),
    ),
    Example(
        name="teleport-compare",
        config="examples/teleport/compare.yaml",
        description=(
            "Compare generator: runs both teleport schedules in one dataset "
            "so the analyser reports them side by side."
        ),
    ),
    Example(
        name="bqc-n1",
        config="examples/bqc/compile-and-compare.1.yaml",
        description=(
            "Full pipeline for one BQC round: euqalyptus -> HIR -> MIR -> LIR "
            "-> iQoala, translated both unoptimized and optimized, then "
            "simulated and compared."
        ),
        needs_tools=True,
    ),
    Example(
        name="bqc-n2",
        config="examples/bqc/compile-and-compare.2.yaml",
        description="Same as bqc-n1 with two BQC rounds.",
        needs_tools=True,
    ),
    Example(
        name="bqc-n3",
        config="examples/bqc/compile-and-compare.3.yaml",
        description=(
            "Three BQC rounds. From three rounds up the optimizer reuses a "
            "qubit slot, which is what `check_qubit_ancestry` guards; both "
            "variants should still report 100% under perfect parameters."
        ),
        needs_tools=True,
    ),
    Example(
        name="bqc-n4-compile-only",
        config="examples/bqc/compile-and-compare.4.yaml",
        description=(
            "Compilation-only run (--compilation-only) for four BQC rounds: "
            "exercises the compiler stage and its timing manifest without "
            "paying for simulation."
        ),
        needs_tools=True,
        compilation_only=True,
    ),
]

# examples/bqc/compile-and-compare.{1..7}.yaml all run end-to-end at 100% for
# both variants. Only the first few are listed here to keep `make examples`
# quick; use --only to run a specific one.


def _tools_on_path() -> List[str]:
    """Return the tool binaries from :data:`TOOL_BINARIES` missing on PATH."""
    return [name for name in TOOL_BINARIES if shutil.which(name) is None]


def _capped_config(
    example: Example, max_iterations: int, cpu_count: Optional[int]
) -> Optional[Path]:
    """Write a copy of ``example.config`` with cheaper execution settings.

    Returns the path of the copy, or ``None`` when the original config
    already satisfies the caps and can be used as-is. The copy is written
    next to the original because ``compilator.python.workdir`` is resolved
    relative to the config file's own directory.
    """
    original = REPO_ROOT / example.config
    with open(original, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    execution = raw.setdefault("execution", {})
    changes = {}

    iterations = execution.get("iterations", 1)
    if iterations > max_iterations:
        execution["iterations"] = max_iterations
        changes["iterations"] = f"{iterations} -> {max_iterations}"

    if cpu_count is not None and execution.get("cpu_count", 2) > cpu_count:
        changes["cpu_count"] = f"{execution['cpu_count']} -> {cpu_count}"
        execution["cpu_count"] = cpu_count

    if not changes:
        return None

    capped = original.with_name(f".run_examples.{example.name}.yaml")
    with open(capped, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, sort_keys=False)

    details = ", ".join(f"{k}: {v}" for k, v in changes.items())
    print(f"    capped for this run ({details})")
    return capped


def _run_cli(args: List[str]) -> int:
    """Run the qoala-bench CLI from the repo root and return its exit code."""
    argv = [sys.executable, "-m", "qoala_bench.cli"] + args
    print(f"    $ {' '.join(argv)}")
    return subprocess.run(argv, cwd=REPO_ROOT).returncode


def run_example(
    example: Example, max_iterations: int, cpu_count: Optional[int], keep: bool
) -> bool:
    """Run one example (``generate``, then ``analyze``) and report success."""
    results_dir = REPO_ROOT / "results" / example.dataset

    # `generate` refuses to write into an existing dataset folder.
    if results_dir.exists():
        print(f"    removing previous dataset {results_dir.relative_to(REPO_ROOT)}")
        shutil.rmtree(results_dir)

    capped = _capped_config(example, max_iterations, cpu_count)
    config = str((capped or (REPO_ROOT / example.config)).relative_to(REPO_ROOT))

    try:
        generate = ["generate", config, "-o", example.dataset]
        if example.compilation_only:
            generate.append("--compilation-only")
        generate += example.generate_flags

        if _run_cli(generate) != 0:
            return False

        # Compilation-only runs produce no simulation output to analyse.
        if (
            not example.compilation_only
            and _run_cli(["analyze", str(results_dir)]) != 0
        ):
            return False
    finally:
        if capped is not None:
            capped.unlink(missing_ok=True)
        if not keep and results_dir.exists():
            shutil.rmtree(results_dir)

    return True


def main() -> int:
    """Entry point: run the selected examples and summarise the results."""
    parser = argparse.ArgumentParser(
        description="Run the qoala-bench examples end-to-end."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the available examples and exit.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="NAME",
        default=None,
        help="Run only the named examples (see --list).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
        help=(
            "Cap execution.iterations for every example "
            f"(default: {DEFAULT_MAX_ITERATIONS}). Use a large value to run "
            "the configs exactly as they are committed."
        ),
    )
    parser.add_argument(
        "--cpu-count",
        type=int,
        default=None,
        help=(
            "Cap execution.cpu_count (default: the number of usable CPUs, "
            "so the examples do not oversubscribe a CI runner)."
        ),
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the results/ folders instead of deleting them afterwards.",
    )
    parser.add_argument(
        "--allow-missing-tools",
        action="store_true",
        help=(
            "Skip the examples that need qoala-opt/qoala-translate instead of "
            "failing when those binaries are not on PATH."
        ),
    )
    args = parser.parse_args()

    if args.list:
        for example in EXAMPLES:
            tools = " [needs qoala-mlir binaries]" if example.needs_tools else ""
            print(
                f"{example.name}{tools}\n    {example.config}\n    "
                f"{example.description}\n"
            )
        return 0

    selected = EXAMPLES
    if args.only is not None:
        by_name = {e.name: e for e in EXAMPLES}
        unknown = [name for name in args.only if name not in by_name]
        if unknown:
            parser.error(
                f"unknown example(s): {', '.join(unknown)}. "
                f"Available: {', '.join(by_name)}"
            )
        selected = [by_name[name] for name in args.only]

    cpu_count = args.cpu_count
    if cpu_count is None:
        # len(os.sched_getaffinity(0)) is the CPU budget the runner actually
        # gave us, which os.cpu_count() overstates in a container.
        cpu_count = len(os.sched_getaffinity(0))

    missing_tools = _tools_on_path()
    if missing_tools:
        print(f"note: not on PATH: {', '.join(missing_tools)}")

    outcomes: List[tuple[str, str, float]] = []
    for example in selected:
        print(f"\n=== {example.name} ({example.config}) ===")
        print(f"    {example.description}")

        if example.needs_tools and missing_tools:
            if args.allow_missing_tools:
                print(f"    SKIPPED: needs {', '.join(missing_tools)}")
                outcomes.append((example.name, "skipped", 0.0))
                continue
            print(
                f"    FAILED: needs {', '.join(missing_tools)} on PATH. Install "
                "the qoala-mlir release binaries (make tools) or pass "
                "--allow-missing-tools to skip this example."
            )
            outcomes.append((example.name, "failed", 0.0))
            continue

        start = time.monotonic()
        ok = run_example(example, args.max_iterations, cpu_count, args.keep)
        elapsed = time.monotonic() - start
        print(f"    {'OK' if ok else 'FAILED'} in {elapsed:.0f}s")
        outcomes.append((example.name, "ok" if ok else "failed", elapsed))

    print("\n=== summary ===")
    for name, status, elapsed in outcomes:
        print(f"{status.upper():>8}  {name}  ({elapsed:.0f}s)")

    failed = [name for name, status, _ in outcomes if status == "failed"]
    if failed:
        print(f"\n{len(failed)} example(s) failed: {', '.join(failed)}")
        return 1

    skipped = [name for name, status, _ in outcomes if status == "skipped"]
    if skipped:
        print(f"\nAll examples passed ({len(skipped)} skipped).")
    else:
        print("\nAll examples passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
