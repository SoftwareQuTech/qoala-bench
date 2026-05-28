#!/usr/bin/env bash
set -euo pipefail

CLI="python -c 'from qoala_bench.cli import main; main()'"

for n in 1 2 3 4 5 6 7; do
    config="examples/bqc/compile-and-compare.${n}.yaml"
    name="check-bqc-n${n}"

    echo "=== n=${n} ==="
    start=$(date +%s%N)

    eval "$CLI generate \"$config\" -o \"$name\""
    eval "$CLI analyze \"results/$name\""

    end=$(date +%s%N)
    elapsed=$(( (end - start) / 1000000000 ))
    echo "--- n=${n} done in ${elapsed}s ---"
    echo
done
