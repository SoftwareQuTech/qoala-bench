from __future__ import annotations

from typing import Any, Dict, List

from qoala_bench.analyzers.base import AnalyzeResult, DataAnalyzer
from qoala_bench.registry import register_analyzer


@register_analyzer("noop")
class NoopAnalyzer(DataAnalyzer):
    def analyze(self, dataset_dirs: List[str], params: Dict[str, Any]) -> AnalyzeResult:
        return AnalyzeResult(
            outputs={"datasets": dataset_dirs, "note": "noop analyzer"}
        )
