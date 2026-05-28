"""Command-line entry point for ``qoala-bench``.

Defines the three subcommands the tool exposes — ``generate``,
``analyze``, and ``add-steps`` — and dispatches to the corresponding
``cmd_*`` helpers. Invoke from a shell with::

    python -c "from qoala_bench.cli import main; main()" <subcommand> [args]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure implementations are imported so decorators run
import qoala_bench.analyzers.noop  # noqa: F401
import qoala_bench.analyzers.simple  # noqa: F401
import qoala_bench.generators.compare  # noqa: F401
import qoala_bench.generators.heuristic  # noqa: F401
from qoala_bench.compilator import run_add_steps, run_compilator
from qoala_bench.config import load_config_yaml
from qoala_bench.dataset import (
    copy_config_into_dataset,
    create_dataset_dir,
    freeze_config_to_dataset_yaml,
    sha256_file,
    write_environment,
    write_meta,
)
from qoala_bench.params_schema import validate_simulation_config
from qoala_bench.registry import ANALYZER_REGISTRY, GENERATOR_REGISTRY


def cmd_generate(
    config_path: str, output_name: str | None = None, compilation_only: bool = False
) -> int:
    """Run the ``generate`` subcommand end-to-end.

    Loads the benchmark YAML at ``config_path``, creates a fresh dataset
    folder under ``results/<output_name>`` (or ``results/dataset-<uuid>``
    when ``output_name`` is ``None``), and walks the four pipeline stages:
    the compilator (which emits HIR/MIR/LIR MLIR plus iQoala variants),
    the generator (which enumerates simulation entries into
    ``dataset.yaml``), the simulator (run by the chosen generator), and
    the analyser (run later via :func:`cmd_analyze`). When
    ``compilation_only`` is true, only the compilator runs; the
    simulation and analysis stages are skipped.

    Args:
        config_path: Path to the benchmark YAML configuration file.
        output_name: Optional folder name under ``results/`` for the
            dataset. Defaults to the ``name`` field of the YAML, or
            ``dataset-<uuid>`` when neither is set.
        compilation_only: When ``True``, skip simulation and analysis;
            useful for compile-time-only benchmarks.

    Returns:
        ``0`` on success. Non-zero exit codes are surfaced via raised
        exceptions rather than return values.

    Raises:
        RuntimeError: If the compilator is enabled but
            :func:`run_compilator` returns ``None``.
        ValueError: If the configured ``generator.type`` is not
            registered in :data:`GENERATOR_REGISTRY`.
    """
    cfg = load_config_yaml(config_path)

    dataset = create_dataset_dir(base_dir="results", name=output_name)
    uuid_str = dataset.root.name.replace("dataset-", "")

    # Copy params.json into dataset and rewrite cfg.params.config_path to relative path
    copied_cfg_path = copy_config_into_dataset(
        cfg.params.config_path, dataset.artifacts_config
    )
    with open(copied_cfg_path, "r", encoding="utf-8") as f:
        cfg_json = json.load(f)

    # strict check: same fields, no extras
    validate_simulation_config(cfg_json, allow_extra_keys=False)
    copied_rel = str(copied_cfg_path.relative_to(dataset.root))

    # Hashes (start with config)
    hashes = {copied_rel: sha256_file(copied_cfg_path)}

    # Freeze resolved yaml into dataset.yaml (includes uuid/ran/dataset_version)
    freeze_config_to_dataset_yaml(cfg, dataset, uuid_str, copied_rel)

    # env snapshot
    write_environment(dataset)

    # -------------------------
    # Run compilator (if configured)
    # -------------------------
    comp_state = None
    comp_cfg = getattr(cfg.pipeline, "compilator", None)

    if comp_cfg is not None and comp_cfg.enabled:
        print("DEBUG: compilator enabled =", comp_cfg.enabled)
        print("DEBUG: dataset.root =", dataset.root)
        print("DEBUG: artifact_subdir =", comp_cfg.artifact_subdir)

        comp_dir = dataset.artifacts_compilator / comp_cfg.artifact_subdir
        comp_dir.mkdir(parents=True, exist_ok=True)

        print("DEBUG: compilator output dir =", comp_dir)
        print("DEBUG: comp_dir exists =", comp_dir.exists())

        # ✅ Run compilator ONCE, with explicit out_dir
        comp_state = run_compilator(
            cfg=cfg,
            dataset=dataset,
            yaml_path=config_path,
            out_dir=comp_dir,
        )

        if comp_state is None:
            raise RuntimeError(
                "Compilator is enabled but run_compilator returned None. "
                "Make sure run_compilator returns a dict (e.g. {'outputs': ...})."
            )

        if isinstance(comp_state, dict):
            print("DEBUG: comp_state keys =", list(comp_state.keys()))
        else:
            print("DEBUG: comp_state type =", type(comp_state))

        produced_files = [p for p in comp_dir.rglob("*") if p.is_file()]
        print(
            f"DEBUG: compilator produced {len(produced_files)} files under {comp_dir}"
        )

        if len(produced_files) == 0:
            print(
                "⚠️  WARNING: compilator produced no files in the expected directory. "
                "This usually means run_compilator is writing somewhere else."
            )

        for p in produced_files:
            rel = str(p.relative_to(dataset.root))
            hashes[rel] = sha256_file(p)

    else:
        print("DEBUG: compilator missing or disabled; skipping.")

    # -------------------------
    # Generator selection (skipped in compilation-only mode)
    # -------------------------
    if compilation_only:
        print("ℹ️  Compilation-only mode: skipping simulation and analysis.")
    else:
        gen_type = cfg.pipeline.generator.type
        gen_cls = GENERATOR_REGISTRY.get(gen_type)
        if gen_cls is None:
            raise ValueError(
                f"Unknown generator type '{gen_type}'. Registered: {list(GENERATOR_REGISTRY)}"
            )

        gen = gen_cls()

        # Always pass comp_state (None is fine); keep generator API consistent
        gen.generate(cfg, dataset, comp_state=comp_state)

    # Hash any .iqoala programs in artifacts/programs (legacy copy mode)
    for p in dataset.artifacts_programs.rglob("*.iqoala"):
        rel = str(p.relative_to(dataset.root))
        hashes[rel] = sha256_file(p)

    # Also hash any .iqoala emitted by compilator (compiled mode)
    # (Only if we actually ran compilator)
    if comp_state is not None:
        artifacts_root = getattr(dataset, "artifacts", None)
        if artifacts_root is None:
            artifacts_root = dataset.root / "artifacts"
        comp_dir = artifacts_root / cfg.pipeline.compilator.artifact_subdir
        if comp_dir.exists():
            for p in comp_dir.rglob("*.iqoala"):
                rel = str(p.relative_to(dataset.root))
                hashes[rel] = sha256_file(p)

    write_meta(dataset, hashes)

    print(f"✅ Dataset created: {dataset.root}")
    return 0


def cmd_add_steps(
    config_path: str,
    dataset_folder: str,
    repeats_override: int | None = None,
) -> int:
    """Run the ``add-steps`` subcommand on an existing dataset.

    Diffs the ``optimizer_passes`` list of the supplied YAML against the
    ``compilator_manifest.json`` inside ``dataset_folder`` and runs only
    the passes that are not yet recorded. The command is idempotent: if
    every pass in the YAML already has a manifest entry, the underlying
    :func:`run_add_steps` prints "nothing to add" and returns without
    re-running any compilation.

    Args:
        config_path: Path to the benchmark YAML containing the new
            passes to add.
        dataset_folder: Path to an existing dataset folder (produced
            by a previous ``generate`` run).
        repeats_override: Optional override for the number of timing
            repeats per pass; when ``None``, the value from the YAML's
            compilator section is used.

    Returns:
        ``0`` on success, ``1`` if the YAML's compilator section is
        missing or disabled.
    """
    cfg = load_config_yaml(config_path)
    comp_cfg = getattr(cfg.pipeline, "compilator", None)
    if comp_cfg is None or not comp_cfg.enabled:
        print("Error: compilator not configured or disabled in YAML", file=sys.stderr)
        return 1
    run_add_steps(cfg, dataset_folder, config_path, repeats_override=repeats_override)
    return 0


def cmd_analyze(dataset_dirs: list[str]) -> int:
    """Run the ``analyze`` subcommand on one or more datasets.

    Reads the analyser configuration from each dataset's
    ``dataset.yaml`` and runs the corresponding analyser implementation
    (from :data:`ANALYZER_REGISTRY`) on the raw simulation output.
    Writes ``analysis/summary.csv`` and ``analysis/per_iteration.csv``
    inside each dataset folder.

    When multiple dataset folders are passed, they must all specify the
    same ``analyzer.type`` in their ``dataset.yaml`` — analysing a
    heterogeneous mix in a single call is not supported (the analyser
    would not know how to combine them).

    Args:
        dataset_dirs: One or more paths to existing dataset folders.
            Each folder must contain a ``dataset.yaml`` produced by a
            previous ``generate`` run.

    Returns:
        ``0`` on success.

    Raises:
        ValueError: If ``dataset_dirs`` is empty, if the datasets
            disagree on the analyser type, or if the configured type
            is not registered in :data:`ANALYZER_REGISTRY`.
        FileNotFoundError: If any of the dataset folders is missing
            ``dataset.yaml``.
    """
    # read analyzer selection from each dataset.yaml? v1: require a single analyzer type across inputs
    import yaml

    if not dataset_dirs:
        raise ValueError("No dataset dirs provided")

    analyzer_type = None
    analyzer_params = None

    for d in dataset_dirs:
        dataset_yaml = Path(d) / "dataset.yaml"
        if not dataset_yaml.exists():
            raise FileNotFoundError(f"Missing dataset.yaml in {d}")

        with open(dataset_yaml, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        this_type = data["pipeline"]["analyzer"]["type"]
        this_params = data["pipeline"]["analyzer"].get("params", {})

        if analyzer_type is None:
            analyzer_type = this_type
            analyzer_params = this_params
        elif this_type != analyzer_type:
            raise ValueError(
                f"All datasets must specify the same analyzer type for one analyze call. "
                f"Got '{analyzer_type}' and '{this_type}'."
            )

    analyzer_cls = ANALYZER_REGISTRY.get(analyzer_type)
    if analyzer_cls is None:
        raise ValueError(
            f"Unknown analyzer type '{analyzer_type}'. Registered: {list(ANALYZER_REGISTRY)}"
        )

    analyzer = analyzer_cls()
    res = analyzer.analyze(dataset_dirs, analyzer_params)
    print(f"✅ Analysis complete: {res.outputs}")
    return 0


def main() -> int:
    """CLI entry point for the ``qoala-bench`` tool.

    Builds the ``argparse`` parser, registers the three subcommands
    (``generate``, ``analyze``, ``add-steps``), and dispatches to the
    corresponding ``cmd_*`` helper. Invoke from a shell via:

    ```sh
    python -c "from qoala_bench.cli import main; main()" <subcommand> [...]
    ```

    Returns:
        Process exit code: ``0`` on success, non-zero if an unrecognised
        subcommand was supplied.
    """
    parser = argparse.ArgumentParser("qs")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pgen = sub.add_parser("generate", help="Generate a dataset from YAML config")
    pgen.add_argument("config", type=str)
    pgen.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Name for the dataset folder (default: dataset-<uuid>)",
    )
    pgen.add_argument(
        "--compilation-only",
        action="store_true",
        default=False,
        help="Run only the compilation pipeline; skip simulation and analysis",
    )

    pana = sub.add_parser("analyze", help="Analyze one or more existing datasets")
    pana.add_argument("datasets", nargs="+", type=str)

    padd = sub.add_parser(
        "add-steps",
        help="Add new compilation passes to an existing dataset without re-running everything",
    )
    padd.add_argument(
        "config", type=str, help="YAML config file (with new passes added)"
    )
    padd.add_argument("dataset", type=str, help="Path to existing dataset folder")
    padd.add_argument(
        "--repeats",
        type=int,
        default=None,
        help="Override number of timing repeats (default: use YAML value)",
    )

    args = parser.parse_args()

    if args.cmd == "generate":
        return cmd_generate(
            args.config, output_name=args.output, compilation_only=args.compilation_only
        )
    if args.cmd == "analyze":
        return cmd_analyze(args.datasets)
    if args.cmd == "add-steps":
        return cmd_add_steps(args.config, args.dataset, repeats_override=args.repeats)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
