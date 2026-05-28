#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# BQC benchmark
# ---------------------------------------------------------------------------

for n in 1 2 3 4 5 6; do
    name="bqc-n${n}_ti_rdam3-leiden3"
    echo "=== analyzing ${name} ==="
    python -c "from qoala_bench.cli import main; main()" analyze "results/$name"
    echo
done

for n in 1 2 3 4 5 6; do
    name="bqc-n${n}_ti_delft1-dh2"
    echo "=== analyzing ${name} ==="
    python -c "from qoala_bench.cli import main; main()" analyze "results/$name"
    echo
done

for n in 1 2 3 4 5 6; do
    name="bqc-n${n}_ti_rdam2-dh2"
    echo "=== analyzing ${name} ==="
    python -c "from qoala_bench.cli import main; main()" analyze "results/$name"
    echo
done

for n in 1 2 3 4 5 6; do
    name="bqc-n${n}_ti_150"
    echo "=== analyzing ${name} ==="
    python -c "from qoala_bench.cli import main; main()" analyze "results/$name"
    echo
done

for n in 1 2 3 4 5 6; do
    name="bqc-n${n}_ti_200"
    echo "=== analyzing ${name} ==="
    python -c "from qoala_bench.cli import main; main()" analyze "results/$name"
    echo
done

# ---------------------------------------------------------------------------
# BQC compile-only benchmark
# (no analyze step — compile-only datasets have no simulation results)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Rotation benchmark
# ---------------------------------------------------------------------------

for n in 1 2 3 4 5 6 7 8; do
    name="rotation-n${n}_ti_200"
    echo "=== analyzing ${name} ==="
    python -c "from qoala_bench.cli import main; main()" analyze "results/$name"
    echo
done
