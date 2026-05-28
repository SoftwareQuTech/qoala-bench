"""qoala-bench: benchmarking harness for the Qoala compiler stack.

`qoala-bench` is the test-bench around the Qoala compiler stack — the
[euqalyptus](https://github.com/QuTech-Delft/qoala-compiler) Python
frontend, the [qoala-mlir](https://github.com/QuTech-Delft/qoala-mlir)
MLIR pipeline, and the `qoala-sim` NetSquid-based simulator. From a
single YAML configuration file, it drives a benchmark through four
stages — compilation, dataset generation, simulation, and analysis —
and writes everything (intermediate MLIR artifacts, raw NetSquid
results, summary CSVs) into a self-contained dataset folder under
``results/``.

The user-facing entry points live under:

- :mod:`qoala_bench.cli` — the command-line driver
  (``generate``, ``analyze``, ``add-steps``).
- :mod:`qoala_bench.config` — Pydantic models for the YAML
  configuration schema.
- :mod:`qoala_bench.compilator` — pass-by-pass invocation of
  ``qoala-opt`` and ``qoala-translate``.
- :mod:`qoala_bench.simulation` — multi-process NetSquid simulation
  driver.
- :mod:`qoala_bench.generators` and :mod:`qoala_bench.analyzers` —
  pluggable generator and analyser implementations, looked up by name
  through :mod:`qoala_bench.registry`.

See the project ``README.md`` for end-to-end usage and the bundled
benchmark configurations under ``benchmark/``.
"""
