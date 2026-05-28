#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# BQC benchmark
# ---------------------------------------------------------------------------

echo "=== BQC benchmark (rdam3-leiden3, n=1..6) ==="
for n in 1 2 3 4 5 6; do
    config="benchmark/bqc/compile-and-compare.${n}.yaml"
    name="bqc-n${n}_ti_rdam3-leiden3"

    echo "=== n=${n} ==="
    start=$(date +%s%N)

    python -c "from qoala_bench.cli import main; main()" generate "$config" -o "$name"

    end=$(date +%s%N)
    elapsed=$(( (end - start) / 1000000000 ))
    echo "--- n=${n} done in ${elapsed}s ---"
    echo
done

echo "=== BQC benchmark (delft1-denhaag2, n=1..6) ==="
for n in 1 2 3 4 5 6; do
    config="benchmark/bqc/compile-and-compare-dd.${n}.yaml"
    name="bqc-n${n}_ti_delft1-dh2"

    echo "=== n=${n} ==="
    start=$(date +%s%N)

    python -c "from qoala_bench.cli import main; main()" generate "$config" -o "$name"

    end=$(date +%s%N)
    elapsed=$(( (end - start) / 1000000000 ))
    echo "--- n=${n} done in ${elapsed}s ---"
    echo
done

echo "=== BQC benchmark (rotterdam2-denhaag2, n=1..6) ==="
for n in 1 2 3 4 5 6; do
    config="benchmark/bqc/compile-and-compare-rd2.${n}.yaml"
    name="bqc-n${n}_ti_rdam2-dh2"

    echo "=== n=${n} ==="
    start=$(date +%s%N)

    python -c "from qoala_bench.cli import main; main()" generate "$config" -o "$name"

    end=$(date +%s%N)
    elapsed=$(( (end - start) / 1000000000 ))
    echo "--- n=${n} done in ${elapsed}s ---"
    echo
done

echo "=== BQC benchmark (trapped-ions 150km, n=1..6) ==="
for n in 1 2 3 4 5 6; do
    config="benchmark/bqc/compile-and-compare-150.${n}.yaml"
    name="bqc-n${n}_ti_150"

    echo "=== n=${n} ==="
    start=$(date +%s%N)

    python -c "from qoala_bench.cli import main; main()" generate "$config" -o "$name"

    end=$(date +%s%N)
    elapsed=$(( (end - start) / 1000000000 ))
    echo "--- n=${n} done in ${elapsed}s ---"
    echo
done

echo "=== BQC benchmark (trapped-ions 200km, n=1..6) ==="
for n in 1 2 3 4 5 6; do
    config="benchmark/bqc/compile-and-compare-200.${n}.yaml"
    name="bqc-n${n}_ti_200"

    echo "=== n=${n} ==="
    start=$(date +%s%N)

    python -c "from qoala_bench.cli import main; main()" generate "$config" -o "$name"

    end=$(date +%s%N)
    elapsed=$(( (end - start) / 1000000000 ))
    echo "--- n=${n} done in ${elapsed}s ---"
    echo
done

# ---------------------------------------------------------------------------
# BQC compile-only benchmark
# ---------------------------------------------------------------------------

echo "=== BQC compilation-only benchmark (10000 repeats, n=1..6) ==="
for n in 1 2 3 4 5 6; do
    config="benchmark/bqc/compile-only.${n}.yaml"
    name="bqc-compile-only-n${n}"

    echo "=== n=${n} ==="
    start=$(date +%s%N)

    python -c "from qoala_bench.cli import main; main()" generate "$config" -o "$name" --compilation-only

    end=$(date +%s%N)
    elapsed=$(( (end - start) / 1000000000 ))
    echo "--- n=${n} done in ${elapsed}s ---"
    echo
done

# ---------------------------------------------------------------------------
# Rotation benchmark
# ---------------------------------------------------------------------------

echo "=== rotation benchmark (ti_200, n=1..8) ==="
for n in 1 2 3 4 5 6 7 8; do
    config="benchmark/rotation/compile-and-compare.${n}.yaml"
    name="rotation-n${n}_ti_200"

    echo "=== n=${n} ==="
    start=$(date +%s%N)

    python -c "from qoala_bench.cli import main; main()" generate "$config" -o "$name"

    end=$(date +%s%N)
    elapsed=$(( (end - start) / 1000000000 ))
    echo "--- n=${n} done in ${elapsed}s ---"
    echo
done

echo "=== rotation compile-only benchmark (10000 repeats, n=1..8) ==="
for n in 1 2 3 4 5 6 7 8; do
    config="benchmark/rotation/compile-only.${n}.yaml"
    name="rotation-compile-only-n${n}"

    echo "=== n=${n} ==="
    start=$(date +%s%N)

    python -c "from qoala_bench.cli import main; main()" generate "$config" -o "$name" --compilation-only

    end=$(date +%s%N)
    elapsed=$(( (end - start) / 1000000000 ))
    echo "--- n=${n} done in ${elapsed}s ---"
    echo
done
