#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# BQC benchmark
# ---------------------------------------------------------------------------

echo "=== plotting bqc rdam3-leiden3 ==="
python benchmark/bqc/plot_benchmark.py \
    1=results/bqc-n1_ti_rdam3-leiden3 \
    2=results/bqc-n2_ti_rdam3-leiden3 \
    3=results/bqc-n3_ti_rdam3-leiden3 \
    4=results/bqc-n4_ti_rdam3-leiden3 \
    5=results/bqc-n5_ti_rdam3-leiden3 \
    6=results/bqc-n6_ti_rdam3-leiden3 \
    -o results/bqc-plots_rdam3-leiden3 \
    --name bqc_rdam3_leiden3
echo

echo "=== plotting bqc delft1-dh2 ==="
python benchmark/bqc/plot_benchmark.py \
    1=results/bqc-n1_ti_delft1-dh2 \
    2=results/bqc-n2_ti_delft1-dh2 \
    3=results/bqc-n3_ti_delft1-dh2 \
    4=results/bqc-n4_ti_delft1-dh2 \
    5=results/bqc-n5_ti_delft1-dh2 \
    6=results/bqc-n6_ti_delft1-dh2 \
    -o results/bqc-plots_delft1-dh2 \
    --name bqc_delft1_dh2
echo

echo "=== plotting bqc rdam2-dh2 ==="
python benchmark/bqc/plot_benchmark.py \
    1=results/bqc-n1_ti_rdam2-dh2 \
    2=results/bqc-n2_ti_rdam2-dh2 \
    3=results/bqc-n3_ti_rdam2-dh2 \
    4=results/bqc-n4_ti_rdam2-dh2 \
    5=results/bqc-n5_ti_rdam2-dh2 \
    6=results/bqc-n6_ti_rdam2-dh2 \
    -o results/bqc-plots_rdam2-dh2 \
    --name bqc_rdam2_dh2
echo

echo "=== plotting bqc ti-150 ==="
python benchmark/bqc/plot_benchmark.py \
    1=results/bqc-n1_ti_150 \
    2=results/bqc-n2_ti_150 \
    3=results/bqc-n3_ti_150 \
    4=results/bqc-n4_ti_150 \
    5=results/bqc-n5_ti_150 \
    6=results/bqc-n6_ti_150 \
    -o results/bqc-plots_ti_150 \
    --name bqc_150km
echo

echo "=== plotting bqc ti-200 ==="
python benchmark/bqc/plot_benchmark.py \
    1=results/bqc-n1_ti_200 \
    2=results/bqc-n2_ti_200 \
    3=results/bqc-n3_ti_200 \
    4=results/bqc-n4_ti_200 \
    5=results/bqc-n5_ti_200 \
    6=results/bqc-n6_ti_200 \
    -o results/bqc-plots_ti_200 \
    --name bqc_200km
echo

# ---------------------------------------------------------------------------
# BQC compile-only benchmark
# ---------------------------------------------------------------------------

echo "=== plotting bqc compilation-only ==="
python benchmark/bqc/plot_benchmark.py \
    1=results/bqc-compile-only-n1 \
    2=results/bqc-compile-only-n2 \
    3=results/bqc-compile-only-n3 \
    4=results/bqc-compile-only-n4 \
    5=results/bqc-compile-only-n5 \
    6=results/bqc-compile-only-n6 \
    -o results/bqc-plots_compile-only --compilation-only
echo

# ---------------------------------------------------------------------------
# Rotation benchmark
# ---------------------------------------------------------------------------

echo "=== plotting rotation ti-200 ==="
python benchmark/rotation/plot_benchmark.py \
    1=results/rotation-n1_ti_200 \
    2=results/rotation-n2_ti_200 \
    3=results/rotation-n3_ti_200 \
    4=results/rotation-n4_ti_200 \
    5=results/rotation-n5_ti_200 \
    6=results/rotation-n6_ti_200 \
    7=results/rotation-n7_ti_200 \
    8=results/rotation-n8_ti_200 \
    -o results/rotation-plots_ti_200
echo

echo "=== plotting rotation compile-only ==="
python benchmark/rotation/plot_benchmark.py \
    1=results/rotation-compile-only-n1 \
    2=results/rotation-compile-only-n2 \
    3=results/rotation-compile-only-n3 \
    4=results/rotation-compile-only-n4 \
    5=results/rotation-compile-only-n5 \
    6=results/rotation-compile-only-n6 \
    7=results/rotation-compile-only-n7 \
    8=results/rotation-compile-only-n8 \
    -o results/rotation-plots_compile-only --compilation-only
echo
