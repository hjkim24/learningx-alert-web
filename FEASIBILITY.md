# FEASIBILITY

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

Status: passed (2026-09-29) for Canvas assignment alerts and LearningX attendance-lecture alerts, on the one-account acceptance bar. Production at `https://alert.sobok-app.com` runs with `LEARNINGX_ALLOWED_HOSTS=canvas.skku.edu`.
