from euqalyptus import QoalaProgram
from euqalyptus.operations import Remote
from euqalyptus.operations.communication import recv_int, send_int
from euqalyptus.operations.control_flow import return_results
from euqalyptus.types.classical import Int
from euqalyptus.types.quantum import Entangle, LocalQubit


def bit_xor(a: Int, b: Int) -> Int:
    return a + b - Int(2) * a * b


@QoalaProgram
def client_bqc_streaming(server: str, n: int):
    s = Remote(server)

    # 1) Initialize all |+> states (worst-case: all upfront)
    qlocs = []
    for _ in range(n):
        qloc = LocalQubit()
        qloc.H()
        qlocs.append(qloc)

    # 2) All EPRs (worst-case: all upfront)
    eprs = [Entangle(server) for _ in range(n)]

    # 3) All Bell measurements (quantum ops, worst-case: all upfront)
    corrections = []
    for i in range(n):
        qlocs[i].cnot(eprs[i])
        qlocs[i].H()
        a = qlocs[i].measure()
        b = eprs[i].measure()
        corrections.append((a, b))

    # 4) Classical communication in streaming order.
    #
    # Streaming send order for general n (n >= 1):
    #
    #   n=1: send corr[0],                          recv out
    #   n=2: send corr[0], corr[1], delta_0=0,
    #         recv s0,                               recv out
    #   n=3: send corr[0], corr[1], delta_0=0,
    #         recv s0, send corr[2], delta_1=0,
    #         recv s1,                               recv out
    #
    # General: send corr[0]; if n>=2: send corr[1];
    #   for i in 0..n-3: send delta_i, recv s_i, send corr[i+2]
    #   if n>=2: send delta_{n-2}, recv s_{n-2}
    #   recv out_raw

    send_int(s, corrections[0][0])
    send_int(s, corrections[0][1])

    ss = []
    if n >= 2:
        send_int(s, corrections[1][0])
        send_int(s, corrections[1][1])

        for i in range(n - 2):
            send_int(s, Int(0))  # delta_i = 0
            ss.append(recv_int(s))  # s_i
            send_int(s, corrections[i + 2][0])
            send_int(s, corrections[i + 2][1])

        send_int(s, Int(0))  # delta_{n-2} = 0
        ss.append(recv_int(s))  # s_{n-2}

    out_raw = recv_int(s)

    # 5) Pauli frame tracking for a 1D wire
    x_key = Int(0)
    z_key = Int(0)
    for s_i in ss:
        new_x = bit_xor(s_i, z_key)
        new_z = x_key
        x_key = new_x
        z_key = new_z

    # n odd  => output qubit measured in X => decrypt with z_key
    # n even => output qubit measured in Z => decrypt with x_key
    if n % 2 == 0:
        out = bit_xor(out_raw, x_key)
    else:
        out = bit_xor(out_raw, z_key)

    return_results(out)
