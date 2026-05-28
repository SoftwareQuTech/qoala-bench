#!/usr/bin/env bash
set -euo pipefail

RUN="python -c 'from qoala_bench.cli import main; main()' add-steps"

run_add_steps() {
    local config="$1"
    local dataset="$2"
    local extra="${3:-}"
    echo "=== add-steps: $dataset ==="
    eval "$RUN $config results/$dataset $extra"
    echo
}

# --- BQC compile-only ---
# for n in 1 2 3 4 5 6; do
#     run_add_steps "benchmark/bqc/compile-only.${n}.yaml" "bqc-compile-only-n${n}"
# done

# --- BQC rdam3-leiden3 ---
# for n in 1 2 3 4 5 6; do
#     run_add_steps "benchmark/bqc/compile-and-compare.${n}.yaml" "bqc-n${n}_ti_rdam3-leiden3" "--repeats 1"
# done

# --- BQC delft1-dh2 ---
# for n in 1 2 3 4 5 6; do
#     run_add_steps "benchmark/bqc/compile-and-compare-dd.${n}.yaml" "bqc-n${n}_ti_delft1-dh2" "--repeats 1"
# done

# --- BQC rdam2-dh2 ---
# for n in 1 2 3 4 5 6; do
#     run_add_steps "benchmark/bqc/compile-and-compare-rd2.${n}.yaml" "bqc-n${n}_ti_rdam2-dh2" "--repeats 1"
# done

# --- BQC ti-200 ---
# for n in 1 2 3 4 5 6; do
#     run_add_steps "benchmark/bqc/compile-and-compare-200.${n}.yaml" "bqc-n${n}_ti_200" "--repeats 1"
# done

# --- BQC ti-150 ---
# for n in 1 2 3 4 5 6; do
#     run_add_steps "benchmark/bqc/compile-and-compare-150.${n}.yaml" "bqc-n${n}_ti_150" "--repeats 1"
# done

# --- Rotation compile-only ---
# for n in 1 2 3 4 5 6 7 8; do
#     run_add_steps "benchmark/rotation/compile-only.${n}.yaml" "rotation-compile-only-n${n}"
# done

# --- Rotation ti-200 ---
# for n in 1 2 3 4 5 6 7 8; do
#     run_add_steps "benchmark/rotation/compile-and-compare.${n}.yaml" "rotation-n${n}_ti_200" "--repeats 1"
# done

# --- BQC streaming rdam3-leiden3 ---
for n in 1 2 3 4 5 6; do
    run_add_steps "benchmark/bqc/compile-and-compare.${n}.yaml" "bqc-n${n}_ti_rdam3-leiden3" "--repeats 1"
done

# --- BQC streaming delft1-dh2 ---
for n in 1 2 3 4 5 6; do
    run_add_steps "benchmark/bqc/compile-and-compare-dd.${n}.yaml" "bqc-n${n}_ti_delft1-dh2" "--repeats 1"
done

# --- BQC streaming rdam2-dh2 ---
for n in 1 2 3 4 5 6; do
    run_add_steps "benchmark/bqc/compile-and-compare-rd2.${n}.yaml" "bqc-n${n}_ti_rdam2-dh2" "--repeats 1"
done

# --- BQC streaming ti-150 ---
for n in 1 2 3 4 5 6; do
    run_add_steps "benchmark/bqc/compile-and-compare-150.${n}.yaml" "bqc-n${n}_ti_150" "--repeats 1"
done

# --- BQC streaming ti-200 ---
for n in 1 2 3 4 5 6; do
    run_add_steps "benchmark/bqc/compile-and-compare-200.${n}.yaml" "bqc-n${n}_ti_200" "--repeats 1"
done
