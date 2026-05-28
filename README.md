# qoala-bench

`qoala-bench` is the benchmarking framework that drives end-to-end experiments on quantum-network programs compiled with the [Qoala compiler stack](<PAPER_URL>). It takes a single YAML configuration file as input and walks a program through four pipeline stages — *compilation* (with [euqalyptus](<EUQALYPTUS_DOCS_URL>) and [qoala-mlir](<QOALA_MLIR_DOCS_URL>)), *dataset generation* (enumerating program variants and hardware parameters), *simulation* (via NetSquid through [qoala-sim](https://github.com/QuTech-Delft/qoala-sim)), and *analysis* (computing success rates and per-stage timing). The same configuration produces a self-contained results folder that includes the intermediate MLIR artifacts, the raw NetSquid output, and CSV summaries.

This repository is the third leaf of the Qoala compiler stack. [euqalyptus](<EUQALYPTUS_DOCS_URL>) is the Python frontend that emits Qoala HIR from user programs, [qoala-mlir](<QOALA_MLIR_DOCS_URL>) is the MLIR-based middle and back end that lowers HIR to the `.iqoala` executable format, and `qoala-bench` is the harness that exercises both — together with `qoala-sim`, which performs the NetSquid-backed simulation — to produce the empirical results reported in the accompanying paper.

## Installation

`qoala-bench` is a Python package. From a checkout:

```bash
pip install -e .
```

The package depends on `qoala`, `euqalyptus`, `netsquid`, `netqasm`, and the usual scientific-Python stack (`numpy`, `scipy`, `networkx`, `matplotlib`, `tqdm`); the full list is pinned in `setup.cfg`. NetSquid is licensed and requires a free account at <https://netsquid.org/> to install.

The `qoala-opt` and `qoala-translate` binaries from the [qoala-mlir](<QOALA_MLIR_DOCS_URL>) build must be reachable on `PATH`. If they live outside `PATH`, you can also point at them explicitly from the YAML's `tools` section (see the configuration reference below).

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
├── meta.yaml                       # run metadata: timestamps, git hash, config snapshot
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

## Running the bundled benchmarks

Three shell scripts orchestrate the full pipeline used in the paper:

```bash
bash run_benchmark.sh      # generate all datasets (compile + simulate)
bash analyze_benchmark.sh  # compute success rates
bash plot_benchmark.sh     # produce all the plots
```

The bundled benchmarks fall into four families. The **BQC** family covers five hardware configurations crossed with `n = 1..6` (`compile-and-compare-{rd3,dd,rd2,150,200}.{n}.yaml`); the **BQC compile-only** family runs the same set with `n = 1..6` and `10 000` repeats per pass for tight compile-time statistics (`compile-only.{n}.yaml`, no simulation); the **rotation** family covers `n = 1..8` on the trapped-ion configuration at 200 km (`benchmark/rotation/compile-and-compare.{n}.yaml`); and the **rotation compile-only** family is the rotation analogue with `n = 1..8`.

## Writing your own benchmark

Adding a new benchmark is a four-step exercise. First, write the quantum program in Python using the [euqalyptus](<EUQALYPTUS_DOCS_URL>) API. The function must accept the peer node name and any parameters and return a compiled program object (or a tuple where index `result_tuple_index` contains the program). Second, create a hardware-parameter JSON by copying one of the existing files under `benchmark/bqc/` and adapting the fidelities, coherence times, and inter-node distance. Third, write a YAML configuration following the reference above — set `config_path`, the `nodes` qubit counts, the `variables` block, the `python_sources` block, and the analyser's `outcome_key` / `success_value` to match your program's output variable. Fourth, run:

```bash
python -c "from qoala_bench.cli import main; main()" \
    generate my-benchmark.yaml -o my-results
python -c "from qoala_bench.cli import main; main()" \
    analyze results/my-results
```

## Citation

If you use `qoala-bench` in academic work, please cite the accompanying paper. The full BibTeX entry will be available alongside the paper at the URL below; the placeholder below will be replaced once the paper is published:

```bibtex
<BIBTEX_PLACEHOLDER>
```

## License

`qoala-bench` is released under the MIT License (Copyright © 2026 QuTech). See the [`LICENSE`](LICENSE) file for the full text.
