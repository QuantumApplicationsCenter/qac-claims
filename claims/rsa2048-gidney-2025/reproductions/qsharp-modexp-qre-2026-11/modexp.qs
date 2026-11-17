// The approximate modular exponentiation of Gidney (2025), "How to factor 2048 bit RSA integers with
// less than a million noisy qubits" (arXiv:2505.15917), Appendix A.1, as one Q# operation.
//
// Every subroutine below mirrors the reference Python of A.1 (`approx_modexp`, `loop1`, `loop2`,
// `loop3`, `loop4`, `unloop3`, `unloop2`) statement by statement; the A.1 line is quoted in a comment
// above the code that implements it. Requires lookup_phaseup.qs (OptimizedLookup, Phaseup,
// MeasureXAndReset, PhaseTableFromMx, XorTables) to be loaded first.
//
// Mapping of A.1 primitives to circuits:
//   Q_a += T[Q_k]          lookup T into a fresh register, Gidney adder, X-measure the register; the phase
//                          table owed (PhaseTableFromMx) is XORed into the table's vent (AddLookup).
//   Q_a ^= T[Q_k]          the same with CNOTs instead of the adder (XorLookup).
//   Q_a -= c (classical)   c written into a fresh register with X gates, adjoint Gidney adder (AddConst).
//   Q_t[:n] += Q_t[n].ghz_lookup(k)
//                          CNOT-fan Q_t[n] into a fresh register where k has 1 bits, add, un-fan
//                          (AddConstControlled). Counted as an addition, not a lookup.
//   qpu.z(Q_a >= T[Q_k])   lookup T into a fresh register, phase-flip comparator with n - 1 Toffolis,
//                          X-measure the register, vent the owed phase table (PhaseCompareLookup).
//   qpu.z(V[Q_k])          Phaseup(Q_k, V) (Appendix A.3).
//   Q.mx_rz(), del_measure_x
//                          MResetX on every qubit.
//   qpu.cz(Q, mask)        Z on the qubits of Q where mask has 1 bits.
//   qpu.z(int)             a global phase of -1 when the int has odd parity (kept so the full state,
//                          not just the state up to global phase, can be checked in simulation).
//   push/pop_uncompute_info
//                          classical arrays handed from Loop3 to Unloop3 (Loop3Info).
//
// Registers are little-endian. A window that runs past the end of its register is shortened, and its
// table is restricted to the addresses the shortened window can hold (as the A.1 slicing implies).

import Std.Arrays.*;
import Std.Math.*;
import Std.Convert.*;
import Std.Arithmetic.*;
import Std.Measurement.*;
import Std.ResourceEstimation.*;

struct ModExpConfig {
    Periods : Int[],
    LenDlog : Int,          // conf.len_dlog_accumulator = ell + len(m)
    LenAcc : Int,           // conf.len_accumulator = f; Q_result has f + 1 qubits
    MaskBits : Int,
    Trunc : Int,            // conf.truncated_modulus = N >> dropped_bits
    W1 : Int,
    W3a : Int,
    W3b : Int,
    W4 : Int,
    NumWindows1 : Int,
    NumWindows3a : Int,
    NumWindows3b : Int,
    NumWindows4 : Int,
    Table1 : Int[][][],     // [i][j][k], i in 0..|P| (|P| + 1 rows)
    Table3a : Int[][][][],  // [i][ja][jb][addr]
    Table3b : Int[][][][],
    Table3c : Int[][],      // [i][addr]
    Table4 : Int[][][],     // [i][j][k]
    // Counting-only switches. Synthetic: ignore the tables and use deterministic pseudo-random dense
    // tables of the right shapes (Toffoli counts don't depend on table contents for dense tables).
    // CompareMode: 0 = follow the measurement outcomes (the real circuit); 1 = always run the
    // measurement-conditioned comparisons; 2 = never run them. Modes 1 and 2 break phase correctness and
    // exist only so the expected cost (each condition has probability exactly 1/2) can be computed.
    Synthetic : Bool,
    CompareMode : Int,
    // Wrap each prime's iteration in BeginEstimateCaching/EndEstimateCaching (counting only).
    CacheBody : Bool,
}

