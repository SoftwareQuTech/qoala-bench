from euqalyptus import QoalaProgram
from euqalyptus.operations import Remote
from euqalyptus.operations.branching import if_cond
from euqalyptus.operations.communication import recv_int, send_int
from euqalyptus.types.classical import Int
from euqalyptus.types.quantum import Entangle, ScopedQubit


def meas_xy_with_only_Z(q, angle_idx: Int) -> Int:
    """
    Measure in {|+_α>,|-_α>} where α = angle_idx*(pi/4).
    Implemented as Rz(-α) then H then Z-measure.

    rot_z(n,d) = n*pi/2^d, so:
      α = angle_idx*pi/4 = (2*angle_idx)*pi/8
      Rz(-α) = rot_z(-2*angle_idx, 3) = rot_z(8 - angle_idx, 2)
    """
    q.rot_Z(8 - angle_idx, 2)
    q.H()
    return q.measure()


def apply_Z_if(q, cond_bit: Int):
    """Apply Z iff cond_bit == 1."""
    with if_cond(cond_bit == 1) as (t, f):
        scoped = ScopedQubit(q)
        with t:
            scoped.Z()
            t.yield_value(scoped)
    return scoped


def apply_X_if(q, cond_bit: Int):
    """Apply X iff cond_bit == 1."""
    with if_cond(cond_bit == 1) as (t, f):
        scoped = ScopedQubit(q)
        with t:
            scoped.X()
            t.yield_value(scoped)
    return scoped


@QoalaProgram
def server_bqc_streaming(client: str, n: int):
    c = Remote(client)

    # 1) All EPRs upfront (worst-case: all n qubit slots occupied from the start)
    qs = [Entangle(client) for _ in range(n)]

    # 2) Receive corrections for first qubit and apply them.
    #    For n >= 2: also receive corrections for second qubit and CZ.
    a = recv_int(c)
    b = recv_int(c)
    qs[0] = apply_Z_if(qs[0], a)
    qs[0] = apply_X_if(qs[0], b)

    if n >= 2:
        a = recv_int(c)
        b = recv_int(c)
        qs[1] = apply_Z_if(qs[1], a)
        qs[1] = apply_X_if(qs[1], b)
        qs[0].cz(qs[1])

    # 3) Streaming measurements: for each non-output qubit i (except the last),
    #    receive delta_i, measure qubit i, send result, then receive corrections
    #    for qubit i+2 and connect it to the graph.
    #
    # This ordering matches the client's streaming send order and allows
    # the optimized variant to reuse qubit slots (EPR for i+2 can be
    # generated only after qubit i is measured and its slot freed).
    for i in range(n - 2):
        delta = recv_int(c)
        s = meas_xy_with_only_Z(qs[i], delta)
        send_int(c, s)

        a = recv_int(c)
        b = recv_int(c)
        qs[i + 2] = apply_Z_if(qs[i + 2], a)
        qs[i + 2] = apply_X_if(qs[i + 2], b)
        qs[i + 1].cz(qs[i + 2])

    # 4) Last non-output qubit measurement (only when n >= 2)
    if n >= 2:
        delta = recv_int(c)
        s = meas_xy_with_only_Z(qs[n - 2], delta)
        send_int(c, s)

    # 5) Output qubit: Z-measure for even n, X-measure (angle=0) for odd n
    if n % 2 == 0:
        out = qs[n - 1].measure()
    else:
        out = meas_xy_with_only_Z(qs[n - 1], 0)

    send_int(c, out)
