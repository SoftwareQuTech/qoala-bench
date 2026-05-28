import argparse

from euqalyptus import QoalaProgram
from euqalyptus.operations import Remote
from euqalyptus.types.quantum import Entangle, LocalQubit
from euqalyptus.types.classical import Int
from euqalyptus.operations.communication import send_int, recv_int
from euqalyptus.operations.control_flow import return_results


def prepare_plus(local_q):
    """Prepare |+> from |0>."""
    local_q.H()
    return local_q


def teleport_local_to_server(local_q, epr_client_half, remote):
    """
    Teleport |psi> from local_q to server’s EPR half.
    Bell meas: CNOT(local->epr), H(local), measure both -> (a,b)
    Server applies Z^a X^b.
    """
    local_q.cnot(epr_client_half)
    local_q.H()
    a = local_q.measure()
    b = epr_client_half.measure()
    send_int(remote, a)
    send_int(remote, b)
    return a, b


def bit_xor(a: Int, b: Int) -> Int:
    """Return a XOR b (bits 0/1) with proper SSA merge."""
    # with if_cond(b == 1) as (t, f):
    #     out = ScopedVar()
    #     with t:
    #         out.assign(Int(1) - a)
    #         t.yield_value(out)
    #     with f:
    #         out.assign(a)
    #         f.yield_value(out)
    # return out
    return a + b - Int(2) * a * b


@QoalaProgram
def client_line_graph(server: str, n: int):
    s = Remote(server)

    # 1) Create n EPR halves and teleport a local |+> into each server half
    qlocs = []
    for i in range(n):
        qloc = LocalQubit()
        prepare_plus(qloc)  # |+>
        qlocs.append(qloc)

    eprs = [Entangle(server) for _ in range(n)]

    for i in range(n):
        teleport_local_to_server(qlocs[i], eprs[i], s)

    # 2) Program the wire: measure first n-1 qubits in X => delta=0
    for _ in range(n - 1):
        send_int(s, Int(0))

    # 3) Receive intermediate outcomes s0..s(n-2)
    ss = [recv_int(s) for _ in range(n - 1)]

    # 4) Choose final measurement basis to make decoded output deterministic 0
    # If n even => H^(n-1)=H => H|+>=|0| => measure Z
    # If n odd  => H^(n-1)=I => I|+>=|+| => measure X
    # basis_flag = Int(0) if (n % 2 == 0) else Int(1)
    # send_int(s, basis_flag)

    out_raw = recv_int(s)

    # 5) Track Pauli frame for a 1D wire with X measurements:
    # (x,z) <- (s_i XOR z, x)
    x_key = Int(0)
    z_key = Int(0)
    for s_i in ss:
        new_x = bit_xor(s_i, z_key)
        new_z = x_key
        x_key = new_x
        z_key = new_z

    # 6) Decrypt final measurement:
    # Z measurement flips under X, X measurement flips under Z
    if n % 2 == 0:
        out = bit_xor(out_raw, x_key)  # Z-meas => decrypt with x_key
    else:
        out = bit_xor(out_raw, z_key)  # X-meas => decrypt with z_key

    # Test: value of out
    # return_results(out, out_raw, basis_flag, x_key, z_key)
    return_results(out)
