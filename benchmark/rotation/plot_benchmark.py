#!/usr/bin/env python3
"""
Plot rotation benchmark results: success probability and compilation time vs n.

Produces:
  - success_probability.{fmt}       — optimized vs unoptimized success rate
  - compilation_lowering.{fmt}      — Python→HIR, HIR→MIR, MIR→LIR, Translation
  - compilation_optimizations.{fmt} — RotFold, HIR→MIR(opt), MIR→LIR(opt), Reorder, Translation

Usage:
    python benchmark/rotation/plot_benchmark.py N=results/folder ... -o OUT_DIR

    e.g.:
    python benchmark/rotation/plot_benchmark.py \\
        1=results/rotation-n1_ti_200 \\
        ...
        8=results/rotation-n8_ti_200 \\
        -o results/rotation-plots_ti_200

Options:
    -o / --output        Output directory for plots (default: current directory)
    --format             Output format: pdf, png, svg (default: pdf)
    --title              Optional title suffix
    --compilation-only   Only produce compilation time charts; skip success plot
"""

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

_LINE_STYLES = {
    "optimized": dict(
        color="#2196F3",
        marker="o",
        linestyle="-",
        linewidth=2,
        markersize=7,
        label="optimized",
    ),
    "unoptimized": dict(
        color="#FF9800",
        marker="s",
        linestyle="--",
        linewidth=2,
        markersize=7,
        label="unoptimized",
    ),
}


def load_summary(folder: str) -> pd.DataFrame:
    path = Path(folder) / "analysis" / "summary.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def load_manifest(folder: str) -> dict | None:
    path = (
        Path(folder)
        / "artifacts"
        / "compilator"
        / "compilator"
        / "compilator_manifest.json"
    )
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Static analysis (ESP / QMem) helpers
# ---------------------------------------------------------------------------


def _parse_analysis_value(path: str, tag: str) -> float | None:
    """Return the float after '[<tag>]:' on the first matching line of *path*."""
    try:
        with open(path) as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith(f"[{tag}]"):
                    _, _, rest = stripped.partition(":")
                    return float(rest.strip())
    except (FileNotFoundError, ValueError, OSError):
        pass
    return None


def load_analysis_from_manifest(manifest: dict) -> dict:
    """
    Extract ESP and QMem efficiency values from manifest pass outputs.

    The primary variant (first whose name is not 'optimized'/'unoptimized',
    e.g. 'rotation') is used.  Falls back to the first variant.

    Returns::

        {
          'esp':  {'unopt': float|None, 'opt': float|None},
          'qmem': {
              'client': {'unopt': float|None, 'opt': float|None},
              'server': {'unopt': float|None, 'opt': float|None},
          }
        }

    ESP is the *product* of all sources (client × server).
    """
    variants = manifest.get("variants", [])
    target = next(
        (
            v
            for v in variants
            if v.get("name", "").lower() not in ("optimized", "unoptimized")
        ),
        variants[0] if variants else None,
    )
    if target is None:
        return {}

    # Build {src_name: {pass_name: output_path}}
    pass_outputs: dict[str, dict[str, str]] = {}
    for src in target.get("sources", []):
        src_name = src["name"]
        pass_outputs[src_name] = {}
        for stage in src.get("stages", []):
            if stage.get("stage") == "optimizer":
                pname = stage.get("pass", "")
                opath = stage.get("output_path", "")
                if pname and opath:
                    pass_outputs[src_name][pname] = opath

    # ESP product across all sources
    esp: dict[str, float | None] = {}
    for suffix, pname in [("unopt", "step_esp_unopt"), ("opt", "step_esp_opt")]:
        vals = []
        for passes in pass_outputs.values():
            if pname in passes:
                v = _parse_analysis_value(passes[pname], "ESP")
                if v is not None:
                    vals.append(v)
        esp[suffix] = float(np.prod(vals)) if vals else None

    # QMem per source
    qmem: dict[str, dict[str, float | None]] = {}
    for src_name, passes in pass_outputs.items():
        qmem[src_name] = {}
        for suffix, pname in [("unopt", "step_qmem_unopt"), ("opt", "step_qmem_opt")]:
            v = (
                _parse_analysis_value(passes[pname], "QMem Efficiency")
                if pname in passes
                else None
            )
            qmem[src_name][suffix] = v

    return {"esp": esp, "qmem": qmem}


# ---------------------------------------------------------------------------
# Compilation time extraction
# ---------------------------------------------------------------------------

# Lowering graph: stages on the unoptimized path + unoptimized translation
_STAGES_LOWERING = [
    ("python", "Python → HIR", "#4FC3F7"),
    ("step1_hir_to_mir", "HIR → MIR", "#81C784"),
    ("step2_mir_to_lir", "MIR → LIR", "#FFB74D"),
    ("translation_unopt", "Translation", "#CE93D8"),
]

