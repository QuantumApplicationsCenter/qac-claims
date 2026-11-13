# Reproducing the FeMoCo 76-orbital resource estimate of Low et al. (2025)

*Davyn Paringkoan, PlexTech at UC Berkeley, building on the 54-orbital reproduction by Katerina Gratsea and Matthew Otten (Quantum Applications Center, UW–Madison).*
*Numbers in this page are rendered from the claim record; the record's numbers come from the executed notebook in `reproductions/qdk-sossa-2026-11/`.*

## The claim

[Low et al. (2025)]({{ links[label=Publication (DOI)].url }}) estimate the quantum resources needed to compute the ground-state
energy of FeMoCo in two active spaces. This record covers the larger one, the 76-orbital, 113-electron active
space of Li et al.; the 54-orbital (Reiher) active space from the same paper has its own record,
[femoco-low-2025](../femoco-low-2025/). FeMoCo, the iron–molybdenum cofactor of
nitrogenase, is a long-standing benchmark for quantum chemistry on quantum computers. Their algorithm combines
double-factorized tensor hypercontraction (DFTHC) with BLISS and sum-of-squares spectrum amplification.
Read literally, the paper claims:

> {{ headline }}

Two layers of numbers sit behind that sentence.

**Logical counts.** For a target precision of {{ assumptions_as_reported.target_precision.value | g }} Ha
(Table V), the circuit needs about {{ reported.figures.toffoli_count.value | sci }} Toffoli gates and
{{ reported.figures.logical_qubits.value | n }} logical qubits. These follow from explicit molecular tensors
that the authors factorized and optimized, with DFTHC hyper-parameters
R = {{ assumptions_as_reported.dfthc_rank_r.value }}, B = {{ assumptions_as_reported.dfthc_b.value }},
C = {{ assumptions_as_reported.dfthc_c.value }}, and bit precisions
b_coeff = {{ assumptions_as_reported.coefficient_bit_precision.value }} and
b_rot = {{ assumptions_as_reported.rotation_bit_precision.value }} (the pair listed for this active space in
their Table X and in the table on p. 38).

**Physical resources.** Assuming the error-correction model of their Ref. 7,
[Lee et al. (2021)](https://doi.org/10.1103/PRXQuantum.2.030305) (four CCZ factories, a
physical error rate of {{ assumptions_as_reported.physical_error_rate.value | sci }}, a surface-code cycle time of
{{ assumptions_as_reported.surface_code_cycle_time.value | sci }} s, a reaction time of
{{ assumptions_as_reported.reaction_time.value | sci }} s, and distance-{{ assumptions_as_reported.code_distance.value }}
surface-code patches), they arrive at about {{ reported.figures.physical_qubits.value | million }} physical qubits and
{{ reported.figures.runtime_seconds.value | hours }} (Section V, p. 14).

## What QAC did