// ------------------------------------------------------------------------------------------------
// Tables.

/// Deterministic pseudo-random table with `size` entries in [0, bound).
function SynthTable(seed : Int, size : Int, bound : Int) : Int[] {
    mutable x = (seed * 7919 + 104729) % 2147483648;
    mutable out = [0, size = size];
    for k in 0..size - 1 {
        set x = (x * 1103515245 + 12345) % 2147483648;
        let a = x;
        set x = (x * 1103515245 + 12345) % 2147483648;
        let b = x;
        set out w/= k <- (a * 2147483648 + b) % bound;
    }
    out
}

function Bits(value : Int, width : Int) : Bool[] {
    mutable out = [false, size = width];
    for b in 0..width - 1 {
        set out w/= b <- ((value >>> b) &&& 1) == 1;
    }
    out
}

function TableBits(data : Int[], width : Int) : Bool[][] {
    mutable out = [];
    for v in data {
        set out += [Bits(v, width)];
    }
    out
}

/// Restrict a table addressed by (hi << w0) | lo to a register whose low part has len0 <= w0 qubits
/// and whose high part has len1 qubits.
function CompactTable(table : Int[], w0 : Int, len0 : Int, len1 : Int) : Int[] {
    mutable out = [];
    for a in 0..(1 <<< (len0 + len1)) - 1 {
        let lo = a &&& ((1 <<< len0) - 1);
        let hi = a >>> len0;
        set out += [table[lo + (hi <<< w0)]];
    }
    out
}

function Window(qs : Qubit[], start : Int, width : Int) : Qubit[] {
    qs[start..MinI(start + width, Length(qs)) - 1]
}

function Mod2n(v : Int, n : Int) : Int {
    v &&& ((1 <<< n) - 1)
}

function GetTable1(cfg : ModExpConfig, i : Int, j : Int, addrLen : Int) : Int[] {
    let size = 1 <<< addrLen;
    if cfg.Synthetic {
        return SynthTable(1000003 * (i + 1) + 17 * j + 1, size, 1 <<< cfg.LenDlog);
    }
    Mapped(v -> Mod2n(v, cfg.LenDlog), cfg.Table1[i][j][...size - 1])
}

function GetTable3(cfg : ModExpConfig, which : Int, i : Int, j : Int, k : Int, len0 : Int, len1 : Int) : Int[] {
    if cfg.Synthetic {
        return SynthTable(1000003 * (i + 1) + 7919 * which + 101 * j + k, 1 <<< (len0 + len1), cfg.Periods[i]);
    }
    let t = which == 0 ? cfg.Table3a[i][j][k] | cfg.Table3b[i][j][k];
    CompactTable(t, cfg.W3b, len0, len1)
}

function GetTable3c(cfg : ModExpConfig, i : Int) : Int[] {
    if cfg.Synthetic {
        return SynthTable(1000003 * (i + 1) + 5, 1 <<< (2 * cfg.W3a), cfg.Periods[i]);
    }
    cfg.Table3c[i]
}

function GetTable4(cfg : ModExpConfig, i : Int, j : Int, addrLen : Int) : Int[] {
    let size = 1 <<< addrLen;
    if cfg.Synthetic {
        return SynthTable(1000003 * (i + 1) + 31 * j + 3, size, cfg.Trunc);
    }
    cfg.Table4[i][j][...size - 1]
}

// ------------------------------------------------------------------------------------------------
// Primitive operations.

/// `target += data[address]` (or `-=`): lookup into a fresh register, Gidney adder, X-measurement
/// uncomputation of the register. Returns the phase table owed (the caller vents it).
operation AddLookup(data : Int[], address : Qubit[], target : Qubit[], subtract : Bool) : Bool[] {
    let bits = TableBits(data, Length(target));
    use tmp = Qubit[Length(target)];
    OptimizedLookup(bits, address, tmp);
    if subtract {
        Adjoint RippleCarryCGIncByLE(tmp, target);
    } else {
        RippleCarryCGIncByLE(tmp, target);
    }
    PhaseTableFromMx(bits, MeasureXAndReset(tmp))
}