# Optimizations graph: the two rotation-specific passes + their lowering + opt translation
_STAGES_OPT = [
    ("step3_rotfold", "Rotation folding", "#EF5350"),
    ("step4_hir_to_mir_opt", "HIR → MIR (opt)", "#81C784"),
    ("step5_mir_to_lir_opt", "MIR → LIR (opt)", "#FFB74D"),
    ("step6_reorder", "Reorder blocks", "#F06292"),
    ("translation_opt", "Translation", "#CE93D8"),
]

_ALL_STAGE_KEYS = {k for k, _, _ in _STAGES_LOWERING + _STAGES_OPT}


def _stage_key(stage: dict) -> str | None:
    """Map a manifest stage entry to an internal stage key, or None to skip."""
    s = stage["stage"]
    if s == "python":
        return "python"
    if s == "optimizer":
        return stage.get("pass")  # "step1_hir_to_mir", "step3_rotfold", etc.
    if s == "translator":
        pv = stage.get("program_variant", "")
        return "translation_unopt" if pv == "unoptimized" else "translation_opt"
    return None


def compile_times_by_stage(manifest: dict) -> dict[str, dict[str, float]]:
    """
    Return {source_name: {stage_key: mean_seconds}}.

    The rotation compilator has a single variant ("rotation") that contains
    all pipeline steps.  We use that variant directly.
    """
    variants = manifest["variants"]
    # Use the first (and typically only) variant
    target = variants[0]
    result: dict[str, dict[str, float]] = {}
    for source in target["sources"]:
        name: str = source["name"]
        result[name] = {}
        for stage in source["stages"]:
            key = _stage_key(stage)
            if key is None or key not in _ALL_STAGE_KEYS:
                continue
            result[name][key] = result[name].get(key, 0.0) + stage["stats"]["mean_s"]
    return result


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

_SRC_COLORS = ["#1565C0", "#E65100", "#2E7D32", "#6A1B9A"]


