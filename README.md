# QAC claims registry

This repository contains the Quantum Applications Center's records of published claims about
the resources quantum computers need for specific applications, together with our reproductions
of those claims. Each record transcribes what a publication reports and compares it with the
result of rerunning the calculation.

## Layout

```
claims/<claim-id>/
  narrative.md                        written explanation of the claim and the reproduction
  README.md                           narrative.md with its figures filled in (generated)
  claim.yaml                          the claim, its source, the assumptions it states, and our assessment
  estimates/reported.yaml             the figures the source reports, each with a page or table reference
  estimates/reproduction-<id>.yaml    how a reproduction was done and where it departs from the source
  reproductions/<id>/
    notebook.ipynb or reproduce.py    the reproduction (a notebook is committed after it has run)
    results.json                      the figures the reproduction produced
    requirements.lock.txt             the package versions used
    run.json                          when and by whom the reproduction was run
schemas/                              JSON Schemas for the files above
dist/                                 the combined records, one JSON file per claim
qacclaims/                            validation, build, and execution tools
```

## How the records are kept consistent

Reported figures are entered by hand from the source, with a reference to where each appears.
Reproduced figures are not entered by hand. The reproduction writes them to `results.json`, and
the other files refer to them there, so a figure on the website or in a narrative is always the
one the code produced. The narratives quote figures through placeholders that are filled in when
the records are built.

Each reproduction is committed after it has been run, with the package versions it used and
checksums that tie the code, its results, and its environment together. A record is published
only after it has been reviewed and approved, and the reviewers and the date are part of the
record. Where our assumptions differ from those of the source, the record lists each difference
and the reason for it.

The `qacclaims` tools check these rules on every change. The repository also reruns every
reproduction weekly and reports any change in the results.

## Commands

```bash
pip install -e ".[test]"
qacclaims validate --online        # check every record against the schemas and the rules above
qacclaims build                    # regenerate dist/ and the claim READMEs
qacclaims execute claims/<id>/reproductions/<rid>          # rerun a reproduction and report differences
qacclaims execute ... --write --operator "Name"            # rerun and commit the new results
```

Each reproduction runs in the environment pinned by its own `requirements.lock.txt`; see the
claim's README for instructions. Contributions are described in `CONTRIBUTING.md`.

## Licenses

The records (`claims/`, `dist/`) are licensed under CC BY 4.0; see `LICENSE-DATA.md`. The code is
licensed under the MIT License; see `LICENSE`. Figures transcribed from publications are short
factual excerpts, cited to their source.
