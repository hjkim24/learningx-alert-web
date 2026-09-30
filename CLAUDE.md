# CLAUDE.md

Before doing anything, read `docs/HANDOFF.md`. It covers the current state, the working rules the user set, and the remaining tasks. The operations runbook is `docs/operations/oci-production.md`.

Key rules (details in HANDOFF section 2):
- Reply to the user in Korean. Never print secret values (tokens, passwords, webhook URLs).
- Changes go through a feature branch, tests, `git push -u origin <branch>`, a PR, and a merge. A merge to main is deployed automatically by GitHub Actions (`.github/workflows/ci.yml`); check the result with `gh run watch`. Never push to main directly.
- Ask the user before any risky or hard-to-undo change.
- Test: `.venv/bin/python manage.py test`
