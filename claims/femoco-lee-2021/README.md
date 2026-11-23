<!-- Rendered by `qacclaims build` from narrative.md. Edit narrative.md; this file is regenerated. -->

# Reproducing the FeMoCo THC resource model of Lee et al.

*Mahnoor and Stella, PlexTech (UC Berkeley). Draft for QAC review.*

## The claim

[The paper](https://arxiv.org/pdf/2011.03494v3) reports THC-based logical resources
and a separate space-optimized physical implementation for the Reiher FeMoCo active space.

> FeMoCo could be simulated with about four million physical qubits in under four days under the paper's hardware assumptions.

Table IV reports 2,142 logical qubits and
5.3 × 10⁹ Toffolis. The physical layout instead uses
6.7 × 10⁹ Toffolis and reports about
4 million physical qubits and
3 days (Fig. 10 and p. 31).
These are different implementations and must not be interchanged.

The energy tolerance is 0.0016 Ha,
with 0.001 Ha allocated to phase estimation
and 0.0006 Ha to Hamiltonian approximation
(Eq. (25), p. 14). Published molecular approximation settings are inputs to this reproduction.

## Logical counts

OpenFermion 1.7.1 produces
2,142 logical qubits and
5.25 × 10⁹ Toffolis for the table implementation.
Li at the requested rank 350 gives
2,194 qubits and
3.2 × 10¹⁰ Toffolis,
against Table V's 2,194 and
3.2 × 10¹⁰.
The recommended Li rank 450 remains separate:
2,196 qubits and
3.19 × 10¹⁰ Toffolis.

## Reconstructing the physical resource model

OpenFermion's half-angle schedule reconstructs the Figure 11 subroutines from the
algorithm inputs, giving 88 stages,
685 peak live data qubits,
and 13,881 Toffolis per loop.
The paper's approximate per-loop value differs by a single operation; we retain the computed value.
Equation (45) gives 481,135 loops, for
6.68 × 10⁹ layout Toffolis.

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
| Main | 4 million | 3,907,584 | 3 days | 3 days |
| Optimistic error rate | About 1 million (p. 31) | 976,896 | About 36 hours (p. 31) | 34.8 hours |

The main hardware failure union bound is 0.00438251,
below the allowed 0.01.
The optimistic case gives 0.00191886.
These use the cited phenomenological formulas, not experimentally established reliability.
The paper also later refers to 3.5 days;
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

Python 3.10.22 and exact package versions are recorded with the executed
notebook. The recorded run took 29 seconds on its recorded host.
With that environment activated:

```bash
python -m pip install -r claims/femoco-lee-2021/reproductions/openfermion-thc-layout-2026-11/requirements.lock.txt
python -m pip install -e ".[execute]"
qacclaims execute claims/femoco-lee-2021/reproductions/openfermion-thc-layout-2026-11
```

The final cell exports calculated values; `qacclaims validate` checks the schema. The package lockfile pins the implementation versions.
Gate inventories not determined by the analytic calculation are omitted. The schema extension and custom resource model await
maintainer review; reviewer and approver fields remain empty.
