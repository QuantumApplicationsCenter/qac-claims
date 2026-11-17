"""The physical layout and runtime model of Gidney (2025), Sec. 3.2 (pp. 18-20), rebuilt as code.

Every constant below is the paper's, with its locator. The model takes the circuit's own logical
counts (peak qubits, operations per shot by kind) and derives, the way Sec. 3.2 does:

- the hot-storage code distance, from the Fig. 6 fit for ordinary surface-code patches;
- the CCZ factory period, from magic state cultivation's spacetime volume ([GSJ24] Fig. 1) and the
  8T-to-CCZ factory's lattice surgery ([GSJ24] Fig. 24), rounded up to the paper's 150 rounds;
- upper bounds on the duration of each operation, from the CCZ period and the largest operation
  of each kind that the circuit performs, rounded up to the paper's 2 ms / 2 ms / 1 ms;
- the physical qubits of cold storage (input register), hot storage (everything else at the
  circuit's peak), and the compute region (factories and lattice-surgery workspace);
- the chance a shot has no logical error, and the expected runtime of a factoring.
"""
from __future__ import annotations

import math

# --- Assumptions (abstract, p. 1; Sec. 3.2, p. 20) ----------------------------------------------
PHYSICAL_ERROR_RATE = 1e-3            # uniform depolarizing noise, 1 error per 1000 gates
CYCLE_TIME_US = 1.0                   # surface code cycle time
REACTION_TIME_US = 10.0               # control system reaction time (stated; bounded by the per-op slack)
TARGET_ERROR_PER_QUBIT_ROUND = 1e-15  # Sec. 3.2, p. 18

# --- Fig. 6 (p. 19) -----------------------------------------------------------------------------
def hot_patch_error_per_round(d: int) -> float:
    """Fig. 6 fit for ordinary surface-code patches: p_L ~ r * n * 3.5^-d / 40, with r = n = 1."""
    return 3.5 ** (-d) / 40


def hot_distance(target: float = TARGET_ERROR_PER_QUBIT_ROUND) -> int:
    d = 3
    while hot_patch_error_per_round(d) > target:
        d += 2 if d % 2 else 1
    # The paper uses the smallest d meeting the target; Fig. 6 steps through every integer d.
    while d > 3 and hot_patch_error_per_round(d - 1) <= target:
        d -= 1
    return d


def hot_qubits_per_logical(d: int) -> int:
    """Sec. 3.2, p. 18: 2(d + 1)^2 physical qubits per hot logical qubit."""
    return 2 * (d + 1) ** 2


COLD_QUBITS_PER_LOGICAL = 430  # Fig. 6 (2D-yoked surface codes at 1e-15 per round), Sec. 3.2, p. 18

# --- Compute region (Sec. 3.2, pp. 18-20) --------------------------------------------------------
COMPUTE_REGION_PATCHES = (7, 18)      # "a 7x18 region of hot patches"
FACTORY_COUNT = 6
FACTORY_PATCHES = (3, 4)              # each factory covers a 3x4 area of hot patches
WORKSPACE_COLUMNS = 3

# --- Factory timing (Sec. 3.2, p. 20) -----------------------------------------------------------
CULTIVATION_VOLUME_QUBIT_ROUNDS = 30000   # [GSJ24] Fig. 1, T state at 1e-7 logical error
T_STATES_PER_CCZ = 8
FACTORY_SURGERY_LAYERS = 6                # [GSJ24] Fig. 24
TEMPORAL_ENCODING_FACTOR = 2 / 3          # temporally encoded lattice surgery [CC22]
CCZ_ROUNDS_WITH_SLACK = 150               # "which I round up to 150 rounds for slack"
CULTIVATED_T_ERROR = 1e-7
DISTILLATION_SUPPRESSION = 28             # 8T-to-CCZ: 28 p^2 [Jon13]

# --- Operation durations (Sec. 3.2, p. 20): bounds rounded up for slack ---------------------------
ADDITION_MS, LOOKUP_MS, PHASEUP_MS = 2.0, 2.0, 1.0


