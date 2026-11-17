// Counting helper for rns_precompute.lookup_toffolis: one OptimizedLookup on an n-qubit address
// into a w-qubit target, everything reset afterwards.
operation LookupCost(data : Bool[][], n : Int, w : Int) : Unit {
    use address = Qubit[n];
    use target = Qubit[w];
    OptimizedLookup(data, address, target);
    ResetAll(address + target);
}
