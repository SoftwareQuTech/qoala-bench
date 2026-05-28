from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from qoala_bench.config import RootConfig
from qoala_bench.dataset import DatasetPaths


@dataclass(frozen=True)
class GenerateResult:
    dataset_dir: str


class DataGenerator(ABC):
    @abstractmethod
    def generate(self, cfg: RootConfig, dataset, comp_state=None) -> GenerateResult: ...