/// `target ^= data[address]`, vented the same way.
operation XorLookup(data : Int[], address : Qubit[], target : Qubit[]) : Bool[] {
    let bits = TableBits(data, Length(target));
    use tmp = Qubit[Length(target)];
    OptimizedLookup(bits, address, tmp);
    for b in 0..Length(target) - 1 {
        CNOT(tmp[b], target[b]);
    }
    PhaseTableFromMx(bits, MeasureXAndReset(tmp))
}

/// `target += c` or `target -= c` (mod 2^n) for a classical constant c.
operation AddConst(c : Int, target : Qubit[], subtract : Bool) : Unit {
    use tmp = Qubit[Length(target)];
    within {
        ApplyXorInPlace(Mod2n(c, Length(target)), tmp);
    } apply {
        if subtract {
            Adjoint RippleCarryCGIncByLE(tmp, target);
        } else {
            RippleCarryCGIncByLE(tmp, target);
        }
    }
}

/// `target += ctrl.ghz_lookup(c)` (or `-=`): add c when ctrl is set.
operation AddConstControlled(ctrl : Qubit, c : Int, target : Qubit[], subtract : Bool) : Unit {
    let n = Length(target);
    use tmp = Qubit[n];
    within {
        for b in 0..n - 1 {
            if ((c >>> b) &&& 1) == 1 {
                CNOT(ctrl, tmp[b]);
            }
        }
    } apply {
        if subtract {
            Adjoint RippleCarryCGIncByLE(tmp, target);
        } else {
            RippleCarryCGIncByLE(tmp, target);
        }
    }
}

/// Negate the amplitude when a + b + carryIn >= 2^n (n = Length(a) = Length(b)).
/// Gidney-style carry chain: n - 1 ANDs, the last carry applied in phase (Z + CZ), uncomputed by
/// measurement (Adjoint AND), so n - 1 Toffolis in total.
operation PhaseFlipIfCarry(a : Qubit[], b : Qubit[], carryIn : Bool) : Unit {
    let n = Length(a);
    if n == 1 {
        if carryIn {
            Z(a[0]);
            Z(b[0]);
        }
        CZ(a[0], b[0]);
    } else {
        use c = Qubit[n - 1]; // c[i] holds the carry into bit i + 1
        within {
            if carryIn {
                within {
                    X(a[0]);
                    X(b[0]);
                } apply {
                    AND(a[0], b[0], c[0]);
                }
                X(c[0]);
            } else {
                AND(a[0], b[0], c[0]);
            }
            for i in 1..n - 2 {
                within {
                    CNOT(c[i - 1], a[i]);
                    CNOT(c[i - 1], b[i]);
                } apply {
                    AND(a[i], b[i], c[i]);
                }
                CNOT(c[i - 1], c[i]);
            }
            CNOT(c[n - 2], a[n - 1]);
            CNOT(c[n - 2], b[n - 1]);
        } apply {
            // carry out = c[n-2] xor (a' and b')
            Z(c[n - 2]);
            CZ(a[n - 1], b[n - 1]);
        }
    }
}

/// Negate the amplitude where x >= y: carry out of x + ~y + 1.
operation PhaseFlipIfGE(x : Qubit[], y : Qubit[]) : Unit {
    within {
        ApplyToEachA(X, y);
    } apply {
        PhaseFlipIfCarry(x, y, true);
    }
}

/// Negate the amplitude where x < y: carry out of y + ~x.
operation PhaseFlipIfLT(x : Qubit[], y : Qubit[]) : Unit {
    within {
        ApplyToEachA(X, x);
    } apply {
        PhaseFlipIfCarry(y, x, false);
    }
}

/// `qpu.z(x >= data[address])` (ge = true) or `qpu.z(x < data[address])` (ge = false): lookup into a
/// fresh register, phase comparison, X-measurement uncomputation. Returns the phase table owed.
operation PhaseCompareLookup(data : Int[], address : Qubit[], x : Qubit[], ge : Bool) : Bool[] {
    let bits = TableBits(data, Length(x));
    use tmp = Qubit[Length(x)];
    OptimizedLookup(bits, address, tmp);
    if ge {
        PhaseFlipIfGE(x, tmp);
    } else {
        PhaseFlipIfLT(x, tmp);
    }
    PhaseTableFromMx(bits, MeasureXAndReset(tmp))
}

