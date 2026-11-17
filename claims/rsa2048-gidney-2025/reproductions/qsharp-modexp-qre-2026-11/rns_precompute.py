"""Residue number system, lookup tables, data-dependent lookup costs, and deviation sampling for the
approximate modular exponentiation of Gidney (2025), arXiv:2505.15917, Appendix A.1.

An independent implementation (numpy + stdlib only) of the classical precomputation the circuit in
modexp.qs needs, in the conventions of its MakeConfig:

- a residue number system P (Eq. 17 and Assumption 1): distinct primes of a fixed bit length whose
  product L is at least N^num_windows1 and has modular deviation Delta_N(L) below 2^-min_wraparound_gap,
  avoiding primes that divide any of the windowed multipliers (whose discrete logs table1 needs);
- table1 ((|P| + 1) rows of differenced discrete logs), table3a/3b/3c and table4;
- the exact Toffoli count of every table lookup the circuit performs, which depends on the table
  contents only through which power-product pairs have a non-zero output mask (Appendix A.4);
- the paper's failed-shot bound (Eqs. 43-45) and a Monte Carlo measurement of the actual modular
  deviation of the circuit's output at full size.

Everything that runs in worker processes is a module-level function, so it works with the macOS
"spawn" start method.
"""
from __future__ import annotations

import dataclasses
import hashlib
import math
import multiprocessing as mp
import os
import random
import time
from typing import Any, Iterator, Sequence

import numpy as np

RSA2048 = int(
    "25195908475657893494027183240048398571429282126204032027777137836043662020707595556264018525880784"
    "406918290641249515082189298559149176184502808489120072844992687392807287776735971418347270261896375"
    "014971824691165077613379859095700097330459748808428401797429100642458691817195118746121515172654632"
    "282216869987549182422433637259085141865462043576798423387184774447920739934236584823824281198163815"
    "010674810451660377306056201619676256133844143603833904414952634432190114657544454178424020924616515"
    "723350778707749817125772467962926386356373289912154831438167899885040445364023527381951378636564391"
    "212010397122822120720357"
)


# ------------------------------------------------------------------------------------------------
# Parameters.


