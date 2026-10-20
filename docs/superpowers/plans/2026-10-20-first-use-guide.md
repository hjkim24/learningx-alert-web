# First-use Guide Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this approved small change inline with TDD checkpoints. Steps use checkbox syntax for tracking.

**Goal:** Help a new user reach the first test notification through Canvas connection, course selection, destination registration and an explicit test send.

**Architecture:** Preserve the login page's existing notification example and add supported schools plus a short setup overview. Expand the dashboard's existing status rail into a four-step, collapsible guide. Derive progress from the existing user-scoped connection, selected courses, active alarms and destination test status; no migration, persistent onboarding flag, new endpoint, dependency or automatic notification.

**Tech Stack:** Existing Django templates, Python, CSS and native HTML details.

**Spec:** User-approved four-step tutorial and brief login introduction in this conversation (2026-10-20); `FEATURE_SPEC.md` defines existing notification behavior, `DESIGN.md` defines visual constraints.

## Global Constraints

- Work on `feat/first-use-guide` from current main; preserve the existing forms, guides, routes, Google sign-in and notification delivery behavior.
- Korean copy; use the existing navy tokens and type scale. Amber remains reserved for approaching deadlines; setup progress uses brand colors.
- Show only the first missing prerequisite as current. An expired Canvas token returns the guide to connection. A disabled schedule prevents the completion message even after a successful test.
- A successful test send does not prove receipt on the device; ask the user to check it. Never send on a guide GET or link click.
- Existing users can reopen the collapsed guide. Use native HTML and existing anchors so guidance works without JavaScript.
- Follow the repo's feature branch → tests → PR flow. Do not change main rules, CI, infrastructure or delivery configuration.

## Review Focus

- Other users' saved targets or successful tests must not advance this user's progress.
- Retained course/target settings must not hide a rejected Canvas token.
- No active alarm must lead to schedule settings, not a claim that scheduled notifications are ready.
- A failed/ambiguous test and an untested destination remain incomplete; at least one successful current destination completes the test step.
- Keyboard access, reopened details, 320px layout and no-JavaScript navigation must remain usable.

### Task 1: First-use path

**Files:**
- Modify `accounts/views.py`, `config/context_processors.py`, `templates/accounts/dashboard.html`, `templates/account/login.html`, `static/app.css`. Reuse `enabled_schools()` in shared context for the login intro.
- Create `templates/accounts/_getting_started.html`, `accounts/tests/test_onboarding.py`.
- Update the old three-step expectation in `accounts/tests/test_alarms.py` to the approved four-step behavior.
- Update `FEATURE_SPEC.md`, `README.md`, `docs/HANDOFF.md` after verification.

**Interfaces:** Dashboard context gains `setup_step` (1–4 or null when complete), `setup_completed_count` (0–4), and `setup_test_succeeded` (bool); existing context and destination-test POST endpoints stay intact.

- [x] Write behavioral tests for the current CTA across new, connected, course-selected, registered, failed-test, successful-test, disabled-schedule and reconnect states; include a second user's successful settings as an isolation check.
- [x] Run the new tests and observe failures because the guide is absent.
- [x] Reuse existing dashboard queries to derive progress and render the four-step guide. Link each action to its existing form/settings page; completed users see it collapsed.
- [x] Keep the current login example and Google form; explain school support, setup order and links to the token/install guides.
- [x] Run targeted tests, then the full Django/client suites and both deployment script tests. Check no migration is needed.
- [x] Render representative dashboard states with synthetic local fixtures; inspect desktop and mobile, keyboard/details behavior, overflow and CTA navigation without external sends.
- [ ] Review the complete diff against the five focus items, address material findings, update the product docs and commit.
- [ ] Push `feat/first-use-guide`, create a PR, and verify CI. Obtain any required production-deploy approval only after the result is concrete and reviewable.