/// `qpu.z(v)` for a classical int v: a global phase of -1 when v has odd parity.
operation GlobalPhaseFlip(q : Qubit) : Unit {
    R(PauliI, 2.0 * PI(), q);
}

operation ZMask(qs : Qubit[], mask : Bool[]) : Unit {
    for b in 0..Length(qs) - 1 {
        if mask[b] {
            Z(qs[b]);
        }
    }
}

function RunCompare(cfg : ModExpConfig, condition : Bool) : Bool {
    cfg.CompareMode == 1 or (cfg.CompareMode == 0 and condition)
}

// ------------------------------------------------------------------------------------------------
// Subroutines of Appendix A.1.

/// loop1: Q_dlog += lookup1[i, j][Q_k] for every window j, venting into vent[j].
operation Loop1(cfg : ModExpConfig, i : Int, exponent : Qubit[], dlog : Qubit[], vent : Bool[][]) : Bool[][] {
    mutable v = vent;
    for j in 0..cfg.NumWindows1 - 1 {
        // Q_k = Q_exponent[j * conf.window1 :][: conf.window1]
        let qk = Window(exponent, j * cfg.W1, cfg.W1);
        // table = conf.lookup1[i, j].venting_into(vent[j]); Q_dlog += table[Q_k]
        let owed = AddLookup(GetTable1(cfg, i, j, Length(qk)), qk, dlog, false);
        set v w/= j <- XorTables(v[j], owed);
    }
    v
}

/// loop2: compress Q_target % modulus into Q_target[:compressed_len].
operation Loop2(target : Qubit[], modulus : Int, compressedLen : Int) : Unit {
    mutable n = Length(target);
    while n > compressedLen {
        set n -= 1;
        let threshold = modulus <<< (n - compressedLen);
        // Q_target[: n + 1] -= threshold
        AddConst(threshold, target[...n], true);
        // Q_target[:n] += Q_target[n].ghz_lookup(threshold)
        AddConstControlled(target[n], threshold, target[...n - 1], false);
    }
}

/// unloop2: undo loop2.
operation Unloop2(target : Qubit[], modulus : Int, compressedLen : Int) : Unit {
    mutable n = compressedLen;
    while n < Length(target) {
        let threshold = modulus <<< (n - compressedLen);
        // Q_target[:n] -= Q_target[n].ghz_lookup(threshold)
        AddConstControlled(target[n], threshold, target[...n - 1], true);
        // Q_target[: n + 1] += threshold
        AddConst(threshold, target[...n], false);
        set n += 1;
    }
}

/// What loop3 pushes for unloop3 (qpu.push_uncompute_info), indexed instead of stacked.
struct Loop3Info {
    Vent3c : Bool[],          // table.vent of the lookup3c initialization
    Wraps : Bool[][],         // [j - 2][k] phase_wrap
    Vents : Bool[][][],       // [j - 2][k] table.vent
    HelperMx : Bool[][],      // [j - 2] Q_helper.mx_rz() after the swap
}

