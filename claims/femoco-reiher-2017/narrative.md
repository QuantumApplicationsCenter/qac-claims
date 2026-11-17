# Reproducing the FeMoCo resource estimate of Reiher et al. (2017)

*{{ review.prepared_by.0.name }}, {{ review.prepared_by.1.name }}, and {{ review.prepared_by.2.name }} ({{ review.prepared_by.0.affiliation }}), for the Quantum Applications Center, UW–Madison.*
*Numbers in this page are rendered from the claim record; the record's numbers come from the executed notebook in `reproductions/qdk-trotter-2026-11/`.*

## The claim

[Reiher et al. (2017)]({{ links[label=Publication (DOI)].url }}) gave the first detailed estimate of what it
would take to compute the ground-state energy of FeMoCo, the iron–molybdenum cofactor of nitrogenase, on a
quantum computer. Their active space, {{ assertion.workload.active_space_electrons }} electrons in
{{ assertion.workload.active_space_orbitals }} orbitals, became the standard benchmark for later algorithms.
Read literally, the paper claims:

> {{ headline }}

The algorithm is the simplest one available. The Hamiltonian is mapped to qubits with the Jordan–Wigner
transformation, its time evolution is approximated by second-order Trotter–Suzuki steps, and phase estimation
reads the energy from those steps. Two layers of numbers sit behind the claim.

**Logical counts.** For a total error of {{ assumptions_as_reported.target_precision.value | g }} Ha, with
rotations executed one at a time, Table 1 reports about {{ reported.figures.t_count.value | sci }} T gates and
{{ reported.figures.logical_qubits.value | n }} logical qubits. At one logical T gate every
{{ assumptions_as_reported.logical_t_gate_time.value }} ns that is {{ reported.figures.runtime_seconds.value | hours }}.
The preprint's appendices give the cost formula behind the T count (Eq. E2) and its inputs: a count of
{{ assumptions_as_reported.hamiltonian_terms.value | sci }} Hamiltonian terms, a Trotter number of
{{ assumptions_as_reported.trotter_number.value }} extrapolated from small molecules, and an average of
{{ assumptions_as_reported.synthesis_t_gates_slope.value }} log₂(1/ε) + {{ assumptions_as_reported.synthesis_t_gates_offset.value }}
T gates to synthesize a rotation to accuracy ε.

**Physical resources.** Table 2 adds the surface code, with physical gates of
{{ assumptions_as_reported.physical_gate_time.value }} ns and enough T factories to keep to the runtime of
Table 1. At a physical error rate of {{ assumptions_as_reported.physical_error_rate.value | sci }} it lists
{{ assumptions_as_reported.t_factories.value }} T factories, code distance
{{ reported.figures.code_distance.value }}, and about {{ reported.figures.physical_qubits.value | million }} physical
qubits; at an error rate of {{ reproductions.0.results.physical.1.architecture.physical_error_rate | sci }} the total falls to about
{{ assumptions_as_reported.physical_qubits_at_error_rate_1e_6.value | million }}.

## What QAC did

