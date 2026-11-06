## What this PR changes

<!-- New claim / updated assessment / new reproduction / tooling -->

## Checklist

- [ ] `qacclaims validate --online` passes locally
- [ ] `qacclaims build` was run and `dist/` is committed
- [ ] Every number attributed to QAC comes from a `results.json` written by an executed notebook (no hand-typed reproduction figures)
- [ ] Reported figures carry a locator (section / page / table) into the source
- [ ] Deviations from the source's assumptions are listed in the reproduction record
- [ ] `review.reviewed_by` / `review.approved_by` are filled in before `publication.status: published`
- [ ] No internal notes, personal data, or embargoed material in the record (this repository is public)
