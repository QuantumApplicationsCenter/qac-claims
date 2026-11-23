# Reproducing the FeMoCo THC resource model of Lee et al.

*Mahnoor and Stella, PlexTech (UC Berkeley). Draft for QAC review.*

## The claim

[The paper]({{ links[label=Paper version used].url }}) reports THC-based logical resources
and a separate space-optimized physical implementation for the Reiher FeMoCo active space.

> {{ headline }}

Table IV reports {{ reported.figures.logical_qubits.value | n }} logical qubits and
{{ reported.figures.toffoli_count.value | sci }} Toffolis. The physical layout instead uses
{{ assumptions_as_reported.layout_toffoli_count.value | sci }} Toffolis and reports about
{{ reported.figures.physical_qubits.value | million }} physical qubits and
{{ reported.figures.runtime_seconds.value | hours }} (Fig. 10 and p. 31).
These are different implementations and must not be interchanged.

The energy tolerance is {{ assumptions_as_reported.total_energy_tolerance.value | g }} Ha,
with {{ assumptions_as_reported.phase_estimation_error.value | g }} Ha allocated to phase estimation
and {{ assumptions_as_reported.hamiltonian_approximation_error.value | g }} Ha to Hamiltonian approximation
(Eq. (25), p. 14). Published molecular approximation settings are inputs to this reproduction.

## Logical counts

OpenFermion {{ reproductions[id=openfermion-thc-layout-2026-11].results.tooling.packages.openfermion }} produces
{{ reproductions[id=openfermion-thc-layout-2026-11].figures.logical_qubits.value | n }} logical qubits and
{{ reproductions[id=openfermion-thc-layout-2026-11].figures.toffoli_count.value | sci }} Toffolis for the table implementation.
Li at the requested rank {{ assumptions_as_reported.li_requested_rank.value }} gives
{{ reproductions[id=openfermion-thc-layout-2026-11].results.logical_variants.0.logical.num_qubits | n }} qubits and
{{ reproductions[id=openfermion-thc-layout-2026-11].results.logical_variants.0.logical.toffoli_count | sci }} Toffolis,
against Table V's {{ assumptions_as_reported.li_requested_logical_qubits.value | n }} and
{{ assumptions_as_reported.li_requested_toffoli_count.value | sci }}.
The recommended Li rank {{ assumptions_as_reported.li_recommended_rank.value }} remains separate:
{{ reproductions[id=openfermion-thc-layout-2026-11].results.logical_variants.1.logical.num_qubits | n }} qubits and
{{ reproductions[id=openfermion-thc-layout-2026-11].results.logical_variants.1.logical.toffoli_count | sci }} Toffolis.

## Reconstructing the physical resource model

OpenFermion's half-angle schedule reconstructs the Figure 11 subroutines from the
algorithm inputs, giving {{ reproductions[id=openfermion-thc-layout-2026-11].results.layout.stage_count | n }} stages,
{{ reproductions[id=openfermion-thc-layout-2026-11].results.layout.peak_data_qubits | n }} peak live data qubits,
and {{ reproductions[id=openfermion-thc-layout-2026-11].results.layout.toffolis_per_walk | n }} Toffolis per loop.
The paper's approximate per-loop value differs by a single operation; we retain the computed value.
Equation (45) gives {{ reproductions[id=openfermion-thc-layout-2026-11].results.layout.walk_steps | n }} loops, for
{{ reproductions[id=openfermion-thc-layout-2026-11].results.layout.toffoli_count | sci }} layout Toffolis.

The factory geometry, depth and CCZ error formulas follow the ancillary script cited as
Ref. 95 by Lee. Factory throughput is calculated from those formulas rather than imposed
as the paper's rounded output rate. The slower of factory supply and reaction time sets
the operation tick; a code-beat regime check is enforced for the QROM operations.

A custom QDK ISA gives each stage this derived duration and a failure bound from CCZ
distillation and nonfactory storage. QDK repeats the stage sequence and estimates its
resources. The complete published rectangular floorplan is reserved, including routing
and AutoCCZ fixup space. The data code distance remains an imposed input.

| Physical scenario | Paper qubits | Model qubits | Paper runtime | Model runtime |
| --- | ---: | ---: | --- | --- |
| Main | {{ reported.figures.physical_qubits.value | million }} | {{ reproductions[id=openfermion-thc-layout-2026-11].results.physical.0.physical_qubits | n }} | {{ reported.figures.runtime_seconds.value | hours }} | {{ reproductions[id=openfermion-thc-layout-2026-11].results.physical.0.runtime_seconds | hours }} |
| Optimistic error rate | About {{ assumptions_as_reported.optimistic_physical_qubits.value | million }} (p. 31) | {{ reproductions[id=openfermion-thc-layout-2026-11].results.physical.1.physical_qubits | n }} | About {{ assumptions_as_reported.optimistic_runtime.value | hours }} (p. 31) | {{ reproductions[id=openfermion-thc-layout-2026-11].results.physical.1.runtime_seconds | hours }} |

The main hardware failure union bound is {{ reproductions[id=openfermion-thc-layout-2026-11].results.physical.0.achieved_error | g }},
below the allowed {{ reproductions[id=openfermion-thc-layout-2026-11].results.physical.0.error_budget | g }}.
The optimistic case gives {{ reproductions[id=openfermion-thc-layout-2026-11].results.physical.1.achieved_error | g }}.
These use the cited phenomenological formulas, not experimentally established reliability.
The paper also later refers to {{ assumptions_as_reported.layout_runtime_alternative.value | hours }};
we retain that textual ambiguity without adjusting inputs to match it.

## What this establishes and what it does not

This is a resource-level reconstruction conditional on the paper's floorplan, distances
and error model. It reproduces the primary rounded resource figures closely and improves
substantially on the earlier aggregate serial-Toffoli proxy. The earlier exploratory version is archived outside the submission.

The calculation is not QDK Chemistry compiling a full gate-level THC circuit. QDK evaluates
our cited subroutine macro costs; it does not independently verify them. We do not prove
routability or optimize the footprint, revalidate chemical accuracy, determine trial-state
overlap, or independently select code distances. A routed Clifford trace, factory warmup,
initial-state preparation and finite-batch scheduling effects are outside this steady-state model.
Physical agreement therefore must not be described as experimental validation or quantum advantage.

## Reproducing the calculation

Python {{ reproductions[id=openfermion-thc-layout-2026-11].results.tooling.python }} and exact package versions are recorded with the executed
notebook. The recorded run took {{ reproductions[id=openfermion-thc-layout-2026-11].run.duration_seconds | n }} seconds on its recorded host.
With that environment activated:

```bash
python -m pip install -r claims/femoco-lee-2021/reproductions/openfermion-thc-layout-2026-11/requirements.lock.txt
python -m pip install -e ".[execute]"
qacclaims execute claims/femoco-lee-2021/reproductions/openfermion-thc-layout-2026-11
```

The final cell exports calculated values; `qacclaims validate` checks the schema. The package lockfile pins the implementation versions.
Gate inventories not determined by the analytic calculation are omitted. The schema extension and custom resource model await
maintainer review; reviewer and approver fields remain empty.
