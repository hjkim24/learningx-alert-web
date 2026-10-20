# CLAUDE.md

Before doing anything, read `docs/HANDOFF.md`. It covers the current state, the working rules the user set, what is waiting on the user, and the remaining tasks. The operations runbook is `docs/operations/oci-production.md`; Actions deploys are described in `docs/operations/github-actions-deploy.md`.

Key rules (details in HANDOFF section 2):
- Reply to the user in Korean. Never print secret values (tokens, passwords, webhook URLs).
- Changes go through a feature branch, tests, `git push -u origin <branch>`, a PR, and a merge. A merge to main is deployed automatically by GitHub Actions (`.github/workflows/ci.yml`). Check the run with `gh run list --workflow ci.yml --branch main --limit 1`, then check `/healthz/`. Never push to main directly.
- The active `main-owner-only` ruleset permits only user `hjkim24` (ID 37476664) to create, update, or delete `main`. Other branches are unaffected. Do not add bypass actors or change the ruleset without an explicit request. See `docs/operations/github-actions-deploy.md` and its ruleset JSON.
- Ask the user before any risky or hard-to-undo change: data deletion, infrastructure, deploy, or CI settings. Do not change existing behavior that was not asked for; report what you find instead.
- Items in HANDOFF 6-3 wait on the user's decision. Do not start them unasked.
- Current product behavior: `FEATURE_SPEC.md`; real-account evidence and remaining gaps: `FEASIBILITY.md`. Dated files under `docs/superpowers/` preserve design/implementation history and are not current task instructions.
- Tests (after installing the project dependencies): `.venv/bin/python manage.py test`, `.venv/bin/python -m unittest discover -s tests`, `bash scripts/tests/deploy_contract_test.sh`, and `bash deploy/tests/runtime_scripts_test.sh`. Keep dated test counts and verification evidence in HANDOFF.