def layout(*, input_qubits: int, peak_logical_qubits: int, additions_per_shot: float,
           lookups_per_shot: float, phaseups_per_shot: float, shots: float,
           largest_adder_toffolis: int, largest_lookup_address_bits: int,
           largest_phaseup_toffolis: int) -> dict:
    d = hot_distance()
    hot_rate = hot_qubits_per_logical(d)

    # Factory: cultivation time per CCZ, plus lattice surgery, versus the 150-round budget.
    factory_qubits_each = FACTORY_PATCHES[0] * FACTORY_PATCHES[1] * hot_rate
    cultivation_rounds = T_STATES_PER_CCZ * CULTIVATION_VOLUME_QUBIT_ROUNDS / factory_qubits_each
    surgery_rounds = FACTORY_SURGERY_LAYERS * TEMPORAL_ENCODING_FACTOR * d
    ccz_rounds = cultivation_rounds + surgery_rounds
    assert ccz_rounds <= CCZ_ROUNDS_WITH_SLACK
    ccz_period_us = CCZ_ROUNDS_WITH_SLACK / FACTORY_COUNT * CYCLE_TIME_US
    surgery_period_us = d * CYCLE_TIME_US
    ccz_error = DISTILLATION_SUPPRESSION * CULTIVATED_T_ERROR ** 2

    # Duration bounds from the largest operation of each kind in the circuit.
    step_us = max(ccz_period_us, surgery_period_us)
    adder_bound_ms = 2 * largest_adder_toffolis * step_us / 1000          # compute, then uncompute
    lookup_bound_ms = ((1 << largest_lookup_address_bits) - 1) * step_us / 1000  # 2^a - 1 surgery layers
    phaseup_bound_ms = 2 * largest_phaseup_toffolis * step_us / 1000
    assert adder_bound_ms <= ADDITION_MS and lookup_bound_ms <= LOOKUP_MS and phaseup_bound_ms <= PHASEUP_MS

    seconds_per_shot = (additions_per_shot * ADDITION_MS + lookups_per_shot * LOOKUP_MS
                        + phaseups_per_shot * PHASEUP_MS) / 1000

    # Space.
    rows, cols = COMPUTE_REGION_PATCHES
    compute_patches = rows * cols
    assert FACTORY_COUNT * FACTORY_PATCHES[0] * FACTORY_PATCHES[1] + WORKSPACE_COLUMNS * cols == compute_patches
    hot_logical = peak_logical_qubits - input_qubits
    cold_physical = input_qubits * COLD_QUBITS_PER_LOGICAL
    hot_physical = hot_logical * hot_rate
    factory_physical = FACTORY_COUNT * factory_qubits_each
    workspace_physical = (compute_patches - FACTORY_COUNT * FACTORY_PATCHES[0] * FACTORY_PATCHES[1]) * hot_rate
    physical = cold_physical + hot_physical + factory_physical + workspace_physical

    # Logical errors: every logical patch (cold, hot, compute) protected at the target per round.
    logical_patches = input_qubits + hot_logical + compute_patches
    qubit_rounds = logical_patches * seconds_per_shot * 1e6 / CYCLE_TIME_US
    p_no_error = math.exp(qubit_rounds * math.log1p(-TARGET_ERROR_PER_QUBIT_ROUND))
    runtime_seconds = seconds_per_shot * shots / p_no_error

    return dict(
        code_distance=d, hot_patch_error_per_round=hot_patch_error_per_round(d),
        hot_qubits_per_logical=hot_rate, cold_qubits_per_logical=COLD_QUBITS_PER_LOGICAL,
        cultivation_rounds_per_ccz=cultivation_rounds, surgery_rounds_per_ccz=surgery_rounds,
        ccz_rounds=ccz_rounds, ccz_period_us=ccz_period_us, ccz_error=ccz_error,
        adder_bound_ms=adder_bound_ms, lookup_bound_ms=lookup_bound_ms, phaseup_bound_ms=phaseup_bound_ms,
        seconds_per_shot=seconds_per_shot, hot_logical_qubits=hot_logical, logical_patches=logical_patches,
        cold_physical=cold_physical, hot_physical=hot_physical, factory_physical=factory_physical,
        workspace_physical=workspace_physical, physical_qubits=physical,
        qubit_rounds_per_shot=qubit_rounds, p_no_logical_error=p_no_error,
        runtime_seconds=runtime_seconds,
    )


if __name__ == "__main__":
    # The paper's own inputs (Sec. 3.2, p. 18): 131 hot logical qubits (it states 1409 = m + 131),
    # which with the rest of the layout gives its 897,864 physical qubits.
    paper = layout(input_qubits=1280, peak_logical_qubits=1280 + 131, additions_per_shot=1, lookups_per_shot=0,
                   phaseups_per_shot=0, shots=9.1, largest_adder_toffolis=32,
                   largest_lookup_address_bits=6, largest_phaseup_toffolis=8)
    assert paper["physical_qubits"] == 897864 and paper["code_distance"] == 25
    print("paper layout reproduced: d", paper["code_distance"], "physical", paper["physical_qubits"],
          "CCZ rounds", round(paper["ccz_rounds"], 1), "(paper: 114.7, rounded up to 150)")
