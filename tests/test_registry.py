"""Tests for the analyser / generator registries.

The registries in :mod:`qoala_bench.registry` are populated as a side
effect of the ``@register_*`` decorators in the analyser and generator
modules. These tests verify the decorator behaviour in isolation,
without depending on which concrete implementations happen to be
registered when the suite runs.
"""

from __future__ import annotations

import pytest

from qoala_bench import registry
from qoala_bench.analyzers.base import AnalyzeResult, DataAnalyzer
from qoala_bench.generators.base import DataGenerator


class _DummyAnalyzer(DataAnalyzer):
    def analyze(self, dataset_dirs, params):  # noqa: D401
        return AnalyzeResult(outputs={"dataset_dirs": list(dataset_dirs)})


class _DummyGenerator(DataGenerator):
    def generate(self, cfg, dataset, comp_state=None):  # noqa: D401
        return None


@pytest.fixture(autouse=True)
def _isolate_registries(monkeypatch):
    """Snapshot and restore the two registries around each test."""
    monkeypatch.setattr(registry, "GENERATOR_REGISTRY", dict(registry.GENERATOR_REGISTRY))
    monkeypatch.setattr(registry, "ANALYZER_REGISTRY", dict(registry.ANALYZER_REGISTRY))


def test_register_analyzer_inserts_class_under_given_name():
    @registry.register_analyzer("dummy")
    class _A(_DummyAnalyzer):
        pass

    assert registry.ANALYZER_REGISTRY["dummy"] is _A


def test_register_generator_inserts_class_under_given_name():
    @registry.register_generator("dummy")
    class _G(_DummyGenerator):
        pass

    assert registry.GENERATOR_REGISTRY["dummy"] is _G


def test_register_returns_the_decorated_class_unchanged():
    @registry.register_analyzer("dummy_returns")
    class _A(_DummyAnalyzer):
        pass

    # Identity check: the decorator must not wrap the class.
    assert registry.ANALYZER_REGISTRY["dummy_returns"] is _A
    instance = _A()
    assert isinstance(instance, DataAnalyzer)


def test_register_overwrites_existing_entry():
    @registry.register_analyzer("dup")
    class _First(_DummyAnalyzer):
        pass

    @registry.register_analyzer("dup")
    class _Second(_DummyAnalyzer):
        pass

    assert registry.ANALYZER_REGISTRY["dup"] is _Second


def test_registries_are_independent():
    @registry.register_analyzer("name")
    class _A(_DummyAnalyzer):
        pass

    @registry.register_generator("name")
    class _G(_DummyGenerator):
        pass

    assert registry.ANALYZER_REGISTRY["name"] is _A
    assert registry.GENERATOR_REGISTRY["name"] is _G
    assert registry.ANALYZER_REGISTRY["name"] is not registry.GENERATOR_REGISTRY["name"]