@dataclasses.dataclass(frozen=True)
class Params:
    modulus: int
    generator: int
    num_input_qubits: int
    window1: int
    window3a: int
    window3b: int
    window4: int
    len_accumulator: int
    min_wraparound_gap: int
    mask_bits: int
    prime_bit_length: int

    @property
    def num_windows1(self) -> int:
        return -(-self.num_input_qubits // self.window1)

    @property
    def num_windows3a(self) -> int:
        return -(-self.prime_bit_length // self.window3a)

    @property
    def num_windows3b(self) -> int:
        return -(-self.prime_bit_length // self.window3b)

    @property
    def num_windows4(self) -> int:
        return -(-self.prime_bit_length // self.window4)

    @property
    def len_dlog(self) -> int:
        return self.prime_bit_length + self.num_input_qubits.bit_length()

    @property
    def dropped_bits(self) -> int:
        return max(0, self.modulus.bit_length() - self.len_accumulator)

    @property
    def trunc(self) -> int:
        return self.modulus >> self.dropped_bits


# The n = 2048 row of Table 5 (s = 8, m = n/2 + n/s), with the generator of the author's
# testdata/rsa2048.ini and min_wraparound_gap = len_accumulator = f.
TABLE5_RSA2048 = Params(
    modulus=RSA2048, generator=3, num_input_qubits=1280, window1=6, window3a=3, window3b=3,
    window4=5, len_accumulator=33, min_wraparound_gap=33, mask_bits=26, prime_bit_length=21,
)


def params_from_vector(d: dict, min_wraparound_gap: int) -> Params:
    """Params of a test vector exported by export_test_vectors.py."""
    return Params(
        modulus=d["modulus"], generator=d["generator"], num_input_qubits=d["num_input_qubits"],
        window1=d["w1"], window3a=d["w3a"], window3b=d["w3b"], window4=d["w4"],
        len_accumulator=d["len_acc"], min_wraparound_gap=min_wraparound_gap,
        mask_bits=d["mask_bits"], prime_bit_length=d["ell"],
    )


# ------------------------------------------------------------------------------------------------
# Number theory helpers.


def multipliers(params: Params) -> list[int]:
    """M[j, k] = g^(k << (window1 * j)) mod N, flattened j-major (the table1 inputs)."""
    N, w1 = params.modulus, params.window1
    out = []
    base = params.generator % N
    for _ in range(params.num_windows1):
        v = 1
        for _ in range(1 << w1):
            out.append(v)
            v = v * base % N
        base = pow(base, 1 << w1, N)
    return out


def primes_of_bit_length(bits: int) -> np.ndarray:
    limit = 1 << bits
    sieve = np.ones(limit, dtype=bool)
    sieve[:2] = False
    for p in range(2, math.isqrt(limit) + 1):
        if sieve[p]:
            sieve[p * p::p] = False
    return np.nonzero(sieve[1 << (bits - 1):])[0].astype(np.int64) + (1 << (bits - 1))


def _prime_factors(n: int) -> list[int]:
    out, d = [], 2
    while d * d <= n:
        if n % d == 0:
            out.append(d)
            while n % d == 0:
                n //= d
        d += 1
    if n > 1:
        out.append(n)
    return out


def primitive_root(p: int) -> int:
    """Smallest multiplicative generator modulo p that is at least 3."""
    qs = _prime_factors(p - 1)
    for g in range(3, p):
        if all(pow(g, (p - 1) // q, p) != 1 for q in qs):
            return g
    raise ValueError(f"no generator for {p}")


def dlog_table(p: int, g: int) -> np.ndarray:
    """log[x] = discrete log of x base g modulo p, for x in 1..p-1."""
    n = p - 1
    pw = np.empty(n, dtype=np.int64)
    pw[0] = 1
    length = 1
    while length < n:
        m = min(length, n - length)
        pw[length:length + m] = pw[:m] * pow(g, length, p) % p
        length += m
    log = np.zeros(p, dtype=np.int64)
    log[pw] = np.arange(n, dtype=np.int64)
    return log


def limbs16(values: Sequence[int], nbits: int) -> np.ndarray:
    nl = (nbits + 15) // 16
    raw = b"".join(int(v).to_bytes(2 * nl, "little") for v in values)
    return np.frombuffer(raw, dtype="<u2").reshape(len(values), nl).astype(np.float64)


def residues(limbs: np.ndarray, primes: Sequence[int]) -> np.ndarray:
    """values mod p for every (value, prime): one float64 matrix product, exact because every
    partial sum is an integer below 2^53 (16-bit limbs times 21-bit weights, at most 2^7 terms)."""
    primes = np.asarray(primes, dtype=np.int64)
    nl = limbs.shape[1]
    assert nl * 65535 * int(primes.max()) < 2**53, "limb products would not be exact in float64"
    W = np.empty((nl, len(primes)), dtype=np.int64)
    W[0] = 1 % primes
    for t in range(1, nl):
        W[t] = W[t - 1] * 65536 % primes
    R = limbs @ W.astype(np.float64)
    R = np.fmod(R, primes.astype(np.float64))
    return R.astype(np.int64)


def modular_deviation(L: int, N: int) -> int:
    r = L % N
    return min(r, N - r)


# ------------------------------------------------------------------------------------------------
# Residue number system search (Eq. 17, Assumption 1).


@dataclasses.dataclass(frozen=True)
class ResidueSystem:
    periods: tuple[int, ...]  # sorted ascending
    excluded_primes: tuple[int, ...]  # primes of the bit length dividing some multiplier
    seed: int
    candidates_tried: int
    added_pair: tuple[int, int]
    pruned: tuple[int, ...]
    seconds: float


def find_excluded_primes(params: Params, primes: np.ndarray, *, chunk: int = 4096) -> list[int]:
    """Primes dividing some multiplier M[j, k] (whose discrete log would not exist)."""
    limbs = limbs16(multipliers(params), params.modulus.bit_length())
    bad = []
    for a in range(0, len(primes), chunk):
        R = residues(limbs, primes[a:a + chunk])
        bad.extend(int(p) for p in primes[a:a + chunk][(R == 0).any(axis=0)])
    return bad


_SEARCH: dict[str, Any] = {}


def _search_init(state: dict[str, Any]) -> None:
    _SEARCH.clear()
    _SEARCH.update(state)


def _try_pair(p1: int, p2: int) -> tuple | None:
    s = _SEARCH
    N, PC, thresh = s["N"], s["PC"], s["thresh"]
    c = s["base"] * p1 % N * p2 % N
    for sign, side in ((+1, c), (-1, N - c)):
        if side < thresh:
            return (sign, (), side)
        g = math.gcd(side, PC % side)
        factors = []
        if g > 1:
            factors = [p for p in s["C"] if g % p == 0]
        factors += [p for p in (p1, p2) if side % p == 0]
        if not factors:
            continue
        factors.sort()
        d, used = 1, []
        for f in factors:
            d *= f
            used.append(f)
            if side // d < thresh:
                break
        if side // d >= thresh:
            continue
        if PC * p1 * p2 // d < s["target"]:
            continue
        return (sign, tuple(used), side // d)
    return None


def _search_batch(pairs: list[tuple[int, int]]) -> tuple[int, tuple | None]:
    for k, (p1, p2) in enumerate(pairs):
        r = _try_pair(p1, p2)
        if r is not None:
            return k, (p1, p2) + r
    return len(pairs), None


def _pairs(pool: list[int]) -> Iterator[tuple[int, int]]:
    for b in range(1, len(pool)):
        for a in range(b):
            yield pool[a], pool[b]


def find_residue_system(params: Params, *, seed: int = 0, slack_primes: int = 1, batch: int = 64,
                        workers: int | None = None) -> ResidueSystem:
    """Random search in the spirit of Assumption 1 (as in the author's code: the largest primes
    plus a pair, then dividing out primes of the set that divide L mod N or N - L mod N, which
    shrinks the deviation). Deterministic for a given seed: candidates are tried in a fixed order and
    the first success in that order is returned."""
    t0 = time.monotonic()
    N = params.modulus
    primes = primes_of_bit_length(params.prime_bit_length)
    excluded = set(find_excluded_primes(params, primes))
    acceptable = [int(p) for p in primes if int(p) not in excluded]
    target = N ** params.num_windows1
    C, PC = [], 1
    while PC < target:
        p = acceptable.pop()
        C.append(p)
        PC *= p
    for _ in range(slack_primes):
        p = acceptable.pop()
        C.append(p)
        PC *= p
    pool = list(acceptable)
    random.Random(seed).shuffle(pool)
    state = dict(N=N, PC=PC, base=PC % N, thresh=N >> params.min_wraparound_gap, target=target, C=C)
    workers = workers or os.cpu_count() or 1
    tried = 0
    found = None
    gen = _pairs(pool)

    def batches():
        while True:
            chunk = [pr for _, pr in zip(range(batch), gen)]
            if not chunk:
                return
            yield chunk

    if workers == 1:
        _search_init(state)
        results = map(_search_batch, batches())
        pool_ctx = None
    else:
        pool_ctx = mp.get_context("spawn").Pool(workers, initializer=_search_init, initargs=(state,))
        results = pool_ctx.imap(_search_batch, batches(), chunksize=1)
    try:
        for k, r in results:
            tried += k
            if r is not None:
                tried += 1
                found = r
                break
    finally:
        if pool_ctx is not None:
            pool_ctx.terminate()
            pool_ctx.join()
    if found is None:
        raise RuntimeError("search space exhausted")
    p1, p2, sign, pruned, _ = found
    chosen = set(C) | {p1, p2}
    chosen -= set(pruned)
    rs = ResidueSystem(
        periods=tuple(sorted(chosen)), excluded_primes=tuple(sorted(excluded)), seed=seed,
        candidates_tried=tried, added_pair=(p1, p2), pruned=tuple(pruned),
        seconds=time.monotonic() - t0,
    )
    verify_residue_system(params, rs.periods)
    return rs


def verify_residue_system(params: Params, periods: Sequence[int]) -> dict[str, Any]:
    """Checks every condition the algorithm needs; raises AssertionError on any failure."""
    periods = [int(p) for p in periods]
    N = params.modulus
    assert len(set(periods)) == len(periods), "periods are not distinct"
    assert all(p.bit_length() == params.prime_bit_length for p in periods), "wrong bit length"
    assert all(_prime_factors(p) == [p] for p in periods[:: max(1, len(periods) // 500)]), "not prime"
    assert all(pow(2, p - 1, p) == 1 for p in periods), "failed a Fermat test"
    L = math.prod(periods)
    target = N ** params.num_windows1
    assert L >= target, "product of the periods is smaller than N^num_windows1"
    dev = modular_deviation(L, N)
    assert dev < N >> params.min_wraparound_gap, "modular deviation of L is too large"
    limbs = limbs16(multipliers(params), N.bit_length())
    zero = 0
    for a in range(0, len(periods), 4096):
        zero += int((residues(limbs, periods[a:a + 4096]) == 0).sum())
    assert zero == 0, "a period divides a multiplier"
    return dict(
        num_primes=len(periods), L_bits=L.bit_length(), capacity_bits_needed=target.bit_length(),
        L_mod_N_deviation=dev / N, L_mod_N_deviation_log2=math.log2(dev / N) if dev else float("-inf"),
        threshold_log2=-params.min_wraparound_gap,
    )


# ------------------------------------------------------------------------------------------------
# Tables, in modexp.qs MakeConfig conventions.


class _Ctx:
    def __init__(self, params: Params, periods: Sequence[int], digits: np.ndarray | None = None):
        self.params = params
        self.periods = np.asarray(periods, dtype=np.int64)
        self.limbs = limbs16(multipliers(params), params.modulus.bit_length())
        self.L = math.prod(int(p) for p in periods)
        self.LmodN = self.L % params.modulus
        self.digits = digits


def _table3(params: Params, p: int, g: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    W3a, W3b, w3a, w3b = params.num_windows3a, params.num_windows3b, params.window3a, params.window3b
    t3a = np.zeros((W3a, W3b, 1 << (w3a + w3b)), dtype=np.int64)
    t3b = np.zeros_like(t3a)
    kb_vals = np.arange(1 << w3b, dtype=np.int64)
    for ka in range(W3a):
        for kb in range(W3b):
            for k4a in range(1 << w3a):
                v = pow(g, k4a << (ka * w3a), p)
                v2 = -pow(v, -1, p)
                v = (v << (kb * w3b)) % p
                v2 = (v2 << (kb * w3b)) % p
                addr = (k4a << w3b) | kb_vals
                t3a[ka, kb, addr] = (-v * kb_vals) % p
                t3b[ka, kb, addr] = (-v2 * kb_vals) % p
    t3c = np.array([pow(g, k, p) for k in range(1 << (2 * w3a))], dtype=np.int64)
    return t3a, t3b, t3c


def _table4(params: Params, p: int, L: int, LmodN: int) -> np.ndarray:
    """table4[j, k] = -(((u << (w4 j)) * k mod L mod N) >> dropped) mod trunc, u the CRT basis value."""
    N, w4, dropped, trunc = params.modulus, params.window4, params.dropped_bits, params.trunc
    u = L // p
    u *= pow(u, -1, p)
    rows = []
    for v1 in range(0, p.bit_length(), w4):
        Y = (u << v1) % L
        y = Y % N
        Z, z = 0, 0
        row = []
        for _ in range(1 << w4):
            row.append((-(z >> dropped)) % trunc)
            Z += Y
            z += y
            if Z >= L:
                Z -= L
                z -= LmodN
            z %= N
        rows.append(row)
    return np.array(rows, dtype=np.int64)


def _chunk_tables(ctx: _Ctx, a: int, b: int) -> dict[str, Any]:
    """Real tables for primes a..b-1 (and the final table1 row when b == |P|)."""
    P, params = ctx.periods, ctx.params
    first = a - 1 if a > 0 else a
    primes = [int(p) for p in P[first:b]]
    R = residues(ctx.limbs, primes)
    if (R == 0).any():
        raise ValueError("a period divides a multiplier")
    D = np.empty_like(R)
    gens = []
    for c, p in enumerate(primes):
        g = primitive_root(p)
        gens.append(g)
        D[:, c] = dlog_table(p, g)[R[:, c]]
    K = b - a
    if a > 0:
        prev, cur = D[:, :K], D[:, 1:]
    else:
        prev = np.concatenate([np.zeros((D.shape[0], 1), dtype=np.int64), D[:, :K - 1]], axis=1)
        cur = D
    shape1 = (params.num_windows1, 1 << params.window1)
    t1 = ((cur - prev) % (1 << 32)).T.reshape((K,) + shape1)
    t1_final = ((-D[:, -1]) % (1 << 32)).reshape(shape1) if b == len(P) else None
    gens = gens[a - first:]
    t3 = [_table3(params, int(p), g) for p, g in zip(P[a:b], gens)]
    t4 = np.stack([_table4(params, int(p), ctx.L, ctx.LmodN) for p in P[a:b]])
    return dict(
        t1=t1, t1_final=t1_final,
        t3a=np.stack([x[0] for x in t3]), t3b=np.stack([x[1] for x in t3]), t3c=np.stack([x[2] for x in t3]),
        t4=t4, R=R[:, a - first:], generators=gens,
    )


def build_tables(params: Params, periods: Sequence[int]) -> dict[str, Any]:
    """All tables (for small instances): lists in the shapes MakeConfig takes."""
    ctx = _Ctx(params, periods)
    T = _chunk_tables(ctx, 0, len(periods))
    t1 = np.concatenate([T["t1"], T["t1_final"][None]], axis=0)
    return dict(
        generators=T["generators"], table1=t1.tolist(), table3a=T["t3a"].tolist(),
        table3b=T["t3b"].tolist(), table3c=T["t3c"].tolist(), table4=T["t4"].tolist(),
    )


def prime_tables(params: Params, periods: Sequence[int], indices: Sequence[int]) -> list[dict[str, Any]]:
    """Real tables of selected primes: table1 rows i and i + 1 (the final row when i = |P| - 1)."""
    ctx = _Ctx(params, periods)
    out = []
    for i in indices:
        T = _chunk_tables(ctx, i, i + 1)
        if i + 1 < len(periods):
            nxt = _chunk_tables(ctx, i + 1, i + 2)["t1"][0]
        else:
            nxt = T["t1_final"]
        out.append(dict(index=i, period=int(periods[i]), generator=T["generators"][0],
                        t1=T["t1"][0], t1_next=nxt, t3a=T["t3a"][0], t3b=T["t3b"][0],
                        t3c=T["t3c"][0], t4=T["t4"][0]))
    return out


# ------------------------------------------------------------------------------------------------
# Lookup costs.


def _pp(k: int) -> int:
    return 0 if k == 0 else (1 << k) - k - 1


_SEL: dict[int, np.ndarray] = {}


def lookup_toffolis(data: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Toffolis of OptimizedLookup (lib/lookup_phaseup.qs) for each row of `data` (T x 2^n, values
    already reduced to the target width), and the number of power-product pairs whose output mask is
    zero. Cost = (2^lo - lo - 1) + (2^hi - hi - 1) + #{monomials s, s_lo != 0 and s_hi != 0, with a
    non-zero mask}; the mask of s is the XOR (Moebius) transform of the table, bitwise."""
    a = np.ascontiguousarray(data, dtype=np.uint64).reshape(-1, 1 << n).copy()
    T = a.shape[0]
    for b in range(n):
        v = a.reshape(T, 1 << (n - b - 1), 2, 1 << b)
        v[:, :, 1, :] ^= v[:, :, 0, :]
    lo, hi = n // 2, n - n // 2
    if n not in _SEL:
        s = np.arange(1 << n)
        _SEL[n] = ((s & ((1 << lo) - 1)) != 0) & ((s >> lo) != 0)
    sel = _SEL[n]
    nz = (a[:, sel] != 0).sum(axis=1)
    return _pp(lo) + _pp(hi) + nz, int(sel.sum()) - nz


@dataclasses.dataclass(frozen=True)
class LookupSpec:
    kind: str     # loop1 | loop3 | loop4 | loop4_cmp | unloop3 | unloop3_cmp
    table: str    # t1 | t3a | t3b | t3c | t4
    j: int
    k: int
    len0: int     # low address part (or the whole address for t1/t3c/t4)
    len1: int     # high address part (t3a/t3b only)
    transform: str  # none | p_minus | trunc_minus
    width: int
    conditional: bool

    @property
    def n(self) -> int:
        return self.len0 + self.len1


def lookup_specs(params: Params) -> list[LookupSpec]:
    """Every lookup of one prime's iteration of modexp.qs, in order, with its table, address size,
    and target width (TableBits(data, Length(target)))."""
    ell = params.prime_bit_length
    f = params.len_accumulator
    m = params.num_input_qubits
    w1, w3a, w3b, w4 = params.window1, params.window3a, params.window3b, params.window4
    W1, W3a, W3b, W4 = params.num_windows1, params.num_windows3a, params.num_windows3b, params.num_windows4
    specs = []
    for j in range(W1):  # Loop1: Q_dlog += table1[i, j][Q_k]
        specs.append(LookupSpec("loop1", "t1", j, 0, min(w1, m - j * w1), 0, "none", params.len_dlog, False))
    # Loop3: Q_result ^= table3c[Q_dlog[:2 w3a]]; then Q_helper -= table3a[i, j, k][Q_l]
    specs.append(LookupSpec("loop3", "t3c", 0, 0, 2 * w3a, 0, "none", ell + 1, False))
    for j in range(2, W3a):
        for k in range(W3b):
            len0 = min(w3b, ell + 1 - k * w3b)  # window of Q_result (ell + 1 qubits)
            len1 = min(w3a, ell - j * w3a)      # window of the compressed dlog (ell qubits)
            specs.append(LookupSpec("loop3", "t3a", j, k, len0, len1, "none", ell + 1, False))
    for j in range(W4):  # Loop4 over the residue register (ell + 1 qubits)
        ln = min(w4, ell + 1 - j * w4)
        specs.append(LookupSpec("loop4", "t4", j, 0, ln, 0, "none", f + 1, False))
        specs.append(LookupSpec("loop4_cmp", "t4", j, 0, ln, 0, "trunc_minus", f, True))
    for j in range(W3a - 1, 1, -1):  # Unloop3
        for k in range(W3b - 1, -1, -1):
            len1 = min(w3b, ell + 1 - k * w3b)  # window of Q_unresult: the low part
            len0 = min(w3a, ell - j * w3a)      # window of the dlog: the high part
            specs.append(LookupSpec("unloop3", "t3b", j, k, len1, len0, "p_minus", ell + 1, False))
            specs.append(LookupSpec("unloop3_cmp", "t3b", j, k, len1, len0, "none", ell, True))
        for k in range(W3b - 1, -1, -1):
            len1 = min(w3b, ell + 1 - k * w3b)
            len0 = min(w3a, ell - j * w3a)
            specs.append(LookupSpec("unloop3", "t3a", j, k, len1, len0, "p_minus", ell + 1, False))
            specs.append(LookupSpec("unloop3_cmp", "t3a", j, k, len1, len0, "none", ell, True))
    return specs


def lookup_data(spec: LookupSpec, T: dict[str, np.ndarray], periods: np.ndarray, params: Params,
                t1_key: str = "t1") -> np.ndarray:
    """(K, 2^n) table values of `spec` for K primes, exactly as modexp.qs passes them to TableBits."""
    size = 1 << spec.n
    if spec.table == "t1":
        d = T[t1_key][..., spec.j, :size] % (1 << params.len_dlog)
    elif spec.table == "t3c":
        d = T["t3c"][:, :size]
    elif spec.table == "t4":
        d = T["t4"][:, spec.j, :size]
    else:
        a = np.arange(size)
        idx = (a & ((1 << spec.len0) - 1)) + ((a >> spec.len0) << params.window3b)
        d = T[spec.table][:, spec.j, spec.k, idx]
    d = np.asarray(d, dtype=np.int64)
    if d.ndim == 1:
        d = d[None]
    if spec.transform == "p_minus":
        d = periods[:, None] - d
    elif spec.transform == "trunc_minus":
        d = params.trunc - d
    assert (d >= 0).all()
    return (d & ((1 << spec.width) - 1)).astype(np.uint64)


KINDS = ("loop1", "loop3", "loop4", "loop4_cmp", "unloop3", "unloop3_cmp")


def iteration_costs(params: Params, periods: np.ndarray, T: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Per-prime lookup Toffolis and zero-mask pairs, by kind (vectorized over the primes in T)."""
    out = {k: np.zeros(len(periods), dtype=np.int64) for k in KINDS}
    zeros = {k: np.zeros(len(periods), dtype=np.int64) for k in KINDS}
    for spec in lookup_specs(params):
        t, z = lookup_toffolis(lookup_data(spec, T, periods, params), spec.n)
        out[spec.kind] += t
        zeros[spec.kind] += z
    return dict(toffolis=out, zero_pairs=zeros)


def final_loop1_costs(params: Params, t1_row: np.ndarray) -> tuple[int, int]:
    tof = zp = 0
    for spec in lookup_specs(params):
        if spec.kind == "loop1":
            t, z = lookup_toffolis(lookup_data(spec, {"t1": t1_row[None]}, np.zeros(1, np.int64), params), spec.n)
            tof += int(t[0])
            zp += int(z[0])
    return tof, zp


# Synthetic tables (modexp.qs SynthTable) for the cached count's correction.


def synth_table(seed: int, size: int, bound: int) -> list[int]:
    x = (seed * 7919 + 104729) % 2147483648
    out = []
    for _ in range(size):
        x = (x * 1103515245 + 12345) % 2147483648
        a = x
        x = (x * 1103515245 + 12345) % 2147483648
        b = x
        out.append((a * 2147483648 + b) % bound)
    return out


def synthetic_tables(params: Params, i: int, period: int) -> dict[str, np.ndarray]:
    """The tables modexp.qs uses for prime index i when Synthetic = true, laid out so that
    lookup_data returns exactly what GetTable* returns."""
    W1, W3a, W3b, W4 = params.num_windows1, params.num_windows3a, params.num_windows3b, params.num_windows4
    ell = params.prime_bit_length
    t1 = np.zeros((1, W1, 1 << params.window1), dtype=np.int64)
    for j in range(W1):
        ln = min(params.window1, params.num_input_qubits - j * params.window1)
        t1[0, j, :1 << ln] = synth_table(1000003 * (i + 1) + 17 * j + 1, 1 << ln, 1 << params.len_dlog)
    t3 = {}
    for which, name in ((0, "t3a"), (1, "t3b")):
        arr = np.zeros((1, W3a, W3b, 1 << (params.window3a + params.window3b)), dtype=np.int64)
        for j in range(W3a):
            for k in range(W3b):
                len0 = min(params.window3b, ell + 1 - k * params.window3b)
                len1 = min(params.window3a, ell - j * params.window3a) if j * params.window3a < ell else 0
                size = 1 << (len0 + len1)
                vals = synth_table(1000003 * (i + 1) + 7919 * which + 101 * j + k, size, period)
                a = np.arange(size)
                idx = (a & ((1 << len0) - 1)) + ((a >> len0) << params.window3b)
                arr[0, j, k, idx] = vals
        t3[name] = arr
    t3c = np.array([synth_table(1000003 * (i + 1) + 5, 1 << (2 * params.window3a), period)], dtype=np.int64)
    t4 = np.zeros((1, W4, 1 << params.window4), dtype=np.int64)
    for j in range(W4):
        ln = min(params.window4, ell + 1 - j * params.window4)
        t4[0, j, :1 << ln] = synth_table(1000003 * (i + 1) + 31 * j + 3, 1 << ln, params.trunc)
    return dict(t1=t1, t3a=t3["t3a"], t3b=t3["t3b"], t3c=t3c, t4=t4)


def synthetic_iteration_costs(params: Params, i: int, period: int) -> dict[str, int]:
    T = synthetic_tables(params, i, period)
    c = iteration_costs(params, np.array([period], dtype=np.int64), T)["toffolis"]
    return {k: int(v[0]) for k, v in c.items()}


def synthetic_final_cost(params: Params, num_periods: int) -> int:
    T = synthetic_tables(params, num_periods, 3)
    return final_loop1_costs(params, T["t1"][0])[0]


# ------------------------------------------------------------------------------------------------
# Full scan: tables, lookup costs, table digest, and deviation samples, chunked over primes.

_CTX: _Ctx | None = None


def _scan_init(ctx: _Ctx) -> None:
    global _CTX
    _CTX = ctx


def _scan_chunk(ab: tuple[int, int]) -> dict[str, Any]:
    a, b = ab
    ctx = _CTX
    params = ctx.params
    T = _chunk_tables(ctx, a, b)
    periods = ctx.periods[a:b]
    costs = iteration_costs(params, periods, T)
    h = hashlib.sha256()
    for key in ("t1", "t3a", "t3b", "t3c", "t4"):
        h.update(np.ascontiguousarray(T[key], dtype="<i8").tobytes())
    out = dict(a=a, b=b, costs=costs, digest=h.digest(), final=None)
    if T["t1_final"] is not None:
        out["final"] = final_loop1_costs(params, T["t1_final"])
        out["final_digest"] = hashlib.sha256(np.ascontiguousarray(T["t1_final"], dtype="<i8").tobytes()).digest()
    if ctx.digits is not None:
        digits = ctx.digits
        S, K = digits.shape[0], b - a
        R = T["R"]
        acc = np.ones((S, K), dtype=np.int64)
        p = periods[None, :]
        rows_per_window = 1 << params.window1
        for j in range(params.num_windows1):
            acc = acc * R[j * rows_per_window + digits[:, j].astype(np.int64)] % p
        t4 = T["t4"]
        total = np.zeros(S, dtype=np.int64)
        cols = np.arange(K)[None, :]
        mask = (1 << params.window4) - 1
        for w in range(params.num_windows4):
            idx = (acc >> (params.window4 * w)) & mask
            total += t4[cols, w, idx].sum(axis=1)
            total %= params.trunc
        out["table4_sum"] = total
    return out


@dataclasses.dataclass
class ScanResult:
    num_primes: int
    lookup_toffolis: dict[str, np.ndarray]   # per prime, by kind
    zero_pairs: dict[str, np.ndarray]
    final_loop1_toffolis: int
    final_loop1_zero_pairs: int
    table_digest: str
    table4_sum: np.ndarray | None             # per sample, sum of table4 entries mod trunc
    seconds: float


def scan(params: Params, periods: Sequence[int], *, digits: np.ndarray | None = None,
         chunk: int = 256, workers: int | None = None) -> ScanResult:
    t0 = time.monotonic()
    ctx = _Ctx(params, periods, digits)
    n = len(periods)
    ranges = [(a, min(a + chunk, n)) for a in range(0, n, chunk)]
    workers = workers or os.cpu_count() or 1
    with mp.get_context("spawn").Pool(workers, initializer=_scan_init, initargs=(ctx,)) as pool:
        parts = pool.map(_scan_chunk, ranges, chunksize=1)
    parts.sort(key=lambda r: r["a"])
    tof = {k: np.concatenate([r["costs"]["toffolis"][k] for r in parts]) for k in KINDS}
    zp = {k: np.concatenate([r["costs"]["zero_pairs"][k] for r in parts]) for k in KINDS}
    h = hashlib.sha256()
    for r in parts:
        h.update(r["digest"])
    h.update(parts[-1]["final_digest"])
    t4sum = None
    if digits is not None:
        t4sum = np.zeros(digits.shape[0], dtype=np.int64)
        for r in parts:
            t4sum = (t4sum + r["table4_sum"]) % params.trunc
    final = parts[-1]["final"]
    return ScanResult(n, tof, zp, final[0], final[1], h.hexdigest(), t4sum, time.monotonic() - t0)


# ------------------------------------------------------------------------------------------------
# Failed-shot rate.


def p_deviant_bound(params: Params, num_primes: int, wraparound_deviation: float | None = None) -> dict[str, float]:
    """Eq. 43 with the author's tally (probability_of_deviation_failure): epsilon is the number of
    truncated additions (num_windows4 per prime) times (2 * 2^-f + the wraparound term), where the
    wraparound term is 2^-min_wraparound_gap, or the actual Delta_N(L) when given."""
    f = params.len_accumulator
    adds = params.num_windows4 * num_primes
    wrap = 2.0 ** -params.min_wraparound_gap if wraparound_deviation is None else wraparound_deviation
    eps = adds * (2 * 2.0 ** -f + wrap)
    S = 2.0 ** (params.mask_bits - f)
    return dict(additions=adds, epsilon=eps, mask_proportion=S, p_deviant=S + eps / S)


def sample_exponents(params: Params, num_samples: int, seed: int) -> tuple[list[int], np.ndarray]:
    rng = random.Random(seed)
    es = [rng.getrandbits(params.num_input_qubits) for _ in range(num_samples)]
    mask = (1 << params.window1) - 1
    digits = np.array([[(e >> (params.window1 * j)) & mask for j in range(params.num_windows1)] for e in es],
                      dtype=np.uint8)
    return es, digits


def _exact_pow(args: tuple[int, list[int], int]) -> list[int]:
    g, es, N = args
    return [pow(g, e, N) for e in es]


def exact_values(params: Params, es: Sequence[int], *, workers: int | None = None) -> list[int]:
    workers = workers or os.cpu_count() or 1
    step = -(-len(es) // (workers * 4))
    jobs = [(params.generator, list(es[a:a + step]), params.modulus) for a in range(0, len(es), step)]
    with mp.get_context("spawn").Pool(workers) as pool:
        return [v for part in pool.map(_exact_pow, jobs) for v in part]


def deviations(params: Params, exact: Sequence[int], table4_sum: np.ndarray, s: int = 0) -> np.ndarray:
    """Modular deviation of the circuit's output (with mask value s) from g^e mod N, per sample."""
    N, trunc, dropped = params.modulus, params.trunc, params.dropped_bits
    out = np.empty(len(exact))
    for k, (x, t) in enumerate(zip(exact, table4_sum)):
        result = (s - int(t)) % trunc
        approx = ((result - s) % trunc) << dropped
        err = (x - approx) % N
        out[k] = min(err, N - err) / N
    return out


def model_output(params: Params, periods: Sequence[int], table4, e: int, s: int) -> int:
    """Scalar closed form of what the circuit leaves in Q_result: (s - sum_i sum_j
    table4[i][j][window_j(P(e) mod p_i)]) mod trunc, P(e) the integer product of the multipliers."""
    M = multipliers(params)
    w1 = params.window1
    product = 1
    for j in range(params.num_windows1):
        product *= M[j * (1 << w1) + ((e >> (w1 * j)) & ((1 << w1) - 1))]
    total = s
    mask = (1 << params.window4) - 1
    for i, p in enumerate(periods):
        r = product % int(p)
        for j in range(params.num_windows4):
            total -= int(table4[i][j][(r >> (params.window4 * j)) & mask])
    return total % params.trunc