/// loop3: Q_result := pow(generators[i], Q_dlog, p). `out` (p.bit_length() + 1 qubits, zero) receives
/// the result; Q_helper is allocated here and released (zero) at the end, as in A.1.
operation Loop3(cfg : ModExpConfig, i : Int, dlog : Qubit[], out : Qubit[]) : Loop3Info {
    let modulus = cfg.Periods[i];
    let ell = BitSizeI(modulus);
    use helperReg = Qubit[ell + 1];
    // Q_result, Q_helper are swapped once per j; name them so the result ends in `out`.
    let swaps = MaxI(0, cfg.NumWindows3a - 2);
    mutable res = swaps % 2 == 0 ? out | helperReg;
    mutable helper = swaps % 2 == 0 ? helperReg | out;

    // table = conf.lookup3c[i].venting_into_new_table(); Q_l = Q_dlog[: conf.window3a * 2]
    // Q_result ^= table[Q_l]; qpu.push_uncompute_info(table.vent)
    let ql = dlog[...2 * cfg.W3a - 1];
    let vent3c = XorLookup(GetTable3c(cfg, i), ql, res);

    mutable wraps = [];
    mutable vents = [];
    mutable helperMx = [];
    for j in 2..cfg.NumWindows3a - 1 {
        // Q_l1 = Q_dlog[j * conf.window3a :][: conf.window3a]
        let ql1 = Window(dlog, j * cfg.W3a, cfg.W3a);
        mutable wj = [];
        mutable vj = [];
        for k in 0..cfg.NumWindows3b - 1 {
            // Q_l0 = Q_result[k * conf.window3b :][: conf.window3b]; Q_l = (Q_l1 << w3b) | Q_l0
            let ql0 = Window(res, k * cfg.W3b, cfg.W3b);
            let addr = ql0 + ql1;
            // table = conf.lookup3a[i, j, k].venting_into_new_table(); Q_helper -= table[Q_l]
            let vent = AddLookup(GetTable3(cfg, 0, i, j, k, Length(ql0), Length(ql1)), addr, helper, true);
            // Q_helper[:-1] += Q_helper[-1].ghz_lookup(modulus)
            AddConstControlled(helper[ell], modulus, helper[...ell - 1], false);
            // phase_wrap = Q_helper[-1].mx_rz(); qpu.push_uncompute_info((phase_wrap, table.vent))
            let phaseWrap = MResetX(helper[ell]) == One;
            set wj += [phaseWrap];
            set vj += [vent];
        }
        set wraps += [wj];
        set vents += [vj];
        // Q_result, Q_helper = Q_helper, Q_result
        let t = res;
        set res = helper;
        set helper = t;
        // qpu.push_uncompute_info(Q_helper.mx_rz())
        set helperMx += [MeasureXAndReset(helper)];
    }
    // Q_helper.del_by_equal_to(0): helperReg is released zero at the end of this scope.
    new Loop3Info { Vent3c = vent3c, Wraps = wraps, Vents = vents, HelperMx = helperMx }
}

/// loop4: Q_acc += the residue's approximate contribution (as subtractions mod the truncated modulus).
operation Loop4(cfg : ModExpConfig, i : Int, residue : Qubit[], acc : Qubit[]) : Unit {
    let f = cfg.LenAcc;
    let trunc = cfg.Trunc;
    for j in 0..cfg.NumWindows4 - 1 {
        // Q_k = Q_residue[j * conf.window4 :][: conf.window4]
        let qk = Window(residue, j * cfg.W4, cfg.W4);
        // table = conf.lookup4[i, j].venting_into_new_table(); table2 = trunc - table
        let table = GetTable4(cfg, i, j, Length(qk));
        let table2 = Mapped(v -> trunc - v, table);
        // Q_acc -= table[Q_k]
        mutable vent = AddLookup(table, qk, acc, true);
        // Q_acc[:-1] += Q_acc[-1].ghz_lookup(trunc)
        AddConstControlled(acc[f], trunc, acc[...f - 1], false);
        // if Q_acc[-1].mx_rz(): qpu.z(Q_acc[:-1] >= table2[Q_k])
        let wrap = MResetX(acc[f]) == One;
        if RunCompare(cfg, wrap) {
            set vent = XorTables(vent, PhaseCompareLookup(table2, qk, acc[...f - 1], true));
        }
        // qpu.z(table.vent[Q_k])
        Phaseup(qk, vent);
    }
}

