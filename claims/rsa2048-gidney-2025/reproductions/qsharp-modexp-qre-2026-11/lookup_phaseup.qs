// Lookups, phaseups, and measurement-based uncomputation for Gidney (2025), Appendices A.3 and A.4.
//
// Conventions: registers are little-endian (address[0] is the least significant bit); a table over an
// n-qubit address is indexed by the address's integer value; a Bool[][] table has one row per address
// and one column per output qubit.

import Std.Arrays.*;
import Std.Math.*;
import Std.Measurement.*;

/// EXOR (Reed-Muller) coefficients of a truth table: coefficient s says whether the monomial
/// prod_{j in s} a_j appears in the table's polynomial over GF(2).
function ExorTransform(table : Bool[]) : Bool[] {
    let size = Length(table);
    mutable c = table;
    mutable step = 1;
    while step < size {
        for i in 0..size - 1 {
            if (i &&& step) != 0 {
                set c w/= i <- c[i] != c[i - step];
            }
        }
        set step *= 2;
    }
    c
}

/// Power product of a register: index s (1..2^k-1) holds the product of the qubits in subset s.
/// Singletons are the register's own qubits; every larger subset costs one AND into a fresh ancilla.
/// Planned classically so the quantum part is a loop that Q# can reverse.
function PowerProductPlan(qs : Qubit[], anc : Qubit[]) : (Qubit[], (Qubit, Qubit, Qubit)[]) {
    let k = Length(qs);
    if k == 0 {
        return ([], []);
    }
    mutable used = 0;
    mutable prod = [qs[0], size = 1 <<< k];
    mutable ands = [];
    for s in 1..(1 <<< k) - 1 {
        let hb = BitSizeI(s) - 1;
        let rest = s - (1 <<< hb);
        if rest == 0 {
            set prod w/= s <- qs[hb];
        } else {
            set ands += [(prod[rest], qs[hb], anc[used])];
            set prod w/= s <- anc[used];
            set used += 1;
        }
    }
    (prod, ands)
}

function PowerProductAncillaCount(k : Int) : Int {
    k == 0 ? 0 | (1 <<< k) - k - 1
}

operation ApplyAnds(ands : (Qubit, Qubit, Qubit)[]) : Unit is Adj {
    for (a, b, t) in ands {
        AND(a, b, t);
    }
}

/// Phaseup (Appendix A.3): negate the amplitude of every address k with table[k] set.
/// Costs (2^lo - lo - 1) + (2^hi - hi - 1) Toffolis, lo = n/2 and hi = n - n/2.
operation Phaseup(address : Qubit[], table : Bool[]) : Unit {
    let n = Length(address);
    let lo = n / 2;
    let coefficients = ExorTransform(table);
    let low = address[...lo - 1];
    let high = address[lo...];
    use ancLow = Qubit[PowerProductAncillaCount(Length(low))];
    use ancHigh = Qubit[PowerProductAncillaCount(Length(high))];
    let (lp, lowAnds) = PowerProductPlan(low, ancLow);
    let (hp, highAnds) = PowerProductPlan(high, ancHigh);
    within {
        ApplyAnds(lowAnds);
        ApplyAnds(highAnds);
    } apply {
        for s in 1..Length(coefficients) - 1 {
            if coefficients[s] {
                let sl = s &&& ((1 <<< lo) - 1);
                let sh = s >>> lo;
                if sh == 0 {
                    Z(lp[sl]);
                } elif sl == 0 {
                    Z(hp[sh]);
                } else {
                    CZ(hp[sh], lp[sl]);
                }
            }
        }
    }
}

/// Lookup (Appendix A.4): XOR data[address] into target.
/// Power products of the two halves of the address, then one multi-target Toffoli per pair of
/// non-trivial products (pairs involving the empty product are CNOT fan-outs), then measurement-based
/// uncomputation of every ancilla. Costs 2^n - n - 1 Toffolis when every pair has a non-zero mask.
operation OptimizedLookup(data : Bool[][], address : Qubit[], target : Qubit[]) : Unit {
    let n = Length(address);
    let w = Length(target);
    let lo = n / 2;
    // masks[s][b]: does monomial s appear in output bit b's polynomial?
    mutable masks = [[false, size = w], size = 1 <<< n];
    for b in 0..w - 1 {
        let column = ExorTransform(Mapped(row -> row[b], data));
        for s in 0..(1 <<< n) - 1 {
            if column[s] {
                set masks w/= s <- (masks[s] w/ b <- true);
            }
        }
    }
    let low = address[...lo - 1];
    let high = address[lo...];
    use ancLow = Qubit[PowerProductAncillaCount(Length(low))];
    use ancHigh = Qubit[PowerProductAncillaCount(Length(high))];
    let (lp, lowAnds) = PowerProductPlan(low, ancLow);
    let (hp, highAnds) = PowerProductPlan(high, ancHigh);
    within {
        ApplyAnds(lowAnds);
        ApplyAnds(highAnds);
    } apply {
        for s in 0..(1 <<< n) - 1 {
            let targets = Subarray(Where(x -> x, masks[s]), target);
            if Length(targets) > 0 {
                let sl = s &&& ((1 <<< lo) - 1);
                let sh = s >>> lo;
                if s == 0 {
                    ApplyToEach(X, targets);
                } elif sh == 0 {
                    for t in targets { CNOT(lp[sl], t); }
                } elif sl == 0 {
                    for t in targets { CNOT(hp[sh], t); }
                } else {
                    use anc = Qubit();
                    within {
                        AND(hp[sh], lp[sl], anc);
                    } apply {
                        for t in targets { CNOT(anc, t); }
                    }
                }
            }
        }
    }
}

/// Measurement-based uncomputation, first half: measure every qubit in the X basis and reset it.
/// Returns the outcomes; a True outcome means the qubit's value kicked back a phase.
operation MeasureXAndReset(qs : Qubit[]) : Bool[] {
    mutable outcomes = [];
    for q in qs {
        set outcomes += [MResetX(q) == One];
    }
    outcomes
}

/// Phase corrections owed after X-measuring a register that held data[address]:
/// address k needs a phase flip when data[k] and the outcomes overlap in an odd number of bits.
function PhaseTableFromMx(data : Bool[][], outcomes : Bool[]) : Bool[] {
    mutable table = [];
    for row in data {
        mutable parity = false;
        for b in 0..Length(row) - 1 {
            if row[b] and outcomes[b] {
                set parity = not parity;
            }
        }
        set table += [parity];
    }
    table
}

/// XOR of two phase tables (for merging deferred corrections, the paper's "vents").
function XorTables(a : Bool[], b : Bool[]) : Bool[] {
    mutable c = [];
    for i in 0..Length(a) - 1 {
        set c += [a[i] != b[i]];
    }
    c
}
