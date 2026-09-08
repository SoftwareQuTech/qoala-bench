# qoala-bench

`qoala-bench` is the benchmarking framework that drives end-to-end experiments on quantum-network programs compiled with the [Qoala compiler stack](https://ieeexplore.ieee.org/document/11662182). It takes a single YAML configuration file as input and walks a program through four pipeline stages — *compilation* (with [euqalyptus](https://softwarequtech.github.io/euqalyptus/) and [qoala-mlir](https://softwarequtech.github.io/qoala-mlir/)), *dataset generation* (enumerating program variants and hardware parameters), *simulation* (via NetSquid through [qoala-sim](https://github.com/QuTech-Delft/qoala-sim)), and *analysis* (computing success rates and per-stage timing). The same configuration produces a self-contained results folder that includes the intermediate MLIR artifacts, the raw NetSquid output, and CSV summaries.

This repository is the third leaf of the Qoala compiler stack. [euqalyptus](https://softwarequtech.github.io/euqalyptus/) is the Python frontend that emits Qoala HIR from user programs, [qoala-mlir](https://softwarequtech.github.io/qoala-mlir/) is the MLIR-based middle and back end that lowers HIR to the `.iqoala` executable format, and `qoala-bench` is the harness that exercises both — together with `qoala-sim`, which performs the NetSquid-backed simulation — to produce the empirical results reported in the accompanying paper.

## Installation

`qoala-bench` is a Python package supporting Python 3.10 – 3.12. NetSquid is licensed software served from a private index, so set your credentials (free account at <https://netsquid.org/>) and install from a checkout with:

```bash
export NETSQUIDPYPI_USER=... NETSQUIDPYPI_PWD=...
make install-dev          # or `make install` without the dev extras
```

`make install-dev` is `pip install -e .[dev]` with the NetSquid index added. Everything else — `qoala`, `euqalyptus`, `qoala-mlir` (the `qnet` Python bindings), and the scientific-Python stack — comes from PyPI; the full list is pinned in `setup.cfg`.

`qoala >= 2.1.0` is a hard requirement, not just a floor: `qoala_bench.simulation` sets `check_qubit_ancestry=True` on every node, which only exists from that release. Without it the simulator lets a local routine run on a qubit still holding an unrelated block's state, so any program where the compiler reuses a qubit slot — block reordering does from three rounds up — reports a success rate that is silently too low.

The `qoala-opt` and `qoala-translate` binaries from [qoala-mlir](https://softwarequtech.github.io/qoala-mlir/) must also be reachable. They are published as release artifacts, so there is no need to build the compiler from source:

```bash
make tools                                   # downloads them into .tools/bin
export PATH="$PWD/.tools/bin:$PATH"
```

`qoala-opt` links against `libscip.so.9.2`, so [SCIP](https://www.scipopt.org/) 9.2 must be installed system-wide (on Ubuntu 24.04, the `SCIPOptSuite-9.2.2-Linux-ubuntu24.deb` package). The benchmark YAMLs refer to both binaries by bare name and resolve them through `PATH`; you can also point at them explicitly from the YAML's `tools` section (see the configuration reference below).

If you would rather not assemble the toolchain yourself, use the Docker image described below — it contains all of the above.

## Quick start

Every operation goes through the same `cli.main` entry point, invoked either via `python -c "from qoala_bench.cli import main; main()"` or — once you set it up locally — as a console script. The three commands that cover most workflows are:

```bash
# Run a full benchmark (compile → simulate → analyze) and store everything under results/bqc-n1
python -c "from qoala_bench.cli import main; main()" \
    generate benchmark/bqc/compile-and-compare.1.yaml -o bqc-n1

# Compilation-only timing benchmark (skip simulation entirely)
python -c "from qoala_bench.cli import main; main()" \
    generate benchmark/bqc/compile-only.1.yaml -o bqc-compile-only-n1 \
    --compilation-only

# Compute success rates from raw simulation output
python -c "from qoala_bench.cli import main; main()" \
    analyze results/bqc-n1
```

Two further commands cover incremental and plotting workflows:

```bash
# Add new compilation passes to an existing dataset without re-running simulation
python -c "from qoala_bench.cli import main; main()" \
    add-steps benchmark/bqc/compile-only.1.yaml results/bqc-compile-only-n1

# Plot success-rate trends across n values
python benchmark/bqc/plot_benchmark.py \
    1=results/bqc-n1_ti_rdam3-leiden3 \
    2=results/bqc-n2_ti_rdam3-leiden3 \
    3=results/bqc-n3_ti_rdam3-leiden3 \
    -o results/bqc-plots_rdam3-leiden3 --name bqc_rdam3_leiden3
```

And to run every benchmark, analyze, and plot in one shot:

```bash
bash run_benchmark.sh
bash analyze_benchmark.sh
bash plot_benchmark.sh
```

## How it works

Each benchmark is driven by a single YAML configuration file and walks through four sequential pipeline stages:

```
YAML config
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Compilator                                               │
│    Python source → HIR MLIR → MIR MLIR → LIR MLIR           │
│    → iQoala (unoptimized + optimized variants)              │
│    Timing data stored in compilator_manifest.json           │
└─────────────────────────────┬───────────────────────────────┘
                              │ compiled programs
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Generator                                                │
│    Builds dataset: enumerates (program_variant, params)     │
│    combinations; writes dataset.yaml                        │
└─────────────────────────────┬───────────────────────────────┘
                              │ dataset.yaml
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Simulator                                                │
│    Runs NetSquid simulation for each dataset entry,         │
│    multi-processed; stores raw results as .pkl.gz files     │
└─────────────────────────────┬───────────────────────────────┘
                              │ raw results
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Analyser                                                 │
│    Reads outcome keys from simulation results,              │
│    computes success rate; writes summary.csv                │
└─────────────────────────────────────────────────────────────┘
```

The `--compilation-only` flag short-circuits the pipeline after stage 1, producing only compilation-timing data — useful when you want to compare compile speeds without paying for NetSquid simulation. The `add-steps` command re-enters stage 1 incrementally for passes not yet recorded in an existing dataset's manifest, so you can extend a previously-generated dataset with new compiler passes without recompiling everything from scratch.

## CLI reference

All commands are accessed via the same entry point. The three subcommands are `generate`, `analyze`, and `add-steps`.

`generate <config.yaml> [-o NAME] [--compilation-only]` is the main entry point. It accepts the path to a benchmark configuration file as its only positional argument; `-o NAME` sets the dataset folder name (under `results/NAME`) and defaults to the `name` field of the YAML; `--compilation-only` runs the compilator only and skips the simulation + analysis stages.

`analyze <dataset_folder>` reads the raw simulation results inside an existing dataset folder and writes `analysis/summary.csv`. It requires a completed `generate` run (i.e. one that was not invoked with `--compilation-only`).

`add-steps <config.yaml> <dataset_folder> [--repeats N]` diffs the YAML's `optimizer_passes` list against the dataset's `compilator_manifest.json` and runs only the passes that are not yet recorded. It is safe to re-run — if the dataset is already up to date, the command prints `nothing to add` and exits cleanly.

## Configuration file reference

A benchmark YAML is structured into a small top-level header (`name`, `author`, `metadata`), the `params` section that drives every simulation entry, an `execution` section controlling parallelism and failure handling, and the `pipeline` section that wires the compilator, generator, simulator, and analyser together. The smallest non-trivial config looks like this:

```yaml
version: 1

name: "my-benchmark"          # used as default dataset folder name
author: "Sacha Bernheim"
metadata:
  tags: ["bqc", "compile-only"]
  notes: >
    Free-text description.

params:
  config_path: "benchmark/bqc/trapped-ions_rotterdam3-leiden3.json"
  nodes:
  - node_name: client
    num_qubits: 2
    inputs: {}                # static inputs passed to the program
  - node_name: server
    num_qubits: 1
    inputs: {}
  qstate_formalism: "DM"      # "DM" (density matrix) or "KET"

execution:
  iterations: 100             # simulation repetitions per dataset entry
  cpu_count: 11               # worker processes
  on_failure: "stop"          # "stop" | "ignore"
  store_logs: false
  log_level: "INFO"

pipeline:

  # ── Compilator ────────────────────────────────────────────────────────────
  compilator:
    enabled: true
    artifact_subdir: "compilator"
    repeats: 1                # how many times to time each pass (use 10000
                              # for compile-only benchmarks)
    on_failure: "stop"

    variables:                # substituted via {var:name} in args/flags
      n: 1
      singular_comm_ops: true

    python_sources:
    - name: "client"
      source_file: "client.py"          # relative to workdir
      function: "client_bqc_streaming"  # function that returns the program
      method: "compile"
      method_args: ["server", "{var:n}"]
      method_kwargs:
        singular_comm_ops: "{var:singular_comm_ops}"
      result_tuple_index: 1             # index into function return tuple
      output_file: "{source_name}.hir.mlir"

    - name: "server"
      source_file: "server.py"
      function: "server_bqc_streaming"
      method: "compile"
      method_args: ["client", "{var:n}"]
      method_kwargs:
        singular_comm_ops: "{var:singular_comm_ops}"
      result_tuple_index: 1
      output_file: "{source_name}.hir.mlir"

    tools:
      optimizer:
        bin: "/path/to/qoala-opt"
        base_flags: []
      translator:
        bin: "/path/to/qoala-translate"
        base_flags: []
        flags: []

    variants:
    - name: "bqc"
      optimizer_passes:
      - name: "step1_hir_to_mir"
        flags: ["--lower-qoala-hir-to-mir"]
        output_file: "{source_name}.1.mir.mlir"
      - name: "step2_mir_to_lir"
        flags: ["--lower-qoala-mir-to-lir"]
        output_file: "{source_name}.2.lir.mlir"
      - name: "step4_opt"
        flags: ["--qoalahost-reorder-blocks"]
        output_file: "{source_name}.4.opt.lir.mlir"

      program_variants:
      - name: "unoptimized"
        input_pass: "step2_mir_to_lir"  # which pass's output to translate
        flags: ["--mlir-to-iqoala"]
        output_file: "{source_name}.unoptimized.iqoala"
      - name: "optimized"
        input_pass: "step4_opt"
        flags: ["--mlir-to-iqoala"]
        output_file: "{source_name}.optimized.iqoala"

  # ── Generator ─────────────────────────────────────────────────────────────
  generator:
    type: "compare"           # "compare" enumerates program_variants
    params:
      programs:
      - label: "unoptimized"
        program_variant: "unoptimized"
      - label: "optimized"
        program_variant: "optimized"

  # ── Analyser ──────────────────────────────────────────────────────────────
  analyzer:
    type: "simple"
    params:
      node: "client"          # which node's result to check
      outcome_key: "%3"       # variable name in the iQoala program output
      success_value: 0        # value that counts as success
```

### Hardware parameter JSON

The `config_path` field points at a JSON file that sets the physical-network parameters consumed by NetSquid:

| Key | Description |
|-----|-------------|
| `link_noise_type` | Noise model for entanglement links (e.g. `"depolarise"`) |
| `link_t1`, `link_t2` | T1/T2 coherence times for link qubits (ns) |
| `node_t1`, `node_t2` | T1/T2 for memory qubits (ns) |
| `gate_noise_type` | Gate noise model |
| `gate_fidelity` | Single/two-qubit gate fidelity |
| `meas_fidelity` | Measurement fidelity |
| `link_speed` | Classical communication speed (m/s) |
| `network_distance` | Node separation (km) |

## Dataset folder structure

After a successful `generate` run, the dataset folder is fully self-contained: it holds the input YAML, every compiled artifact, the raw simulation output, and the analysis CSVs. A typical layout looks like this:

```
results/bqc-n1_ti_rdam3-leiden3/
│
├── dataset.yaml                    # generated dataset: list of (program, params) entries
├── meta.yaml                       # run metadata + sha256 of every compile artifact
├── environment.yaml                # Python/package versions at run time
│
├── artifacts/
│   ├── config/
│   │   └── config.yaml             # copy of the input YAML used for this run
│   │
│   └── compilator/
│       └── compilator/
│           ├── compilator_manifest.json   # records every pass: flags, output paths,
│           │                              # timing stats (n, mean_s, p95_s, std_s)
│           └── bqc/                       # one subfolder per variant name
│               └── outputs/
│                   ├── client.hir.mlir
│                   ├── client.1.mir.mlir
│                   ├── client.2.lir.mlir
│                   ├── client.4.opt.lir.mlir
│                   ├── client.unoptimized.iqoala
│                   ├── client.optimized.iqoala
│                   ├── server.hir.mlir
│                   └── ...                # analogous server files
│
├── raw/
│   ├── unoptimized/
│   │   ├── results-0.pkl.gz        # simulation results for iteration 0
│   │   ├── results-1.pkl.gz
│   │   └── ...                     # one file per iteration
│   └── optimized/
│       └── ...
│
└── analysis/
    ├── summary.csv                 # per-label: n_iterations, success_rate, ...
    └── per_iteration.csv           # per-(label, iteration): outcome values
```

The key files are `dataset.yaml`, the flat list of simulation jobs (each entry names a program label, the iQoala file paths per node, and the hardware config — the simulator reads it to know what to run); `compilator_manifest.json`, the compiler's ledger that records the exact flags, output paths, and timing statistics for every source × pass combination (the plot scripts read this to draw compilation-time charts); the per-iteration `raw/<label>/results-N.pkl.gz` gzipped pickles containing the raw NetSquid output; and `analysis/summary.csv`, the human-readable summary `analyze` writes — one row per program label with columns `label`, `iterations`, `successes`, `success_rate`.

### Integrity

`generate` writes a `hashes:` map into `meta.yaml` with a SHA-256 for every compile-time artifact in the dataset: `params.json`, the runner script, the compilator manifest, every MLIR intermediate (`*.hir.mlir`, `*.mir.mlir`, `*.lir.mlir`), every `.iqoala` output, and every per-pass `stderr.log`. The simulation outputs (`raw/**/*.pkl.gz`, `raw/**/*.jsonl.gz`), the analysis CSVs, and `simulation_timing.json` are **not** hashed — they are deterministic given the seed sequence recorded in `raw/<label>/seeds.jsonl.gz`, but tamper-evidence stops at the compile boundary. To verify every hashed file in a dataset folder:

```bash
cd results/bqc-n1_ti_rdam3-leiden3
python -c '
import hashlib, pathlib, sys, yaml
m = yaml.safe_load(open("meta.yaml"))
bad = [p for p, h in m["hashes"].items()
       if hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() != h.split(":",1)[1]]
sys.exit(print("\n".join(bad) or "OK") or len(bad))
'
```

## Running the bundled benchmarks

Three shell scripts orchestrate the full pipeline used in the paper:

```bash
bash run_benchmark.sh      # generate all datasets (compile + simulate)
bash analyze_benchmark.sh  # compute success rates
bash plot_benchmark.sh     # produce all the plots
```

The bundled benchmarks fall into four families. The **BQC** family covers five hardware configurations crossed with `n = 1..6` (`compile-and-compare-{rd3,dd,rd2,150,200}.{n}.yaml`); the **BQC compile-only** family runs the same set with `n = 1..6` and `10 000` repeats per pass for tight compile-time statistics (`compile-only.{n}.yaml`, no simulation); the **rotation** family covers `n = 1..8` on the trapped-ion configuration at 200 km (`benchmark/rotation/compile-and-compare.{n}.yaml`); and the **rotation compile-only** family is the rotation analogue with `n = 1..8`.

### Pre-computed results

Running everything takes a long time, and the results reported in the paper are published as a dataset instead of being committed here: **[Data supporting the publication *A Multi-Level Compiler Pipeline for Qoala Quantum Internet Programs*](https://doi.org/10.4121/bcac962c-fa21-40c5-9908-44ea5ccaaa5a.v1)** (4TU.ResearchData, MIT-licensed). It holds the raw NetSquid output, the compiler intermediates (MLIR and iQoala), the compile-time measurements, the aggregated success-rate and duration tables, and the paper's figures. The folders are laid out exactly as [described below](#dataset-folder-structure), so `analyze` and the plotting scripts run against them unchanged.

## Writing your own benchmark

Adding a new benchmark is a four-step exercise. First, write the quantum program in Python using the [euqalyptus](https://softwarequtech.github.io/euqalyptus/) API. The function must accept the peer node name and any parameters and return a compiled program object (or a tuple where index `result_tuple_index` contains the program). Second, create a hardware-parameter JSON by copying one of the existing files under `benchmark/bqc/` and adapting the fidelities, coherence times, and inter-node distance. Third, write a YAML configuration following the reference above — set `config_path`, the `nodes` qubit counts, the `variables` block, the `python_sources` block, and the analyser's `outcome_key` / `success_value` to match your program's output variable. Fourth, run:

```bash
python -c "from qoala_bench.cli import main; main()" \
    generate my-benchmark.yaml -o my-results
python -c "from qoala_bench.cli import main; main()" \
    analyze results/my-results
```

## Docker: bootstrapping the toolchain locally

Assembling the toolchain by hand means a Python 3.10–3.12 environment, NetSquid credentials, a system SCIP 9.2, and the two qoala-mlir binaries on `PATH`. The [`Dockerfile`](Dockerfile) in this repository does all of that in one shot, so you can go from a fresh clone to a working pipeline without touching your host: it bundles Python 3.10, `qoala-opt`/`qoala-translate`, the SCIP runtime they link against, and `qoala-bench` installed editable together with `qoala`, `euqalyptus` and `qoala-mlir`. Nothing is compiled from source, so the build takes a couple of minutes rather than the hours the paper's artifact image needed.

> **The image is built locally and is not published anywhere.** It contains NetSquid, which is licensed software that each user obtains under their own account, so it is not ours to redistribute. There is no `docker pull` for it — build it yourself with your own credentials.

### Build

Copy [`.env.example`](.env.example) to `.env` and fill in your NetSquid credentials, then:

```bash
docker compose build
```

The credentials are passed as BuildKit secrets, so they never end up in the image or its history. `make docker-build` does the same thing with a plain `docker build`, reading `NETSQUIDPYPI_USER`/`NETSQUIDPYPI_PWD` from your shell instead of `.env`.

### Use

```bash
docker compose run --rm qoala-bench                          # interactive shell
docker compose run --rm qoala-bench make tests examples      # or: make docker-verify
docker compose run --rm qoala-bench \
    python -m qoala_bench.cli generate examples/bqc/compile-and-compare.1.yaml -o bqc-n1
```

The checkout is mounted over `/workspace/qoala-bench` and the package is installed editable, so local edits take effect immediately and datasets written to `results/` land in your working tree. `qoala-opt` and `qoala-translate` are on `PATH` at `/usr/local/bin`, which is all the benchmark YAMLs need.

The smoke-test script from the paper artifact runs the same way, subject to the `n >= 3` limitation noted below:

```bash
docker compose run --rm qoala-bench bash check.sh
```

To pin a different toolchain version, override the build args: `QOALA_MLIR_VERSION` (which qoala-mlir release the binaries come from), `SCIP_VERSION`, and `PYTHON_VERSION`.

## Development

```bash
make lint            # isort, black, flake8 over qoala_bench, tests, examples, benchmark
make mypy            # type-check qoala_bench
make tests           # pytest (make tests-parallel for pytest-xdist)
make examples        # run every example end-to-end (python examples/run_examples.py)
make verify          # all of the above
make docker-build    # build the image
make docker-verify   # run the tests and examples inside the image
```

`examples/run_examples.py` drives each configuration under `examples/` through `generate` and `analyze` exactly as a user would, capping `execution.iterations` at 100 so a full pass takes well under a minute. Use `--list` to see the examples, `--only NAME` to run one, `--keep` to keep the `results/` folders, and `--max-iterations` to run the configs at their committed iteration counts. Examples that need the compiler binaries fail with a clear message when those are not on `PATH`; pass `--allow-missing-tools` to skip them instead.

The runner lists only the first few BQC sizes so that `make examples` stays quick. All seven `examples/bqc/compile-and-compare.{1..7}.yaml` run end-to-end and report 100% success for both the optimized and the unoptimized variant under the perfect hardware parameters in `examples/configs/perfect.json`; `bash check.sh` walks the same seven.

### Continuous integration

Three workflows live under `.github/workflows/`:

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yaml` | every push | `lint` → `mypy` → `tests` and `examples` on Python 3.10, 3.11 and 3.12 |
| `docker.yaml` | pull requests touching the image definition, or manual dispatch | builds the image and runs the tests and examples inside it; never pushes it |
| `release.yaml` | pushing a `vX.Y.Z` tag, or manual dispatch | tests on 3.10/3.11/3.12, builds the sdist and wheel, then publishes — to PyPI and a GitHub Release on a tag, to TestPyPI on a dispatch |

They need two repository secrets, `NETSQUIDPYPI_USER` and `NETSQUIDPYPI_PWD`, for the NetSquid index. Publishing uses [trusted publishing](https://docs.pypi.org/trusted-publishers/) rather than API tokens, so it needs no secrets of its own — instead it needs two GitHub environments, `pypi` and `testpypi`, and a matching trusted publisher registered on each index (workflow `release.yaml`, environment `pypi` / `testpypi`). Until `qoala-bench` exists on an index, register it there as a *pending* publisher.

The version comes from the git tag via `setuptools_scm`, so a real release is just `git tag vX.Y.Z && git push --tags`. To rehearse one without burning a version, run the workflow manually with a `version_override`: it builds and publishes to TestPyPI under that version and creates no GitHub Release.

## Citation

If you use `qoala-bench` in academic work, please cite the accompanying paper, [*A Multi-Level Compiler Pipeline for Qoala Quantum Internet Programs*](https://ieeexplore.ieee.org/document/11662182) (IEEE QSW 2026):

```bibtex
@inproceedings{bernheim2026qoalacompiler,
  author    = {Bernheim, Sacha and van der Vecht, Bart and Ferrari, Davide and
               Rivera, Diego and Wehner, Stephanie},
  title     = {A Multi-Level Compiler Pipeline for Qoala Quantum Internet Programs},
  booktitle = {2026 IEEE International Conference on Quantum Software (QSW)},
  year      = {2026},
  month     = jul,
  address   = {Sydney, Australia},
  publisher = {IEEE},
  pages     = {12--24},
  doi       = {10.1109/QSW72780.2026.00012},
  url       = {https://ieeexplore.ieee.org/document/11662182},
}
```

If you use the published measurements rather than re-running the pipeline, please also cite the dataset:

```bibtex
@dataset{bernheim2026qoalacompilerdata,
  author    = {Bernheim, Sacha and van der Vecht, Bart and Ferrari, Davide and
               Rivera, Diego and Wehner, Stephanie},
  title     = {Data supporting the publication ``A Multi-Level Compiler Pipeline
               for Qoala Quantum Internet Programs''},
  year      = {2026},
  publisher = {4TU.ResearchData},
  doi       = {10.4121/bcac962c-fa21-40c5-9908-44ea5ccaaa5a.v1},
  url       = {https://doi.org/10.4121/bcac962c-fa21-40c5-9908-44ea5ccaaa5a.v1},
}
```

## License

`qoala-bench` is released under the MIT License (Copyright © 2026 QuTech). See the [`LICENSE`](LICENSE) file for the full text.