/// unloop3: uncompute Q_residue := pow(generators[i], Q_dlog, p) and release it.
operation Unloop3(cfg : ModExpConfig, i : Int, unresultReg : Qubit[], dlog : Qubit[], info : Loop3Info) : Unit {
    let modulus = cfg.Periods[i];
    let ell = BitSizeI(modulus);
    use helperReg = Qubit[ell + 1];
    mutable unres = unresultReg;
    mutable helper = helperReg;
    for j in cfg.NumWindows3a - 1..-1..2 {
        // Q_l0 = Q_dlog[j * conf.window3a :][: conf.window3a]
        let ql0 = Window(dlog, j * cfg.W3a, cfg.W3a);
        // Perform `let Q_helper := Q_unresult * X^-1 % N`
        for k in cfg.NumWindows3b - 1..-1..0 {
            // Q_l1 = Q_unresult[k * w3b :][: w3b]; Q_l = (Q_l0 << w3b) | Q_l1
            let ql1 = Window(unres, k * cfg.W3b, cfg.W3b);
            let addr = ql1 + ql0;
            // table1 = conf.lookup3b[i, j, k].venting_into_new_table(); table2 = modulus - table1
            let table1 = GetTable3(cfg, 1, i, j, k, Length(ql1), Length(ql0));
            let table2 = Mapped(v -> modulus - v, table1);
            // Q_helper -= table2[Q_l]
            mutable vent = AddLookup(table2, addr, helper, true);
            // Q_helper[:-1] += Q_helper[-1].ghz_lookup(modulus)
            AddConstControlled(helper[ell], modulus, helper[...ell - 1], false);
            // not_phase_wrap = Q_helper[-1].mx_rz(); qpu.z(not_phase_wrap)
            let notPhaseWrap = MResetX(helper[ell]) == One;
            if notPhaseWrap {
                GlobalPhaseFlip(helper[ell]);
            }
            // if not_phase_wrap: qpu.z(Q_helper[:-1] < table1[Q_l])
            if RunCompare(cfg, notPhaseWrap) {
                set vent = XorTables(vent, PhaseCompareLookup(table1, addr, helper[...ell - 1], false));
            }
            // qpu.z(table1.vent[Q_l])
            Phaseup(addr, vent);
        }
        // qpu.cz(Q_helper, qpu.pop_uncompute_info())
        ZMask(helper, info.HelperMx[j - 2]);
        // Q_unresult, Q_helper = Q_helper, Q_unresult
        let t = unres;
        set unres = helper;
        set helper = t;
        // Perform `del Q_helper := Q_unresult * X % N`
        for k in cfg.NumWindows3b - 1..-1..0 {
            let ql1 = Window(unres, k * cfg.W3b, cfg.W3b);
            let addr = ql1 + ql0;
            // phase_wrap, phase_table = qpu.pop_uncompute_info()
            let phaseWrap = info.Wraps[j - 2][k];
            // table1 = conf.lookup3a[i, j, k].venting_into(phase_table); table2 = modulus - table1
            let table1 = GetTable3(cfg, 0, i, j, k, Length(ql1), Length(ql0));
            let table2 = Mapped(v -> modulus - v, table1);
            // Q_helper -= table2[Q_l]
            mutable phaseTable = XorTables(info.Vents[j - 2][k], AddLookup(table2, addr, helper, true));
            // Q_helper[:-1] += Q_helper[-1].ghz_lookup(modulus)
            AddConstControlled(helper[ell], modulus, helper[...ell - 1], false);
            // not_phase_wrap = Q_helper[-1].mx_rz(); qpu.z(not_phase_wrap)
            let notPhaseWrap = MResetX(helper[ell]) == One;
            if notPhaseWrap {
                GlobalPhaseFlip(helper[ell]);
            }
            // if phase_wrap ^ not_phase_wrap: qpu.z(Q_helper[:-1] < table1[Q_l])
            if RunCompare(cfg, phaseWrap != notPhaseWrap) {
                set phaseTable = XorTables(phaseTable, PhaseCompareLookup(table1, addr, helper[...ell - 1], false));
            }
            // qpu.z(phase_table[Q_l])
            Phaseup(addr, phaseTable);
        }
    }
    // Q_helper.del_by_equal_to(0): `helper` is zero here (checked when released).
    // mx = Q_unresult.del_measure_x()
    let table3c = GetTable3c(cfg, i);
    let bits3c = TableBits(table3c, ell + 1);
    let mx = MeasureXAndReset(unres);
    // vent = qpu.pop_uncompute_info(); vent ^= conf.lookup3c[i].phase_corrections_for_mx(mx)
    let vent = XorTables(info.Vent3c, PhaseTableFromMx(bits3c, mx));
    // qpu.z(vent[Q_dlog[: conf.window3a * 2]])
    Phaseup(dlog[...2 * cfg.W3a - 1], vent);
}

