# Benchmark audit findings log (Gate 2 human review)

Append-only. Each finding records a disagreement between independent reviewers, the stored frozen answers, and the spec. **Findings never modify frozen artifacts directly.** Any resulting change goes into a new, versioned and disclosed benchmark version (EVAL_PROTOCOL.md §1).

## Review summary (fill in after labeling)

| Item | Value |
|---|---|
| Reviewer A (pseudonym; has read generator? y/n) | |
| Reviewer B (pseudonym; has read generator? y/n) | |
| Cases labelled | 47 |
| A–B agreement, all five questions | |
| A–B agreement on outcome; Cohen's κ | |
| Agreement with stored frozen answers (A / B) | |
| Appendix B alternatives confirmed / dropped | / 15 |
| Date completed | |

## Findings

| # | Case | Type: (a) stored label wrong / (b) spec ambiguous / (c) reviewer error / (d) Appendix B alternative confirmed / (e) Appendix B alternative dropped | Reviewer A | Reviewer B | Stored answer | Resolution (spec clarification, or v2 disclosed correction, or none) | Decided by, date |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

## Already-known findings carried in from the audit (not yet reviewed by humans)

| # | Finding | Source | Status |
|---|---|---|---|
| K1 | 25 frozen gold traces in multi-step cases omit status `lookup_user`; the expected actions are correct | spec §3, protocol §7 | Disclosed as a v1 limitation; to be fixed in train/val only |
| K2 | D1 ask/refuse ambiguity: test-0182, test-0184, test_hard-0032, test_hard-0035 | audit §4 | Pending blind review (Appendix B1) |
| K3 | Unstated conventions: low-severity `user_id`, relative dates | audit §4 | Pending blind review (Appendix B2/B3) |
