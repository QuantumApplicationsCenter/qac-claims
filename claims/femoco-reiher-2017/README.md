<!-- Rendered by `qacclaims build` from narrative.md. Edit narrative.md; this file is regenerated. -->

# Reproducing the FeMoCo resource estimate of Reiher et al. (2017)

*Yash Kumar, Jolin Wang, and Daniel Ng (PlexTech, UC Berkeley), for the Quantum Applications Center, UW–Madison.*
*Numbers in this page are rendered from the claim record; the record's numbers come from the executed notebook in `reproductions/qdk-trotter-2026-11/`.*

## The claim

[Reiher et al. (2017)](https://doi.org/10.1073/pnas.1619152114) gave the first detailed estimate of what it
would take to compute the ground-state energy of FeMoCo, the iron–molybdenum cofactor of nitrogenase, on a
quantum computer. Their active space, 54 electrons in
54 orbitals, became the standard benchmark for later algorithms.
Read literally, the paper claims:

> FeMoCo's ground-state energy could be computed to 0.1 mHa in about 130 days with 111 logical qubits and 1.1 × 10¹⁵ T gates, or about 180 million physical qubits at a 10⁻³ error rate.

The algorithm is the simplest one available. The Hamiltonian is mapped to qubits with the Jordan–Wigner
transformation, its time evolution is approximated by second-order Trotter–Suzuki steps, and phase estimation
reads the energy from those steps. Two layers of numbers sit behind the claim.

**Logical counts.** For a total error of 0.0001 Ha, with
rotations executed one at a time, Table 1 reports about 1.1 × 10¹⁵ T gates and
111 logical qubits. At one logical T gate every
10 ns that is 130 days.
The preprint's appendices give the cost formula behind the T count (Eq. E2) and its inputs: a count of
6.1 × 10⁶ Hamiltonian terms, a Trotter number of
166 extrapolated from small molecules, and an average of
1.15 log₂(1/ε) + 9.2
T gates to synthesize a rotation to accuracy ε.

**Physical resources.** Table 2 adds the surface code, with physical gates of
10 ns and enough T factories to keep to the runtime of
Table 1. At a physical error rate of 1 × 10⁻³ it lists
202 T factories, code distance
35, and about 180 million physical
qubits; at an error rate of 1 × 10⁻⁶ the total falls to about
1.2 million.

## What QAC did

We rebuilt the estimate with [QDK Chemistry](https://github.com/microsoft/qdk-chemistry)
(version 2.3.0) and the resource estimator in the
[QDK](https://github.com/microsoft/qdk) (version 1.33.1). The
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
8 orbitals. The full
Hamiltonian has 12,604,410 Pauli terms. That is
2.1× the
6.1 × 10⁶ terms the paper quotes. Discarding small terms does
not close the difference, and we could not determine how the paper's count was obtained.

**Rotations per Trotter step.** QDK Chemistry compiles a second-order Trotter step into one rotation per Pauli
exponential, and the notebook confirms the count on circuits compiled for the truncated active spaces. For
FeMoCo a step has 25,208,819 rotations. The full circuit is
too large to compile on a laptop, so this figure follows from the term count and the rule checked on the smaller
circuits. Phase estimation is costed as in the paper's Lemma 2, which controls a step with Clifford gates and
adds no rotations.

**Trotter steps and T gates.** We then apply the paper's Eq. E2 with the paper's constants. The Trotter number
is the one input we take on trust: the paper extrapolates it from molecules small enough to simulate, and we
did not repeat that. The result is 6,861,089 Trotter steps,
1.73 × 10¹⁴ rotations at
65.886 T gates each, and
1.14 × 10¹⁶ T gates in total, on
110 logical qubits. At the paper's rate of one T gate per
10 ns that is
1318.9 days.

**Physical resources.** The QDK resource estimator takes these logical counts with the paper's stated
assumptions (physical gates of 10 ns, the surface
code, 15-to-1 distillation) and its own lattice-surgery model for the rest. At an error rate of
1 × 10⁻³ it returns
2.72 million physical qubits
(2,721,009) at code distance
39, with
15 T factories, and a runtime of about
449 years. At an error rate of
1 × 10⁻⁶ it returns
181,529 physical qubits at distance
9 and about
104 years.

## How to read the comparison

**The logical qubit count agrees.** We count 110 qubits from
the ingredients the paper names: the spin orbitals, one phase-estimation qubit, and one ancilla for rotation
synthesis. The paper lists 111 without a breakdown.

**The T count does not.** Ours is 10.4× the paper's. The notebook separates
the difference into two parts.

- *Rotations per step.* Using every Pauli term instead of the paper's term count raises the T count by
  2.1×.
- *The formula against the tables.* Eq. E2, evaluated with the paper's own term count and the constants of its
  Table IV, gives 5.41 × 10¹⁵ T gates. Table 1 reports
  1.1 × 10¹⁵. With the three errors added linearly, as in Table IV, the formula
  gives 5.74 × 10¹⁵ against the table's
  1.2 × 10¹⁵.

We did not find the cause of either part, and we did not change any input to make the numbers agree. The
second part does not involve our Hamiltonian or our tools: it compares the paper's formula with the paper's
tables. The paper's circuits and scripts are not public, so an unstated step in its calculation may account for
it.

**The physical figures differ in both directions, for one reason.** The paper sizes its machine to apply a
logical T gate every 10 ns, which takes
202 T factories, and those factories hold almost all of its qubits.
In the lattice-surgery model a T gate takes a logical cycle, here
2,340 ns. Far fewer factories keep up
at that pace, so our machine has 98% fewer qubits than the
paper's and runs about 1,261 times as long. The runtime ratio combines the
slower T gates with the larger T count. Neither figure tests the paper's Table 2, because the model is
different.

## What this does not show, and what comes next

- It does not show which of the paper's numbers is the source of the T-count difference. A count of the
  rotations in the paper's original circuits, or the script behind its Table IV, would settle it.
- It does not rebuild the Trotter number. A tighter or looser value would change the T count in proportion.
- It does not compile the full 54-orbital circuit; the largest compiled
  check uses 8 orbitals.
- It does not reproduce the paper's surface-code model. A like-for-like physical comparison needs a model in
  which T gates are applied as fast as the paper assumes.
- It covers the serial ordering at 0.0001 Ha only. Table 1 also
  gives a 1 mHa case and the nesting and PAR orderings, which are natural later variants.

## Reproducing this result

The [notebook](https://github.com/QuantumApplicationsCenter/qac-claims/blob/main/claims/femoco-reiher-2017/reproductions/qdk-trotter-2026-11/notebook.ipynb)
runs in about 31 seconds on a laptop, in the environment pinned by
`requirements.lock.txt` (Python 3.10.22). It downloads the integral file
on first use, so it needs a network connection. From a checkout of this repository:

```bash
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r claims/femoco-reiher-2017/reproductions/qdk-trotter-2026-11/requirements.lock.txt
pip install -e ".[execute]"
qacclaims execute claims/femoco-reiher-2017/reproductions/qdk-trotter-2026-11
```

The last command re-executes the notebook and reports any difference from the committed `results.json`.
