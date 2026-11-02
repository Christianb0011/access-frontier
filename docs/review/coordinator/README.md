# Gate 2 review: coordinator guide

**Reviewers must never see this folder.** It holds the selection reasons, stored answers, findings and other reviewers' labels.

## Folder layout
| Path | Audience | Contents |
|---|---|---|
| `../for_reviewers/` | **Reviewers (send only this folder)** | `POLICY_SPEC_FOR_REVIEWERS.md` (generated, case-free), `blind_cases.jsonl` (no category, answers, selection reason or model output), `labels_template.csv`, `README.md` |
| `./` | Coordinator only | `selection.json` (why each case was picked), `AUDIT_FINDINGS.md` (findings log), `labels/` (submitted label files) |

Regenerate the reviewer spec after any change to `docs/POLICY_SPEC.md`:
```
python scripts/make_reviewer_spec.py
```
It refuses to write if any case ID, concrete user or approval ID, or link to a coordinator document (Appendix B, the proposal, the protocol, the audit) would leak.

## The 47-case sample
- **All 15 Appendix B cases.**
- **Weighted toward hard cases:** conflicts, refusals, missing information, mixed and partial workflows, chained and approval-defined requests, approval exports, date and duration boundaries, same-name identities, distractor threads, hidden-state conflicts, incidents, and out-of-scope boundaries.

See `selection.json` for each case's reason.

## Integrity rule
**The review must not modify the frozen test sets, `config/`, the grader, or any saved frontier results.** Every disagreement, label error or spec ambiguity is logged in `AUDIT_FINDINGS.md`. A finding changes the benchmark only through a new, versioned and disclosed version (EVAL_PROTOCOL.md §1).

## Reviewer independence (D9)
| Label file | Reviewer type | Reviewer spec version (source SHA) | Blind? | Counts toward Gate 2 agreement? |
|---|---|---|---|---|
| Reviewer A working draft (file not yet in `labels/`) | ChatGPT-assisted | full spec including Appendix B | **No.** Appendix B named 15 of the cases and their answers. | **No.** A working draft only. |
| `labels/reviewer_B_claude_blind.csv` | **Model reviewer** (Claude, isolated context) | `60f49d735c46`: before the catalog and pasted-export clarifications | Yes | **Yes** |
| *(no Reviewer C: dropped by team decision, see below)* | | | | |

**Methodology decision (team, 2026-11-02):** given the hackathon time limit, Gate 2 is:
- **one independent blind model review** (Reviewer B);
- **plus** a separate non-blind working review (Reviewer A);
- **plus** the spec owner's human sign-off.

There is no second blind reviewer, so **inter-reviewer agreement is not reported**. The accurate public wording is:

> *"The benchmark received one independent blind model review, plus a separate non-blind working review and human owner sign-off. All disagreements and spec clarifications were logged, with the frozen benchmark unchanged."*

Never write "two independent blind reviewers agreed", and never call this "human validation".

**Lesson recorded:** the full spec leaked answers to Reviewer A. The reviewer edition (`make_reviewer_spec.py`) exists because of that.

## Process
1. **Phase 1, blind labeling:** send `../for_reviewers/` to each reviewer. Collect their CSVs into `labels/` as `reviewer_<X>_<date>.csv`.
2. **Comparison with the frozen answers:**
   ```
   python scripts/compare_reviews.py docs/review/coordinator/labels/<file>.csv
   ```
   It parses Q1 into the grader's canonical form and compares Q1–Q4 with `data/*.jsonl` (read-only). It was checked to detect planted errors (wrong target, a date off by one day, ask vs refuse, an extra invalid approval, a dropped missing field, wrong severity).
3. **Appendix B alternatives:** an alternative counts in the **normalized** score only if the blind review supports it. If the blind reviewer independently gives the stored answer, the alternative is **dropped**, unless the spec owner explicitly reinstates it, which must be disclosed as an owner decision. The raw score never uses alternatives.
4. **Log everything** in `AUDIT_FINDINGS.md`. Classify each disagreement as:
   - (a) stored label wrong;
   - (b) spec ambiguous;
   - (c) reviewer error;
   - (d) Appendix B alternative confirmed;
   - (e) Appendix B alternative dropped.
5. **Gate 2 passes** when all three hold:
   - blind Reviewer B is completed;
   - every disagreement and every Appendix B entry is audited and logged;
   - the spec owner signs `docs/POLICY_SPEC.md`.