/// One iteration of the outer loop of approx_modexp (one prime of the residue system).
operation PrimeIteration(cfg : ModExpConfig, i : Int, exponent : Qubit[], dlog : Qubit[], acc : Qubit[], vent1 : Bool[][]) : Bool[][] {
    let p = cfg.Periods[i];
    let ell = BitSizeI(p);
    // loop1(Q_dlog, Q_exponent, vent=loop1_vent, i)
    let v = Loop1(cfg, i, exponent, dlog, vent1);
    // Q_compressed = loop2(Q_dlog, p - 1, p.bit_length())
    Loop2(dlog, p - 1, ell);
    let compressed = dlog[...ell - 1];
    // Q_residue = loop3(Q_compressed, i)
    use residue = Qubit[ell + 1];
    let info = Loop3(cfg, i, compressed, residue);
    // loop4(Q_residue, Q_result, i)
    Loop4(cfg, i, residue, acc);
    // unloop3(Q_residue, Q_compressed, i)
    Unloop3(cfg, i, residue, compressed, info);
    // unloop2(Q_dlog, p - 1, p.bit_length())
    Unloop2(dlog, p - 1, ell);
    v
}

function InitialVent1(cfg : ModExpConfig, numExponentQubits : Int) : Bool[][] {
    mutable vent = [];
    for j in 0..cfg.NumWindows1 - 1 {
        let len = MinI(cfg.W1, numExponentQubits - j * cfg.W1);
        set vent += [[false, size = 1 <<< len]];
    }
    vent
}

/// Q_result = alloc_quint(length=len_accumulator + 1, scatter=True, scatter_range=1 << mask_bits)
operation PrepareMask(cfg : ModExpConfig, acc : Qubit[]) : Unit {
    ApplyToEach(H, acc[...cfg.MaskBits - 1]);
}

/// approx_modexp (Appendix A.1). `exponent` is Q_exponent; `acc` is Q_result (len_accumulator + 1
/// qubits), already holding its mask (see PrepareMask). On return `acc` holds the approximate modular
/// exponentiation added to the mask, every other qubit is released in |0>, and all phases are fixed.
operation ApproxModExp(cfg : ModExpConfig, exponent : Qubit[], acc : Qubit[]) : Unit {
    // Q_dlog = qpu.alloc_quint(length=conf.len_dlog_accumulator)
    use dlog = Qubit[cfg.LenDlog];
    // loop1_vent = Lookup(np.zeros((conf.num_windows1, 1 << conf.window1), dtype=np.bool_))
    mutable vent1 = InitialVent1(cfg, Length(exponent));
    for i in 0..Length(cfg.Periods) - 1 {
        if not cfg.CacheBody or BeginEstimateCaching("approx_modexp_prime_iteration", 0) {
            set vent1 = PrimeIteration(cfg, i, exponent, dlog, acc, vent1);
            if cfg.CacheBody {
                EndEstimateCaching();
            }
        }
    }
    // Uncompute Q_dlog: loop1(..., i=len(conf.periods))
    set vent1 = Loop1(cfg, Length(cfg.Periods), exponent, dlog, vent1);
    // Q_dlog.del_by_equal_to(0): dlog is released here and must be |0>.
    // for j: qpu.z(loop1_vent[j, Q_exponent[j * w1:][:w1]])
    for j in 0..cfg.NumWindows1 - 1 {
        Phaseup(Window(exponent, j * cfg.W1, cfg.W1), vent1[j]);
    }
}

// ------------------------------------------------------------------------------------------------
// Entry points used by verify_small.py and count_full.py.

function MakeConfig(
    periods : Int[], lenDlog : Int, lenAcc : Int, maskBits : Int, trunc : Int,
    w1 : Int, w3a : Int, w3b : Int, w4 : Int, numInputQubits : Int,
    table1 : Int[][][], table3a : Int[][][][], table3b : Int[][][][], table3c : Int[][], table4 : Int[][][],
    synthetic : Bool, compareMode : Int, cacheBody : Bool
) : ModExpConfig {
    let ell = BitSizeI(periods[0]);
    new ModExpConfig {
        Periods = periods, LenDlog = lenDlog, LenAcc = lenAcc, MaskBits = maskBits, Trunc = trunc,
        W1 = w1, W3a = w3a, W3b = w3b, W4 = w4,
        NumWindows1 = (numInputQubits + w1 - 1) / w1,
        NumWindows3a = (ell + w3a - 1) / w3a,
        NumWindows3b = (ell + w3b - 1) / w3b,
        NumWindows4 = (ell + w4 - 1) / w4,
        Table1 = table1, Table3a = table3a, Table3b = table3b, Table3c = table3c, Table4 = table4,
        Synthetic = synthetic, CompareMode = compareMode, CacheBody = cacheBody,
    }
}