def plot_success(
    ax: plt.Axes,
    ns: list,
    summaries: dict,
    title_suffix: str = "",
    manifests: dict | None = None,
) -> None:
    """Line chart: simulated success probability + ESP product vs number of rotations.

    Color code: blue = optimized, orange = unoptimized.
    Line style: solid = simulation, dashed = ESP (analytical estimate).
    """
    series = {label: [] for label in _LINE_STYLES}

    for n in ns:
        df = summaries[n]
        for label in _LINE_STYLES:
            row = df[df["task"] == label]
            series[label].append(
                float(row["success_percentage"].iloc[0])
                if not row.empty
                else float("nan")
            )

    sim_styles = {
        "optimized": dict(
            **{
                k: v
                for k, v in _LINE_STYLES["optimized"].items()
                if k not in ("label", "linestyle")
            },
            linestyle="-",
            label="Sim. optimized",
        ),
        "unoptimized": dict(
            **{
                k: v
                for k, v in _LINE_STYLES["unoptimized"].items()
                if k not in ("label", "linestyle")
            },
            linestyle="-",
            label="Sim. unoptimized",
        ),
    }
    for label, style in sim_styles.items():
        ax.plot(ns, series[label], **style)

    # ESP product (client × server) as dashed lines
    esp_series: dict[str, list[float]] = {"opt": [], "unopt": []}
    if manifests:
        for n in ns:
            if n in manifests:
                analysis = load_analysis_from_manifest(manifests[n])
                esp = analysis.get("esp", {})
                v_opt = esp.get("opt")
                v_unopt = esp.get("unopt")
                esp_series["opt"].append(
                    v_opt * 100.0 if v_opt is not None else float("nan")
                )
                esp_series["unopt"].append(
                    v_unopt * 100.0 if v_unopt is not None else float("nan")
                )
            else:
                esp_series["opt"].append(float("nan"))
                esp_series["unopt"].append(float("nan"))

        if any(not np.isnan(v) for v in esp_series["opt"]):
            ax.plot(
                ns,
                esp_series["opt"],
                linewidth=2,
                linestyle="--",
                color=_LINE_STYLES["optimized"]["color"],
                label="ESP optimized",
            )
        if any(not np.isnan(v) for v in esp_series["unopt"]):
            ax.plot(
                ns,
                esp_series["unopt"],
                linewidth=2,
                linestyle="--",
                color=_LINE_STYLES["unoptimized"]["color"],
                label="ESP unoptimized",
            )

    # Dynamic y-axis scaling with 15% padding, snapped to 5 pp (include ESP)
    all_vals = [v for vals in series.values() for v in vals if not np.isnan(v)]
    if manifests:
        all_vals += [v for vals in esp_series.values() for v in vals if not np.isnan(v)]
    if all_vals:
        lo, hi = min(all_vals), max(all_vals)
        span = max(hi - lo, 5.0)
        pad = span * 0.15
        y_min = max(0.0, lo - pad)
        y_max = min(100.0, hi + pad)
        y_min = 5.0 * (y_min // 5)
        y_max = 5.0 * (-(-y_max // 5))
    else:
        y_min, y_max = 0.0, 100.0

    ax.set_xlabel("Number of rotations", fontsize=14)
    ax.set_ylabel("Success probability (%)", fontsize=14)
    ax.set_xticks(ns)
    ax.set_ylim(y_min, y_max)
    y_range = y_max - y_min
    major_step = 10 if y_range > 30 else 5 if y_range > 10 else 2
    ax.yaxis.set_major_locator(ticker.MultipleLocator(major_step))
    ax.yaxis.set_minor_locator(ticker.MultipleLocator(major_step / 2))
    ax.grid(True, which="major", alpha=0.25)
    ax.grid(True, which="minor", alpha=0.10)
    ax.legend(fontsize=15)
    if title_suffix:
        ax.set_title(f"Rotation benchmark — {title_suffix}", fontsize=15)


def plot_qmem(
    ax: plt.Axes,
    ns: list,
    manifests: dict,
    src: str,
) -> None:
    """Line graph: qubit memory efficiency for one node (client or server).

    Color code: blue = optimized, orange = unoptimized.
    """
    data: dict[str, list[float]] = {"unopt": [], "opt": []}

    for n in ns:
        if n in manifests:
            analysis = load_analysis_from_manifest(manifests[n])
            qmem = analysis.get("qmem", {})
            for suffix in ("unopt", "opt"):
                v = qmem.get(src, {}).get(suffix)
                data[suffix].append(v * 100.0 if v is not None else float("nan"))
        else:
            for suffix in ("unopt", "opt"):
                data[suffix].append(float("nan"))

    for suffix in ("unopt", "opt"):
        color = _LINE_STYLES["optimized" if suffix == "opt" else "unoptimized"]["color"]
        ax.plot(
            ns,
            data[suffix],
            marker="o",
            linewidth=2,
            markersize=6,
            color=color,
            label=suffix.capitalize(),
        )

    ax.set_xlabel("Number of rotations", fontsize=14)
    ax.set_ylabel("Memory efficiency (%)", fontsize=14)
    ax.set_xticks(ns)
    ax.set_ylim(-5, 105)
    ax.yaxis.set_minor_locator(ticker.MultipleLocator(10))
    ax.grid(True, which="major", alpha=0.25)
    ax.legend(fontsize=15)


def _make_compilation_figure(
    ns: list,
    all_data: dict,
    all_sources: list,
    stage_list: list,
    title: str = "",
) -> plt.Figure:
    """Grouped bar chart per n, stacked by compilation stage."""
    from matplotlib.patches import Patch

    n_groups = len(ns)
    bar_w = 0.25
    gap = 0.04
    half_span = (len(all_sources) * bar_w + (len(all_sources) - 1) * gap) / 2
    src_offset = {
        src: -half_span + i * (bar_w + gap) + bar_w / 2
        for i, src in enumerate(all_sources)
    }
    x_base = np.arange(n_groups)
    src_color = {
        src: _SRC_COLORS[i % len(_SRC_COLORS)] for i, src in enumerate(all_sources)
    }

    fig, ax = plt.subplots(figsize=(9, 5))

    for src in all_sources:
        x_pos = x_base + src_offset[src]
        bottoms = np.zeros(n_groups)
        for sk, sl, sc in stage_list:
            heights = np.array(
                [all_data[ns[i]].get(src, {}).get(sk, 0.0) for i in range(n_groups)]
            )
            ax.bar(
                x_pos,
                heights,
                bar_w,
                bottom=bottoms,
                color=sc,
                edgecolor="white",
                linewidth=0.4,
                zorder=3,
            )
            bottoms += heights
        ax.text(
            x_base[-1] + src_offset[src],
            bottoms[-1] * 1.02,
            src,
            ha="center",
            va="bottom",
            fontsize=10,
            color=src_color[src],
        )

    ax.set_xticks(x_base, [str(n) for n in ns], fontsize=12)
    ax.set_xlabel("Number of rotations", fontsize=12)
    ax.set_ylabel("Mean time (s)", fontsize=12)
    ax.grid(True, axis="y", alpha=0.22, zorder=0)
    ax.legend(
        handles=[Patch(facecolor=c, label=l) for _, l, c in stage_list],
        fontsize=11,
        loc="upper left",
        framealpha=0.85,
        edgecolor="#ccc",
    )
    if title:
        ax.set_title(title, fontsize=14)
    fig.tight_layout()
    return fig


def plot_compilation_lowering(ns: list, manifests: dict) -> plt.Figure:
    """Bar chart for lowering stages (Python→HIR, HIR→MIR, MIR→LIR, Translation)."""
    all_data = {n: compile_times_by_stage(manifests[n]) for n in ns}
    all_sources = sorted({src for d in all_data.values() for src in d})
    return _make_compilation_figure(
        ns,
        all_data,
        all_sources,
        _STAGES_LOWERING,
        title="Lowering pipeline",
    )


def plot_compilation_optimizations(ns: list, manifests: dict) -> plt.Figure:
    """Bar chart for optimization stages (RotFold, lowering opt, Reorder, Translation)."""
    all_data = {n: compile_times_by_stage(manifests[n]) for n in ns}
    all_sources = sorted({src for d in all_data.values() for src in d})
    return _make_compilation_figure(
        ns,
        all_data,
        all_sources,
        _STAGES_OPT,
        title="Optimization pipeline",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "datasets",
        nargs="+",
        metavar="N=FOLDER",
        help="Mapping of integer n to dataset folder, e.g. 1=results/rotation-n1_ti_200",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=".",
        metavar="DIR",
        help="Output directory for plot files (default: current directory)",
    )
    parser.add_argument(
        "--format",
        default="pdf",
        choices=["pdf", "png", "svg"],
        help="Output file format (default: pdf)",
    )
    parser.add_argument(
        "--title",
        default="",
        metavar="SUFFIX",
        help="Optional suffix appended to the plot title",
    )
    parser.add_argument(
        "--compilation-only",
        action="store_true",
        default=False,
        help="Only produce compilation time charts; skip success probability plot",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    mapping: dict = {}
    for entry in args.datasets:
        if "=" not in entry:
            print(f"Error: expected N=FOLDER, got: {entry!r}", file=sys.stderr)
            return 1
        n_str, folder = entry.split("=", 1)
        try:
            n = int(n_str)
        except ValueError:
            print(f"Error: n must be an integer, got: {n_str!r}", file=sys.stderr)
            return 1
        mapping[n] = folder

    ns = sorted(mapping)
    summaries: dict = {}
    manifests: dict = {}
    skipped: list = []

    for n in ns:
        folder = mapping[n]

        if not args.compilation_only:
            try:
                summaries[n] = load_summary(folder)
            except FileNotFoundError as exc:
                print(f"Warning: missing {exc}, skipping n={n}", file=sys.stderr)
                skipped.append(n)
                continue

        manifest = load_manifest(folder)
        if manifest is None:
            print(
                f"Warning: compilator_manifest.json not found in {folder}, "
                f"n={n} excluded from compilation charts",
                file=sys.stderr,
            )
        else:
            manifests[n] = manifest

    ns = [n for n in ns if n not in skipped]
    if not ns:
        print("Error: no valid datasets found.", file=sys.stderr)
        return 1

    os.makedirs(args.output, exist_ok=True)

    # --- Plot 1: success probability (skipped in compilation-only mode) ---
    if not args.compilation_only:
        fig1, ax1 = plt.subplots(figsize=(8, 5))
        plot_success(
            ax1,
            ns,
            summaries,
            title_suffix=args.title,
            manifests=manifests if manifests else None,
        )
        fig1.tight_layout()
        out1 = os.path.join(args.output, f"success_probability.{args.format}")
        fig1.savefig(out1, dpi=150)
        print(f"Saved: {out1}")

    # --- Plot 1b: memory efficiency — one file per node ---
    if not args.compilation_only and manifests:
        ns_qmem = [n for n in ns if n in manifests]
        if ns_qmem:
            for src in ("client", "server"):
                fig1b, ax1b = plt.subplots(figsize=(8, 5))
                plot_qmem(ax1b, ns_qmem, manifests, src=src)
                fig1b.tight_layout()
                out1b = os.path.join(
                    args.output, f"memory_efficiency_{src}.{args.format}"
                )
                fig1b.savefig(out1b, dpi=150)
                print(f"Saved: {out1b}")
                plt.close(fig1b)

    # --- Plot 2: lowering stages ---
    ns_comp = [n for n in ns if n in manifests]
    if ns_comp:
        fig2 = plot_compilation_lowering(ns_comp, manifests)
        out2 = os.path.join(args.output, f"compilation_lowering.{args.format}")
        fig2.savefig(out2, dpi=150)
        print(f"Saved: {out2}")

        fig3 = plot_compilation_optimizations(ns_comp, manifests)
        out3 = os.path.join(args.output, f"compilation_optimizations.{args.format}")
        fig3.savefig(out3, dpi=150)
        print(f"Saved: {out3}")
    else:
        print(
            "No compilator manifests found; skipping compilation time plots.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
