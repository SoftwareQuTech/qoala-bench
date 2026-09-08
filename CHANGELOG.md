CHANGELOG
=========

2026-09-08 (0.1.0)
-------------------

First release. Attribution is given per entry as *(author, PR)*. Contributors
in this release: @spoukke.

`qoala-bench` drives end-to-end experiments on quantum-network programs
compiled with the Qoala stack. One YAML configuration walks a program through
four stages — compilation with [euqalyptus](https://softwarequtech.github.io/euqalyptus/)
and [qoala-mlir](https://softwarequtech.github.io/qoala-mlir/), dataset
generation, NetSquid simulation through `qoala-sim`, and analysis — and
produces a self-contained results folder holding the MLIR intermediates, the
raw simulation output and CSV summaries. It is the harness behind the results
in [*A Multi-Level Compiler Pipeline for Qoala Quantum Internet Programs*](https://ieeexplore.ieee.org/document/11662182)
(IEEE QSW 2026).

### Requirements

- **Python 3.10 – 3.12.** The upper bound comes from `qoala-mlir`, which
  publishes cp310–cp312 wheels only.
- **`qoala >= 2.1.0`**, and not merely as a floor: `qoala_bench.simulation`
  sets `check_qubit_ancestry=True` on every node, which that release
  introduced. Without it the simulator lets a local routine run on a qubit
  still holding an unrelated block's state, so any program where the compiler
  reuses a qubit slot — block reordering does so from three rounds up —
  reports a success rate that is silently too low.
- **`qoala-opt` and `qoala-translate` on `PATH`**, plus SCIP 9.2 for them to
  link against. Both are published as qoala-mlir release artifacts and are
  fetched by `make tools`; nothing needs to be built from source. The bundled
  YAML configurations name the two binaries without a path and resolve them
  through `PATH`.
- **A NetSquid account**, since NetSquid is licensed and served from a private
  index. `make install-dev` adds that index.

### Included

- The `generate`, `analyze` and `add-steps` subcommands, the `compare` and
  `heuristic` generators, and the `simple` and `noop` analysers.
- Benchmark configurations for the BQC and rotation experiments reported in the
  paper, under `benchmark/`, together with the three scripts that run, analyse
  and plot them.
- Worked examples under `examples/`, exercised end-to-end by
  `examples/run_examples.py` (`make examples`).
- A Dockerfile and compose file that assemble the whole toolchain locally. The
  image is deliberately not published to any registry: it contains NetSquid,
  which each user obtains under their own account.

### Notes

- The pre-computed measurements behind the paper are published separately as a
  dataset rather than committed here — see the README.
- Branching is not yet documented.
  *(@spoukke)*