/// Basis-state run: exponent = e (given as little-endian bits, since m may exceed 63), mask = s.
/// Returns the measured Q_result and the measured exponent bits. Qubits other than the exponent and
/// Q_result are checked to be |0> by the simulator when released; the exponent must still read e.
operation RunBasis(cfg : ModExpConfig, eBits : Bool[], s : Int) : (Int, Bool[]) {
    use exponent = Qubit[Length(eBits)];
    use acc = Qubit[cfg.LenAcc + 1];
    ApplyPauliFromBitString(PauliX, true, eBits, exponent);
    ApplyXorInPlace(s, acc);
    ApproxModExp(cfg, exponent, acc);
    let r = MeasureInteger(acc);
    let eOut = ResultArrayAsBoolArray(MResetEachZ(exponent));
    (r, eOut)
}

/// Superposition run: exponent uniformly superposed over its 2^m values and Q_result masked over
/// [0, 2^maskBits). Dumps the final state (the caller checks it) and resets.
operation RunSuperposed(cfg : ModExpConfig, numInputQubits : Int) : Unit {
    use exponent = Qubit[numInputQubits];
    use acc = Qubit[cfg.LenAcc + 1];
    ApplyToEach(H, exponent);
    PrepareMask(cfg, acc);
    ApproxModExp(cfg, exponent, acc);
    Std.Diagnostics.DumpRegister(exponent + acc);
    ResetAll(exponent + acc);
}

/// Whole circuit for resource counting (mask prepared, exponent superposed).
operation CountFull(cfg : ModExpConfig, numInputQubits : Int) : Unit {
    use exponent = Qubit[numInputQubits];
    use acc = Qubit[cfg.LenAcc + 1];
    ApplyToEach(H, exponent);
    PrepareMask(cfg, acc);
    ApproxModExp(cfg, exponent, acc);
    ResetAll(exponent + acc);
}

/// One prime's iteration, stopped after stage `upto` (1 = loop1, 2 = +loop2, 3 = +loop3, 4 = +loop4,
/// 5 = +unloop3, 6 = +unloop2), for per-subroutine counts by differences. Stage 7 is the final
/// uncomputing loop1 plus the loop1-vent phaseups. Registers start in |0> (Toffoli counts don't
/// depend on the register values); everything is reset at the end.
operation CountStages(cfg : ModExpConfig, numInputQubits : Int, upto : Int) : Unit {
    use exponent = Qubit[numInputQubits];
    use acc = Qubit[cfg.LenAcc + 1];
    use dlog = Qubit[cfg.LenDlog];
    let i = 0;
    let p = cfg.Periods[i];
    let ell = BitSizeI(p);
    mutable vent1 = InitialVent1(cfg, numInputQubits);
    if upto == 7 {
        set vent1 = Loop1(cfg, Length(cfg.Periods), exponent, dlog, vent1);
        for j in 0..cfg.NumWindows1 - 1 {
            Phaseup(Window(exponent, j * cfg.W1, cfg.W1), vent1[j]);
        }
    } else {
        if upto >= 1 { set vent1 = Loop1(cfg, i, exponent, dlog, vent1); }
        if upto >= 2 { Loop2(dlog, p - 1, ell); }
        use residue = Qubit[ell + 1];
        if upto >= 3 {
            let info = Loop3(cfg, i, dlog[...ell - 1], residue);
            if upto >= 4 { Loop4(cfg, i, residue, acc); }
            if upto >= 5 { Unloop3(cfg, i, residue, dlog[...ell - 1], info); }
        }
        if upto >= 6 { Unloop2(dlog, p - 1, ell); }
        ResetAll(residue);
    }
    ResetAll(exponent + acc + dlog);
}
