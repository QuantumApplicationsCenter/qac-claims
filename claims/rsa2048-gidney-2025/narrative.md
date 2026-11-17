# Reproducing the RSA-2048 resource estimate of Gidney (2025)

*Davyn Paringkoan, PlexTech at UC Berkeley.*
*Numbers in this page are rendered from the claim record; the record's numbers come from the executed notebook in `reproductions/qsharp-modexp-qre-2026-11/`.*

## The claim

[Gidney (2025)]({{ links[label=Publication (arXiv)].url }}) estimates the cost of factoring a 2048-bit
RSA integer on a surface-code quantum computer, under the same physical assumptions as the earlier
[Gidney and Ekerå (2021)](https://doi.org/10.22331/q-2021-04-15-433) estimate of 20 million qubits.
Read literally, the paper claims:

> {{ headline }}

Two layers of numbers sit behind that sentence.

**Logical counts.** The algorithm does Ekerå–Håstad period finding with approximate residue
arithmetic, following [Chevignard, Fouque, and Schrottenloher (2024)](https://eprint.iacr.org/2024/222).
Nearly all of its work is additions, table lookups, and "phaseups", counted from a reference
implementation in Tables 3 and 4 of the paper. With the parameters the paper highlights for
RSA-2048 (s = {{ assumptions_as_reported.ekera_hastad_s.value }}, prime length
ℓ = {{ assumptions_as_reported.prime_bit_length.value }}, windows
w1 = {{ assumptions_as_reported.window_w1.value }}, w3 = {{ assumptions_as_reported.window_w3.value }},
w4 = {{ assumptions_as_reported.window_w4.value }}, accumulator length
f = {{ assumptions_as_reported.accumulator_length_f.value }}, and
m = {{ assumptions_as_reported.input_qubits_m.value | n }} input qubits), Table 5 gives
{{ reported.figures.logical_qubits.value | n }} logical qubits and
{{ reported.figures.toffoli_count.value | sci }} expected Toffoli gates per factoring, over an
expected {{ assumptions_as_reported.expected_shots.value | g }} shots.

**Physical resources.** The layout splits the machine into compute, hot storage, and cold storage.
Hot storage and compute use distance-{{ assumptions_as_reported.code_distance.value }} surface-code
patches ({{ assumptions_as_reported.hot_storage_physical_qubits_per_logical.value | n }} physical
qubits per logical qubit). Cold storage holds the idle input qubits in
[yoked surface codes](https://doi.org/10.1038/s41467-025-59714-1) at about
{{ assumptions_as_reported.cold_storage_physical_qubits_per_logical.value | n }} physical qubits per
logical qubit. {{ assumptions_as_reported.ccz_factories.value }} factories make Toffoli states with
[magic state cultivation](https://arxiv.org/abs/2409.17595) followed by 8T-to-CCZ distillation.
Section 3.2 adds this up to 897,864 physical qubits and 4.96 days, which the abstract reports as
fewer than {{ reported.figures.physical_qubits.value | million }} qubits and less than a week.

## What QAC did

The [notebook](https://github.com/QuantumApplicationsCenter/qac-claims/blob/main/claims/rsa2048-gidney-2025/reproductions/qsharp-modexp-qre-2026-11/notebook.ipynb)
builds the algorithm as a circuit, runs it on the real RSA-2048 instance, and rebuilds the paper's
physical model.

**The whole modular exponentiation as one circuit.** Appendix A.1 of the paper gives a reference
implementation of the algorithm, `approx_modexp`, as a sequence of additions, table lookups,
comparisons, and "phaseups" over seven subroutines. We built it operation for operation as one Q#
circuit (`modexp.qs`), including the phase corrections that measurement-based uncomputation of
lookups leaves behind. The lookups are the optimized ones the paper assumes (Appendix A.4: power
products of the two halves of the address, then one multi-target Toffoli per pair), and the phaseups
are the construction of Appendix A.3. Additions and comparisons use the library's version of the adder
Section 3.1 cites. On {{ reproductions.0.results.inputs.factoring.parameters.verified_instances }}
small instances, with 32-bit and 100-bit moduli, the circuit's output equals the paper's reference
implementation for every exponent tried, and every temporary qubit is released in |0⟩. With the
exponent and the mask in superposition, the final state matches the expected one amplitude by
amplitude, which only happens if every phase correction is right; a deliberately broken variant fails
the same check.

**The real instance.** The circuit needs a residue number system: small primes whose product is large
enough to hold the computation and, modulo N, almost zero (Eq. 17). We wrote our own version of the
paper's classical precomputation, checked that it rebuilds the published code's tables exactly on the
small instances, and used it to find a residue system for the RSA-2048 challenge number:
{{ reproductions.0.results.inputs.factoring.parameters.num_primes | n }} primes of
{{ assumptions_as_reported.prime_bit_length.value }} bits, slightly more than the paper's estimator
assumes. It then builds every lookup table the circuit uses on them, several hundred million entries.

**Logical counts.** We counted the circuit with the Table 5 parameters on those primes. Each prime's
iteration is traced once and accounted for every prime, and each lookup's Toffoli count is then
corrected to its real table, since a lookup saves a Toffoli wherever its table makes a pair of address
products irrelevant. Both steps are checked against Q#: on tens of thousands of real tables, and on whole
iterations built with real tables. One shot takes
{{ reproductions.0.results.logical.toffoli_count_per_shot | sci }} Toffolis and, over
{{ reproductions.0.results.logical.shots_expected | g }} expected shots, a factoring takes
{{ reproductions.0.figures.toffoli_count.value | sci }}, {{ comparisons[aspect=toffoli_count].ratio | x }}
the Table 5 value. The circuit's peak is {{ reproductions.0.figures.logical_qubits.value | n }} logical
qubits, {{ comparisons[aspect=logical_qubits].ratio | pctabs }} above Table 5, which counts only the
long-lived registers.

**The failed-shot rate.** Masking and approximate arithmetic make some shots fail. The paper bounds
the rate by S + ε/S (Eq. 43), where S is the masked fraction of the output and ε bounds the
approximation's error. Recomputed for the real residue system, the bound gives
{{ reproductions.0.results.inputs.factoring.parameters.deviant_shot_rate_percent | g }}%, the rate behind
Table 5's shot count. Running the approximate arithmetic on
{{ reproductions.0.results.inputs.factoring.parameters.sampled_exponents | n }} random exponents shows
its actual error is a nearly constant offset, at most
{{ reproductions.0.results.inputs.factoring.parameters.sampled_deviation_max | sci }} of N, well
inside the bound's {{ reproductions.0.results.inputs.factoring.parameters.deviation_bound_epsilon | sci }}.

**Physical resources: the paper's model, rebuilt.** Section 3.2 derives the physical cost from a
layout and a timing model, which we rebuilt as code (`physical_layout.py`) and applied to the circuit's
counts. Hot patches use distance {{ reproductions.0.figures.code_distance.value }}, the smallest that
reaches the paper's 10⁻¹⁵ per round under its Fig. 6 fit. The input register sits in yoked cold
storage. Every other qubit at the circuit's peak is hot, next to a compute region of six
cultivation-plus-distillation factories and workspace. The model checks the paper's 150 rounds per CCZ
state and its per-operation duration bounds against the circuit's largest operations. It then
multiplies those bounds by the circuit's
{{ reproductions.0.results.inputs.factoring.parameters.additions_per_shot | million }} additions,
{{ reproductions.0.results.inputs.factoring.parameters.lookups_per_shot | million }} lookups, and
{{ reproductions.0.results.inputs.factoring.parameters.phaseups_per_shot | million }} phaseups per shot.
The result is {{ reproductions.0.figures.physical_qubits.value | n }} physical qubits,
{{ reproductions.0.results.physical.0.runtime_seconds_per_shot | hours }} per shot, and
{{ reproductions.0.figures.runtime_seconds.value | hours }} per factoring.

**An independent check.** The resource estimator in the [QDK](https://github.com/microsoft/qdk)
(version {{ reproductions.0.results.tooling.packages.qdk }}) costs the same counts with its own
cultivation, factory, and yoked-storage models, chooses its own distances, and uses its own timing. It
needs {{ reproductions.0.results.physical.1.physical_qubits | million }} physical qubits and
{{ reproductions.0.results.physical.1.runtime_seconds | hours }}. Without yoked storage, keeping every
qubit in ordinary surface-code patches, it needs
{{ reproductions.0.results.physical.2.physical_qubits | million }}.

## How to read the comparison

The Toffoli count agrees with Table 5 to a fraction of a percent
({{ comparisons[aspect=toffoli_count].ratio | x }}), and the peak qubit count is
{{ comparisons[aspect=logical_qubits].ratio | pctabs }} higher because it includes temporary qubits.
The paper reports its physical cost as bounds, fewer than
{{ reported.figures.physical_qubits.value | million }} qubits and less than a week, and the rebuilt
model falls inside both, at {{ comparisons[aspect=physical_qubits].ratio | x }} and
{{ comparisons[aspect=runtime_seconds].ratio | x }} of the bounds.

Two details differ from Section 3.2's own numbers. The rebuilt layout needs more qubits than the
paper's 897,864, because the built circuit's peak holds more hot qubits than Section 3.2 counts, so it
uses part of the hundred thousand qubits of slack the paper adds before rounding to a million. And it
runs faster than the paper's 12.07 hours per shot: the paper's own durations applied to the circuit's
operation counts give {{ reproductions.0.results.physical.0.runtime_seconds_per_shot | hours }}. The
paper's published estimator gives a similar figure for the Table 5 row, so the 12.07 hours looks like it
came from a different parameter set.

## What this does not show, and what comes next

- The physical model takes its component figures from the work the paper cites, as the paper does:
  the storage fits of Fig. 6, the cost of magic state cultivation, and the 8T-to-CCZ factory. They are
  not re-simulated here.
- The physical claim depends on yoked storage: without it, the estimator needs several times more
  qubits. Section 3.2 leaves detailed simulation of cold storage under the algorithm's workload as
  future work, and so does this reproduction.
- The failed-shot rate keeps the paper's assumption that a mask covering a fraction S of the output
  costs about a fraction S of shots (Assumption 2). The approximation's own error is measured, but
  masked period finding is not simulated at this size.

The small test instances were generated with the paper's published code and data on
[Zenodo]({{ links[label=Code and assets (Zenodo)].url }}) (CC BY 4.0): its precomputation and the
outputs of its reference implementation. They check the circuit and our own precomputation; the
full-size work does not use the published code.

## Reproducing this result

The [notebook](https://github.com/QuantumApplicationsCenter/qac-claims/blob/main/claims/rsa2048-gidney-2025/reproductions/qsharp-modexp-qre-2026-11/notebook.ipynb) runs in about {{ reproductions.0.run.duration_seconds | n }} seconds on an 11-core laptop, in the
environment pinned by `requirements.lock.txt` (Python {{ reproductions.0.results.tooling.python }}).
From a checkout of this repository:

```bash
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r claims/rsa2048-gidney-2025/reproductions/qsharp-modexp-qre-2026-11/requirements.lock.txt
pip install -e ".[execute]"
qacclaims execute claims/rsa2048-gidney-2025/reproductions/qsharp-modexp-qre-2026-11
```

The last command re-executes the notebook and reports any difference from the committed `results.json`.
