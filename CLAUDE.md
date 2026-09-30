# CLAUDE.md

Before doing anything, read `docs/HANDOFF.md`. It covers the current state, the working rules the user set, what is waiting on the user, and the remaining tasks. The operations runbook is `docs/operations/oci-production.md`; Actions deploys are described in `docs/operations/github-actions-deploy.md`.

Key rules (details in HANDOFF section 2):
- Reply to the user in Korean. Never print secret values (tokens, passwords, webhook URLs).
- Changes go through a feature branch, tests, `git push -u origin <branch>`, a PR, and a merge. A merge to main is deployed automatically by GitHub Actions (`.github/workflows/ci.yml`). Check the run with `gh run list --workflow ci.yml --branch main --limit 1`, then check `/healthz/`. Never push to main directly.
- Ask the user before any risky or hard-to-undo change: data deletion, infrastructure, deploy, or CI settings. Do not change existing behavior that was not asked for; report what you find instead.
- Items in HANDOFF 6-3 wait on the user's decision. Do not start them unasked.
- Test: `.venv/bin/python manage.py test` (447 tests), plus `bash scripts/tests/deploy_contract_test.sh`.
