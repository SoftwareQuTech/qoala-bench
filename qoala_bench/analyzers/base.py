from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class AnalyzeResult:
    outputs: Dict[str, Any]


class DataAnalyzer(ABC):
    @abstractmethod
    def analyze(
        self, dataset_dirs: List[str], params: Dict[str, Any]
    ) -> AnalyzeResult: ...
