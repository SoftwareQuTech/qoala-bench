from euqalyptus import QoalaProgram
from euqalyptus.operations import Remote
from euqalyptus.operations.communication import recv_int, send_int
from euqalyptus.operations.control_flow import return_results
from euqalyptus.types.classical import Int


@QoalaProgram
def client_full_turn(server: str, n: int, n_int: int):
    s = Remote(server)

    # d=3 is hardcoded in the server; the client only sends n_int per rotation.
    # Total angle = n * n_int * π / 2^3 = n * n_int * π / 8.
    for _ in range(n):
        send_int(s, Int(n_int))

    meas = recv_int(s)
    return_results(meas)
