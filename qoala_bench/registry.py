from __future__ import annotations

from typing import Dict, Type

from qoala_bench.analyzers.base import DataAnalyzer
from qoala_bench.generators.base import DataGenerator

GENERATOR_REGISTRY: Dict[str, Type[DataGenerator]] = {}
ANALYZER_REGISTRY: Dict[str, Type[DataAnalyzer]] = {}


def register_generator(type_name: str):
    def deco(cls: Type[DataGenerator]):
        GENERATOR_REGISTRY[type_name] = cls
        return cls

    return deco


def register_analyzer(type_name: str):
    def deco(cls: Type[DataAnalyzer]):
        ANALYZER_REGISTRY[type_name] = cls
        return cls

    return deco
