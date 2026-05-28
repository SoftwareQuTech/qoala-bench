from euqalyptus import QoalaProgram
from euqalyptus.operations import Remote
from euqalyptus.operations.communication import recv_int, send_int
from euqalyptus.operations.control_flow import return_results
from euqalyptus.types.quantum import LocalQubit


@QoalaProgram
def server_full_turn(client: str, n: int):
    c = Remote(client)

    # Qubit initialised as |0⟩.
    # rot_Y rotations move through the equatorial plane → T2-sensitive
    # while waiting for each classical message from the client.
    q = LocalQubit()

    # d=3 hardcoded: angles are multiples of π/8.
    # Receive only the numerator n_int per rotation.
    for _ in range(n):
        n_int = recv_int(c)
        q.rot_Y(n_int, 3)

    meas = q.measure()
    send_int(c, meas)
    return_results(meas)