We rebuilt the computation with [QDK Chemistry](https://github.com/microsoft/qdk-chemistry)
(version {{ reproductions.0.results.tooling.packages.qdk-chemistry }}), whose DFTHC implementation aims to
follow Low et al., and estimated physical resources with the resource estimator in the
[QDK](https://github.com/microsoft/qdk) (version {{ reproductions.0.results.tooling.packages.qdk }}).
The [executed notebook](https://github.com/QuantumApplicationsCenter/qac-claims/blob/main/claims/femoco-low-2025-li76/reproductions/qdk-sossa-2026-11/notebook.ipynb) walks through every step:
block encoding, spectrum amplification, the sum-of-squares qubit mapping, the circuit primitives, the
trial state, and finally logical and physical resource estimation.

**Synthetic tensors.** The library's resource-estimation path does not build FeMoCo's molecular tensors.
It generates random tensors *of the same dimensions* as the paper's optimized factorization
(R = {{ reproductions.0.results.inputs.hamiltonian.R }}, B = {{ reproductions.0.results.inputs.hamiltonian.B }},
C = {{ reproductions.0.results.inputs.hamiltonian.C }}, effective normalization
λ_eff = {{ reproductions.0.results.inputs.hamiltonian.lambda_eff }}, seed {{ reproductions.0.results.inputs.hamiltonian.seed }})
and the same bit precisions. This is a reasonable simplification for *counting* resources, because the
compiled circuit's complexity depends primarily on the tensor shapes rather than on the tensor values.
Finding a compact, accurate DFTHC representation is a hard numerical optimization that the paper has
already done. It also means this reproduction says nothing about FeMoCo's energies: the spectrum of a random
tensor is not the spectrum of nitrogenase.

**Logical counts.** The rebuilt circuit uses {{ reproductions.0.results.logical.walk_steps | n }} walk steps and comes out at
{{ reproductions.0.figures.toffoli_count.value | sci }} Toffoli gates and
{{ reproductions.0.figures.logical_qubits.value | n }} logical qubits, within
{{ comparisons[aspect=toffoli_count].ratio | pct }} and {{ comparisons[aspect=logical_qubits].ratio | pct }} of the paper's
figures. We read this as reproducing, and validating, the paper's logical resource estimates with an
independent implementation of the same algorithmic ingredients.

**Physical resources.** We then applied the physical assumptions the paper states (error rate
{{ reproductions.0.results.physical.1.architecture.physical_error_rate | sci }}, a
{{ reproductions.0.results.physical.1.code.cycle_time_ns }} ns surface-code cycle, and code distance
{{ reproductions.0.results.physical.1.code.distance }}), with a different logical architecture. The main
scenario uses four T factories following [Litinski (2019)](https://doi.org/10.22331/q-2019-12-02-205),
synthesizes arbitrary rotations with PSSPC ([Beverland et al.](https://arxiv.org/abs/2211.07629)),
maps operations to lattice-surgery instructions, and has no separate reaction time. Under these
assumptions the machine needs {{ reproductions.0.figures.physical_qubits.value | million }} physical qubits
({{ reproductions.0.figures.physical_qubits.value | n }}) and runs for
{{ reproductions.0.figures.runtime_seconds.value | hours }}. A second scenario, with the CCX factories of
[Gidney, Shutty, and Jones (2024)](https://arxiv.org/abs/2409.17595), gives
{{ reproductions.0.results.physical.0.physical_qubits | million }} qubits in the same time.

**What changed from the 54-orbital reproduction.** The 54-orbital notebook carried over by changing
only its inputs: the DFTHC dimensions, λ_eff, the bit precisions, and the electron count. One more
change was needed for the physical estimate. This circuit has about
{{ reproductions.0.results.logical.rotation_count | sci }} arbitrary rotations, and at the estimator's default
maximum of 20 T states per rotation the estimated failure probability exceeds the error budget of
{{ reproductions.0.results.physical.1.error_budget | g }} at every code distance and factory choice, which points to
rotation-synthesis error; no estimate exists in the default range. We let the estimator use up to 40 T states per rotation; the headline scenario then reaches a
total failure probability of {{ reproductions.0.results.physical.1.achieved_error | sci }} at the paper's
distance-{{ reproductions.0.results.physical.1.code.distance }} code. The 54-orbital record, with about a
fifth as many rotations, fits within the default range.

## How to read the comparison

The logical counts compare the same algorithm with the same hyper-parameters, and they agree to within
about {{ comparisons[aspect=toffoli_count].ratio | pctabs }}. The physical figures were computed with
different factory designs and timing models, so their ratios
({{ comparisons[aspect=physical_qubits].ratio | x }} for physical qubits and
{{ comparisons[aspect=runtime_seconds].ratio | x }} for runtime) include the effect of those choices.

## What this does not show, and what comes next

- It does not reproduce FeMoCo's chemistry: the tensors are synthetic, and the distance-{{ reproductions.0.results.physical.1.code.distance }}
  code was imposed as an input to match the paper rather than selected independently.
- Its rotation-synthesis cost is not the estimator's default: allowing more T states per rotation adds to
  the T-state demand on the factories, which the paper's own estimate does not need to account for in the same way.
- It does not reproduce the paper's physical estimate under the paper's own architecture. Low et al. use the
  QEC scheme of their Ref. 7, but the number of stored qubits, and therefore the surface-code patch size,
  appears to differ from the implementation shown in Fig. 10 of that reference. Once that information is
  available we plan to implement their logical architecture and QEC scheme in the same framework, which
  would make the physical-qubit and runtime comparison apples-to-apples.

## Reproducing this result

The [notebook](https://github.com/QuantumApplicationsCenter/qac-claims/blob/main/claims/femoco-low-2025-li76/reproductions/qdk-sossa-2026-11/notebook.ipynb) runs in about {{ reproductions.0.run.duration_seconds | n }} seconds on a laptop, in the
environment pinned by `requirements.lock.txt` (Python {{ reproductions.0.results.tooling.python }}).
From a checkout of this repository:

```bash
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r claims/femoco-low-2025-li76/reproductions/qdk-sossa-2026-11/requirements.lock.txt
pip install -e ".[execute]"
qacclaims execute claims/femoco-low-2025-li76/reproductions/qdk-sossa-2026-11
```

The last command re-executes the notebook and reports any difference from the committed `results.json`.
