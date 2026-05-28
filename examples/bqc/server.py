import argparse

from euqalyptus import QoalaProgram
from euqalyptus.operations import Remote
from euqalyptus.operations.communication import send_int, recv_int
from euqalyptus.operations.branching import if_cond
from euqalyptus.types.quantum import Entangle, ScopedQubit
from euqalyptus.types.classical import Int


def meas_xy_with_only_Z(q, angle_idx: Int) -> Int:
    """
    Measure in {|+_α>,|-_α>} where α = angle_idx*(pi/4).
    Implemented as Rz(-α) then H then Z-measure.

    Your rot_z(n,d) = n*pi/2^d, so:
      α = angle_idx*pi/4 = (2*angle_idx)*pi/8
      Rz(-α) = rot_z(-2*angle_idx, 3)
    """
    q.rot_Z(8 - angle_idx, 2)
    q.H()
    return q.measure()


def apply_Z_if(q, cond_bit: Int):
    """Apply Z iff cond_bit == 1, using if_cond."""
    with if_cond(cond_bit == 1) as (t, f):
        scoped = ScopedQubit(q)
        with t:
            scoped.Z()
            t.yield_value(scoped)
    return scoped


def apply_X_if(q, cond_bit: Int):
    """Apply X iff cond_bit == 1, using if_cond."""
    with if_cond(cond_bit == 1) as (t, f):
        scoped = ScopedQubit(q)
        with t:
            scoped.X()
            t.yield_value(scoped)
    return scoped


@QoalaProgram
def server_line_graph(client: str, n: int):
    c = Remote(client)

    # Server qubits = server halves of EPR pairs (one per node in the line)
    qs = [Entangle(client) for _ in range(n)]

    # Teleport corrections: for each qubit receive (a,b) and apply Z^a X^b
    for i in range(n):
        a = recv_int(c)
        b = recv_int(c)
        q = apply_Z_if(qs[i], a)
        q = apply_X_if(q, b)
        qs[i] = q  # keep corrected handle

    # Build the line graph: q0--q1--...--q(n-1)
    for i in range(n - 1):
        qs[i].cz(qs[i + 1])

    # Measure first n-1 qubits (client sends delta; we’ll use delta=0 for X)
    for i in range(n - 1):
        delta_i = recv_int(c)
        s_i = meas_xy_with_only_Z(qs[i], delta_i)
        send_int(c, s_i)

    # Final measurement basis flag from client:
    # 0 => measure Z
    # 1 => measure X (angle 0)
    # basis_flag = recv_int(c)

    # Branch to pick final measurement
    if n % 2 == 0:
        out_raw = qs[n - 1].measure()  # Z
    else:
        out_raw = meas_xy_with_only_Z(qs[n - 1], 0)  # X

    send_int(c, out_raw)
