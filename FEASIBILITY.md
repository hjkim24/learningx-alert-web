# FEASIBILITY

## Current scope (updated 2026-10-20)

- This file separates recorded real-account evidence from implementation and current production health. The October 20 documentation refresh did not use stored user tokens or send real notifications.
- Current application origin: `https://learningx-alert.com`; the old `alert.sobok-app.com` origin in the September evidence was replaced on 2026-09-30.
- Implemented schools: SKKU and Hanyang. Current behavior is in [FEATURE_SPEC.md](FEATURE_SPEC.md); operations and pending checks are in [HANDOFF](docs/HANDOFF.md).

## Safety conditions

- Scope: read-only Canvas and LearningX checks.
- Accounts: Account A, used with voluntary consent. Since 2026-09-29 the acceptance bar is one real account; isolation between users is covered by automated multi-user tests.
- Credential handling: prompted in memory, not stored or copied into this file.
- Evidence: capability status, response shape (field names and value kinds only), and owner-confirmed source-screen comparison.

## Account A

| Check | Status | Evidence note |
| --- | --- | --- |
| Own course list is isolated | verified | Active course list matched the owner-confirmed source UI |
| Assignment list | verified | Four owner-approved course samples returned independently |
| Own submission state | verified | Own state lookup completed for every returned assignment |
| LearningX sessionless launch | verified | 2026-09-29: launch completed for current-term courses with `canvas.skku.edu` as the only allowed host |
| Lecture list and completion | verified | 2026-09-29: LearningX `/modules` items carry `completed` (bool) and `content_data.use_attendance` / `due_at`; the read-only preview and the production preview listed the same unfinished attendance lectures, and the owner confirmed them against LearningX |
| Required materials | dropped | 2026-09-29 decision: no separate type. Attendance-tracked documents are covered by the lecture selection and labelled `[학습자료]`; the module items expose no `required` field |

### Observed response shape (2026-09-29)

- `allcomponents_db` does not list lecture videos: across 66 active courses only `assignment`, `quiz` and `offline_exam` types appeared. Lectures are read from `/modules` instead.
- A lecture is a module item whose `content_data.use_attendance` is `true`; per course this count matched the number of attendance videos (`screenlecture`, `movie`, `everlec`). Documents (`pdf`, `file`) appeared only with `use_attendance: false`.
- Tab labels differ by language and tool generation: `강의콘텐츠`, `(구) 강의콘텐츠`, `(Old) Lecture Contents`, `출결현황`, `출결/학습 현황`, `Learn Status`. Courses from 2021 with English labels previously reported `lectures_unsupported` until the labels were matched.
- Canvas returns term names (`2026년 2학기`, `2025 비정규`, …); recent 비정규 terms have no start date.

## Account B

Not required after the 2026-09-29 acceptance change. The owner reports that a second account was also tested; no evidence for it is recorded in this file.

## Gate decision

Status: passed (2026-09-29) for Canvas assignment alerts and LearningX attendance-lecture alerts, on the one-account acceptance bar. The validation used the old production origin `https://alert.sobok-app.com` with `LEARNINGX_ALLOWED_HOSTS=canvas.skku.edu`. This is a dated gate decision, not a new production-health or delivery check.

## Hanyang (2026-09-30)

Recorded read-only checks used the owner's explicitly supplied Hanyang token. Details and response-shape evidence are in [the expansion review](docs/superpowers/specs/2026-09-30-expansion-review.md#한양대-실측-2026-09-30).

| Check | Status | Evidence note |
| --- | --- | --- |
| Profile, active courses, assignments, own submission state | verified | The expected Canvas endpoints and fields were available |
| LearningX launch and modules | verified | Four course launches succeeded; expected completion, attendance and deadline fields were present |
| Application collectors | verified with empty results | Assignment and lecture collectors finished without errors; no deadline-bearing unfinished item was available |
| Connection through the multi-school production UI | owner-confirmed | Recorded in HANDOFF after the multi-school deployment |
| Deadline-bearing recorded-lecture alert | unverified | Attendance items in the sample were live classes without `due_at`; there was no recorded-lecture sample |

## Remaining evidence gaps

- Hanyang recorded lectures with a real deadline, followed through preview, scheduled execution and receipt.
- Submission-state behavior of an actual in-progress Canvas quiz. LearningX-only quizzes are not implemented.
- Current scheduled-run delay, notification receipt and monthly restore-drill results. The repository has implementation and historical observations, but the October 20 refresh did not recheck the VM, Grafana or recipient devices.
- Recorded API/source comparisons do not establish a measured missed-notification rate, duplicate rate, availability percentage or universal school support.
