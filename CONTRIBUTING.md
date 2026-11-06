# Contributing a claim or a reproduction

Everything in this repository is public and licensed for reuse (data CC BY 4.0, code MIT).
Do not add anything you would not want quoted.

## Adding a claim

1. Open an issue first describing the claim and the source; agree on the slug (`<workload>-<firstauthor>-<year>`).
2. Create `claims/<slug>/claim.yaml` and `claims/<slug>/estimates/reported.yaml`.
   Every reported figure needs a `locator` (section, page, table) into the source.
   Use `qualifier: rounded|approximate|upper_bound|lower_bound` when the source does.
3. Run `qacclaims validate --online` until it is clean.

## Adding a reproduction

1. Put the code at `claims/<slug>/reproductions/<repro-id>/`, as either `notebook.ipynb` or
   `reproduce.py` (not both). It must write `results.json` matching `schemas/results.schema.json`,
   with `producer.entrypoint` naming the file. A notebook is a good choice when the reproduction
   should also explain the method; tag its final cell `results-export`. A script is fine otherwise.
2. In a fresh environment with the Python version and exact package pins the reproduction needs, run
   `qacclaims execute claims/<slug>/reproductions/<repro-id> --write --refresh-lock --operator "Your Name"`.
   This commits `results.json`, `requirements.lock.txt`, `run.json`, and, for a notebook, the executed copy.
3. Write `claims/<slug>/estimates/reproduction-<repro-id>.yaml`: tool, headline scenario,
   `figure_map` pointers into `results.json`, every deviation from the source's assumptions,
   and the interpretation. **This file may not contain numbers** — the validator rejects them.
4. Update `assessment` in `claim.yaml` (status, findings, plain-language summary).
5. Write or update `narrative.md`: the explanation a reader or student needs — what the paper claims,
   what you did and why, how to read the comparison, what it does not show, how to reproduce.
   Write numbers as placeholders (`{{ reported.figures.logical_qubits.value | n }}`,
   `{{ comparisons[aspect=runtime_seconds].ratio | x }}`); filters: `n`, `sci`, `million`, `hours`, `x`, `pct`, `pctabs`, `g`.
   Never edit `README.md` by hand — it is rendered from `narrative.md`.
6. `qacclaims build` (renders `README.md`, regenerates `dist/`) and commit both.

## Publishing

`publication.status: published` requires `review.reviewed_by`, `review.approved_by`, and
`publication.first_published`. The approver is a QAC lead. Reviewers and approvers are listed in
the published record, so a reader can see who prepared, checked, and approved it.
The website shows only published claims.

## Changing a published number

Never edit a committed `results.json` by hand. Re-execute, commit the new executed notebook,
and describe the change in the PR. Superseded results stay in git history; a materially
different result gets a new reproduction id rather than overwriting the old one.
