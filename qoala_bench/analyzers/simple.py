from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from qoala.util.runner import AppResult
from qoala_bench.analyzers.base import AnalyzeResult, DataAnalyzer
from qoala_bench.registry import register_analyzer
from qoala_bench.utils import SimulationResult, load_all_results_from_directory


@register_analyzer("simple")
class SimpleAnalyzer(DataAnalyzer):
    """
    Generic analyzer that extracts success + duration from AppResult objects.

    Config params:
      - node: str            (e.g. "bob")
      - outcome_key: str     (e.g. "outcome")
      - success_value: Any   (e.g. 0)
    """

    def analyze(self, dataset_dirs: List[str], params: Dict[str, Any]) -> AnalyzeResult:
        node = params["node"]
        default_outcome_key = params["outcome_key"]
        # Optional per-label override: outcome_key_by_label: {label: key}
        outcome_key_by_label: Dict[str, str] = params.get("outcome_key_by_label", {})
        success_value = params["success_value"]

        all_summaries = []

        for dataset_dir in dataset_dirs:
            raw_dir = Path(dataset_dir) / "raw"

            for task_dir in sorted(raw_dir.iterdir()):
                if not task_dir.is_dir():
                    continue

                label = task_dir.name
                outcome_key = outcome_key_by_label.get(label, default_outcome_key)
                app_results = load_all_results_from_directory(str(task_dir))
                sim_results = self._extract_results(
                    app_results,
                    node=node,
                    outcome_key=outcome_key,
                    success_value=success_value,
                )

                summary = self._summarize(sim_results)
                summary["task"] = label
                summary["dataset"] = Path(dataset_dir).name

                self._write_csv(
                    Path(dataset_dir) / "analysis" / f"{label}_results.csv",
                    sim_results,
                )

                all_summaries.append(summary)

                # nice UX for heuristic
                print(
                    f"[{label}] "
                    f"success={summary['success_percentage']:.2f}% "
                    f"(n={summary['iterations']}), "
                    f"mean_duration={summary['mean_duration']:.2f}"
                )

        # write global summary if multiple tasks or datasets
        if len(all_summaries) > 1:
            self._write_summary_csv(
                Path(dataset_dirs[0]) / "analysis" / "summary.csv",
                all_summaries,
            )

        return AnalyzeResult(outputs={"summaries": all_summaries})

    def _extract_results(
        self,
        app_results: List[AppResult],
        *,
        node: str,
        outcome_key: str,
        success_value: Any,
    ) -> List[SimulationResult]:
        results: List[SimulationResult] = []

        for app_result in app_results:
            batch = app_result.batch_results[node]
            outcomes = batch.results
            timestamps = batch.timestamps

            for i, outcome in enumerate(outcomes):
                success = outcome.values[outcome_key] == success_value
                start, end = timestamps[i]
                duration = end - start
                results.append(SimulationResult(success, duration))

        return results

    def _summarize(self, results: List[SimulationResult]) -> Dict[str, Any]:
        successes = sum(r.success for r in results)
        durations = np.array([r.duration for r in results], dtype=float)

        return {
            "iterations": len(results),
            "success_count": successes,
            "fail_count": len(results) - successes,
            "success_percentage": 100.0 * successes / len(results) if results else 0.0,
            "mean_duration": float(durations.mean()) if results else 0.0,
            "std_duration": float(durations.std()) if results else 0.0,
            "min_duration": float(durations.min()) if results else 0.0,
            "max_duration": float(durations.max()) if results else 0.0,
        }

    def _write_csv(self, path: Path, results: List[SimulationResult]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["success", "duration"])
            for r in results:
                writer.writerow([r.success, r.duration])

    def _write_summary_csv(self, path: Path, rows: List[Dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        keys = rows[0].keys()
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)