We rebuilt the estimate with [QDK Chemistry](https://github.com/microsoft/qdk-chemistry)
(version {{ reproductions.0.results.tooling.packages.qdk-chemistry }}) and the resource estimator in the
[QDK](https://github.com/microsoft/qdk) (version {{ reproductions.0.results.tooling.packages.qdk }}). The
[executed notebook](https://github.com/QuantumApplicationsCenter/qac-claims/blob/main/claims/femoco-reiher-2017/reproductions/qdk-trotter-2026-11/notebook.ipynb)
walks through every step.

**The paper's own Hamiltonian.** The integrals are the original structure-1 file of Reiher et al., which
Microsoft publishes with the first author's permission in
[qdk-chemistry-data](https://github.com/microsoft/qdk-chemistry-data/tree/main/data/hamiltonians/FeMoco-Reiher2017).
The notebook downloads it from a pinned commit and checks its SHA-256 digest. Unlike the registry's other
FeMoCo record, nothing here is synthetic.

**Pauli terms.** The cost of a Trotter step is set by the number of Pauli terms in the Jordan–Wigner
Hamiltonian. We count them with a closed form and check it against QDK Chemistry's qubit mapper, which returns
the same terms with the same coefficients on truncated active spaces of up to
{{ reproductions.0.results.diagnostics.largest_validated_active_space_orbitals | n }} orbitals. The full
Hamiltonian has {{ reproductions.0.results.logical.pauli_terms | n }} Pauli terms. That is
{{ reproductions.0.results.diagnostics.pauli_terms_over_source_term_count | x }} the
{{ assumptions_as_reported.hamiltonian_terms.value | sci }} terms the paper quotes. Discarding small terms does
not close the difference, and we could not determine how the paper's count was obtained.

**Rotations per Trotter step.** QDK Chemistry compiles a second-order Trotter step into one rotation per Pauli
exponential, and the notebook confirms the count on circuits compiled for the truncated active spaces. For
FeMoCo a step has {{ reproductions.0.results.logical.rotations_per_step | n }} rotations. The full circuit is
too large to compile on a laptop, so this figure follows from the term count and the rule checked on the smaller
circuits. Phase estimation is costed as in the paper's Lemma 2, which controls a step with Clifford gates and
adds no rotations.

**Trotter steps and T gates.** We then apply the paper's Eq. E2 with the paper's constants. The Trotter number
is the one input we take on trust: the paper extrapolates it from molecules small enough to simulate, and we
did not repeat that. The result is {{ reproductions.0.results.logical.walk_steps | n }} Trotter steps,
{{ reproductions.0.results.logical.rotation_count | sci }} rotations at
{{ reproductions.0.results.logical.t_states_per_rotation | g }} T gates each, and
{{ reproductions.0.figures.t_count.value | sci }} T gates in total, on
{{ reproductions.0.figures.logical_qubits.value | n }} logical qubits. At the paper's rate of one T gate per
{{ reproductions.0.results.inputs.trotter.logical_t_gate_time_ns }} ns that is
{{ reproductions.0.results.logical.runtime_seconds_at_logical_t_rate | hours }}.

**Physical resources.** The QDK resource estimator takes these logical counts with the paper's stated
assumptions (physical gates of {{ reproductions.0.results.physical.0.architecture.gate_time_ns }} ns, the surface
code, 15-to-1 distillation) and its own lattice-surgery model for the rest. At an error rate of
{{ reproductions.0.results.physical.0.architecture.physical_error_rate | sci }} it returns
{{ reproductions.0.figures.physical_qubits.value | million }} physical qubits
({{ reproductions.0.figures.physical_qubits.value | n }}) at code distance
{{ reproductions.0.figures.code_distance.value }}, with
{{ reproductions.0.results.diagnostics.t_factories_error_rate_1e_3 | n }} T factories, and a runtime of about
{{ reproductions.0.results.diagnostics.runtime_years_error_rate_1e_3 | n }} years. At an error rate of
{{ reproductions.0.results.physical.1.architecture.physical_error_rate | sci }} it returns
{{ reproductions.0.results.physical.1.physical_qubits | n }} physical qubits at distance
{{ reproductions.0.results.physical.1.code.distance }} and about
{{ reproductions.0.results.diagnostics.runtime_years_error_rate_1e_6 | n }} years.

## How to read the comparison

**The logical qubit count agrees.** We count {{ reproductions.0.figures.logical_qubits.value | n }} qubits from
the ingredients the paper names: the spin orbitals, one phase-estimation qubit, and one ancilla for rotation
synthesis. The paper lists {{ reported.figures.logical_qubits.value | n }} without a breakdown.

**The T count does not.** Ours is {{ comparisons[aspect=t_count].ratio | x }} the paper's. The notebook separates
the difference into two parts.

- *Rotations per step.* Using every Pauli term instead of the paper's term count raises the T count by
  {{ reproductions.0.results.diagnostics.t_count_over_source_formula_t_count | x }}.
- *The formula against the tables.* Eq. E2, evaluated with the paper's own term count and the constants of its
  Table IV, gives {{ reproductions.0.results.diagnostics.source_formula_t_count | sci }} T gates. Table 1 reports
  {{ reported.figures.t_count.value | sci }}. With the three errors added linearly, as in Table IV, the formula
  gives {{ reproductions.0.results.diagnostics.source_formula_t_count_sum_rule | sci }} against the table's
  {{ assumptions_as_reported.t_count_with_summed_error_budget.value | sci }}.

We did not find the cause of either part, and we did not change any input to make the numbers agree. The
second part does not involve our Hamiltonian or our tools: it compares the paper's formula with the paper's
tables. The paper's circuits and scripts are not public, so an unstated step in its calculation may account for
it.

**The physical figures differ in both directions, for one reason.** The paper sizes its machine to apply a
logical T gate every {{ assumptions_as_reported.logical_t_gate_time.value }} ns, which takes
{{ assumptions_as_reported.t_factories.value }} T factories, and those factories hold almost all of its qubits.
In the lattice-surgery model a T gate takes a logical cycle, here
{{ reproductions.0.results.diagnostics.logical_cycle_ns_error_rate_1e_3 | n }} ns. Far fewer factories keep up
at that pace, so our machine has {{ comparisons[aspect=physical_qubits].ratio | pctabs }} fewer qubits than the
paper's and runs about {{ comparisons[aspect=runtime_seconds].ratio | n }} times as long. The runtime ratio combines the
slower T gates with the larger T count. Neither figure tests the paper's Table 2, because the model is
different.

## What this does not show, and what comes next

- It does not show which of the paper's numbers is the source of the T-count difference. A count of the
  rotations in the paper's original circuits, or the script behind its Table IV, would settle it.
- It does not rebuild the Trotter number. A tighter or looser value would change the T count in proportion.
- It does not compile the full {{ assertion.workload.active_space_orbitals }}-orbital circuit; the largest compiled
  check uses {{ reproductions.0.results.diagnostics.largest_validated_active_space_orbitals | n }} orbitals.
- It does not reproduce the paper's surface-code model. A like-for-like physical comparison needs a model in
  which T gates are applied as fast as the paper assumes.
- It covers the serial ordering at {{ assumptions_as_reported.target_precision.value | g }} Ha only. Table 1 also
  gives a 1 mHa case and the nesting and PAR orderings, which are natural later variants.

## Reproducing this result

The [notebook](https://github.com/QuantumApplicationsCenter/qac-claims/blob/main/claims/femoco-reiher-2017/reproductions/qdk-trotter-2026-11/notebook.ipynb)
runs in about {{ reproductions.0.run.duration_seconds | n }} seconds on a laptop, in the environment pinned by
`requirements.lock.txt` (Python {{ reproductions.0.results.tooling.python }}). It downloads the integral file
on first use, so it needs a network connection. From a checkout of this repository:

```bash
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r claims/femoco-reiher-2017/reproductions/qdk-trotter-2026-11/requirements.lock.txt
pip install -e ".[execute]"
qacclaims execute claims/femoco-reiher-2017/reproductions/qdk-trotter-2026-11
```

The last command re-executes the notebook and reports any difference from the committed `results.json`.
