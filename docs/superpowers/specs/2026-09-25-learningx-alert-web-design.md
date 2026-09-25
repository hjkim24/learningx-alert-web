# LearningX Alert Web Design

## Status

- Approved in conversation on 2026-09-25.
- Product implementation has not started.
- The first release is a private two-account pilot for Sungkyunkwan University LearningX/Canvas.

## Intent and success criteria

The service lets each approved student sign in with Google, connect their own Canvas personal access token, choose courses and notification item types, and receive scheduled deadline alerts through Discord or Slack. The service must keep working after the browser closes.

The pilot is successful only when two different student accounts complete this flow independently:

1. Sign in and connect Canvas.
2. See only their own active courses.
3. Select courses and item types.
4. Send a user-initiated test notification.
5. Receive a scheduled notification.
6. Compare assignments, LearningX lecture or attendance items, required materials, deadlines, and completion state with the source UI or approved test evidence.

The service must not claim support for a LearningX item type that the two-account feasibility check cannot verify.

## Scope

### Pilot scope

- One operator-configured Sungkyunkwan University Canvas host.
- Google OAuth login for two allowlisted pilot accounts.
- Canvas token connection, replacement, and disconnection.
- Active-course discovery with pagination.
- Per-course selection of assignments, deadline-bearing lecture or attendance items, and deadline-bearing required materials.
- A one-to-fourteen-day lookahead window.
- One or two daily execution times in Asia/Seoul.
- One Discord or Slack webhook per user.
- User-initiated test delivery.
- Scheduled collection, completion recheck, delivery, execution history, and per-course failure reporting.
- Account deletion with cascading removal of local settings and secrets.

### Explicit exclusions

- Arbitrary webhook URLs or arbitrary Canvas hosts.
- Other universities.
- Assignment submission, attendance manipulation, or lecture playback.
- Mobile applications, AI deadline inference, prioritization, and calendar synchronization.
- Multiple destinations, per-item exclusions, email, Telegram, and non-Korean time zones.
- Immediate replacement of the existing personal notifier.

## Selected stack

- Python 3.12.
- Django 5.2 LTS.
- Django templates, plain HTML and CSS, and minimal browser JavaScript.
- django-allauth with the Google provider.
- SQLite on a persistent volume.
- `cryptography` Fernet encryption for stored Canvas tokens and webhook URLs.
- One Django web process and one long-running Django management-command worker.
- Docker Compose on one OCI Compute VM.
- Caddy for public HTTPS termination.
- Django `TestCase` and `unittest.mock` for automated tests.

React, a separate REST API, Redis, Celery, PostgreSQL, and Kubernetes are intentionally omitted from the pilot. They are added only if measured load or deployment topology exceeds a single host and worker.

## Architecture

```text
User browser
    |
    | HTTPS
    v
  Caddy
    |
    v
Django web -------- SQLite persistent volume
                         ^
                         |
Scheduler worker --------+
    |              |
    |              +---- Discord or Slack
    +------------------- Canvas or LearningX
```

The web and worker processes use the same Django code and database. The web process handles authentication, configuration, previews, user-initiated test delivery, and history pages. The worker finds due schedules, rechecks current source state, creates messages, sends them, and records safe results.

The initial deployment runs one web process and one worker. The database enforces run and delivery uniqueness so a restarted worker cannot create a second copy of a confirmed run or message.

## Components

### Accounts

django-allauth performs Google OAuth login. Only email addresses in the operator-controlled pilot allowlist may create or use an account. Google is used only for service identity; it does not grant Canvas access. The OAuth request uses only the identity scopes needed for login.

### LearningX client

The client is adapted from the existing personal notifier's Canvas pagination, LearningX external-tool launch, attendance, module, and submission-state logic. Hard-coded courses and notification windows are removed. The client accepts one user's decrypted token and explicit selected course IDs.

The Canvas base URL is fixed by operator configuration and is never accepted from a user. LearningX origins observed during feasibility testing are added to an explicit operator allowlist before those features are enabled.

### Collection service

The collection service queries each selected course and item type independently. It returns normalized items and structured failures. It does not treat a failed completion lookup as an incomplete item and does not turn a course failure into an empty result.

### Notification service

The notification service renders normalized items and failures in deadline order using provider-specific formatting. It splits messages to provider-safe sizes and records one delivery row per part. Discord and Slack URL validation and response interpretation remain separate.

### Scheduler worker

The worker polls once per minute for due rules. It claims a scheduled slot by creating a unique run row in a database transaction. Users are processed independently and sequentially in the pilot.

## Data model

### `User`

Django user identity linked to the Google social account.

### `CanvasConnection`

- One-to-one with `User`.
- Canvas user ID.
- Encrypted Canvas token.
- Connection status and last verification time.

The plaintext token is never redisplayed.

### `CourseSelection`

- User.
- Stable Canvas course ID and display-name snapshot.
- Enabled flag.
- Assignment, lecture or attendance, and required-material flags.

`(user, canvas_course_id)` is unique. All flags default to false.

### `NotificationRule`

- One-to-one with `User`.
- Lookahead days from 1 through 14.
- First daily local time.
- Optional second daily local time, distinct from the first.

### `Destination`

- One-to-one with `User`.
- Discord or Slack kind.
- Encrypted webhook URL.
- Verification status and last test result time.

### `ScheduledRun`

- User and scheduled UTC slot.
- Started and finished times.
- Pending, running, succeeded, empty, failed, interrupted, or needs-review status.

`(user, scheduled_for)` is unique.

### `CourseRunResult`

- Run and course ID.
- Success, empty, or failed status.
- Safe error code and display-safe summary.

### `RunItem`

- Run, course ID, stable external item ID, item type, title snapshot, due time, and observed state.

External item ID, item type, and due time identify an item; the title is never used as identity.

### `Delivery`

- Run, destination kind, part number, idempotency key, provider-confirmation ID when available, and status.
- Pending, sending, succeeded, definitely-failed, or needs-review status.

The idempotency key is unique and includes the user, destination, scheduled slot, and message part identity.

Deleting a user cascades through all application-owned records. The UI also explains how to revoke the Canvas token and webhook at their external providers.

## User flow

### Login and Canvas connection

1. An allowlisted user signs in with Google.
2. The user submits a Canvas token over HTTPS.
3. The server validates the token against the fixed Canvas host.
4. Invalid tokens are not saved.
5. Valid tokens are encrypted and stored; the UI shows only connection status, Canvas identity, and verification time.

### Course selection and preview

1. The server follows Canvas pagination and requests active enrolments.
2. Newly discovered courses are shown unselected.
3. The user enables courses and item types.
4. Preview collection labels outcomes as deadline found, no deadline, or unavailable.

### Destination setup

1. The server checks the provider-specific HTTPS host and URL format.
2. The webhook is encrypted before storage.
3. No request is sent merely by saving the webhook.
4. A test notification is sent only from an explicit user action.

### Scheduled execution

1. The worker calculates due slots in Asia/Seoul and atomically creates a run.
2. It decrypts the user's secrets only for the active operation.
3. It re-fetches every selected source and completion state.
4. It includes items satisfying `now < due_at <= now + lookahead`.
5. It records each course outcome and sorts valid incomplete items by deadline.
6. When items and failures are both absent, it records an empty run and sends nothing.
7. When failures exist, it includes a warning even if no valid item was collected.
8. It creates delivery intent rows before network delivery.
9. It marks only provider-confirmed responses as success.

## Idempotency and interruption behavior

- A repeated worker scan cannot create a second run for the same user and scheduled slot.
- A run interrupted before any delivery request may be resumed for the same slot.
- Once a delivery request starts, a process crash or ambiguous network result changes the delivery to `needs-review`; it is not automatically resent.
- A confirmed successful delivery is never resent for the same run.
- A later scheduled run performs a fresh source check. An item still incomplete may appear again by design; an item completed since the prior run is excluded.

## Network and secret security

- Only HTTPS is allowed outside local development.
- Canvas, discovered pagination URLs, LTI form actions, and redirects are validated at every hop.
- Allowed hostnames must resolve to public addresses; loopback, private, link-local, reserved, and cloud-metadata destinations are rejected.
- Automatic redirects are disabled for security-sensitive clients.
- Canvas authorization headers never cross an origin boundary.
- Canvas or LearningX traffic and webhook traffic use separate HTTP sessions and cookie jars.
- TLS verification, connection and response timeouts, and response-size limits are mandatory.
- Session cookies use `Secure`, `HttpOnly`, and `SameSite=Lax` in deployment.
- Django CSRF protection covers every state-changing browser request.
- Fernet ciphertext is stored in SQLite; its key, Django secret, Google OAuth secret, and deployment configuration remain outside the database and Git.
- Logs contain internal IDs, safe error codes, and timing only. They exclude tokens, webhook URLs, authorization headers, external response bodies, and raw exception representations that may embed URLs.

Local secret files are ignored by Git. OCI receives secrets through deployment environment configuration with restricted file and process permissions. Database backups remain encrypted at the field level, while the encryption key is backed up separately with operator-only access.

## Error handling

- An invalid or revoked Canvas token changes only that user to reconnect-required and skips their collection.
- A single course or item-type failure does not stop other selected sources.
- A single user's failure does not stop other users.
- A provider-confirmed 4xx response is a definite delivery failure.
- A timeout, connection drop, or worker crash after delivery begins is needs-review.
- No scheduled delivery is automatically retried during the pilot. A later schedule remains independent.
- Stale running rows are reconciled on worker startup: rows with no started delivery may resume; rows with a sending delivery become needs-review.
- User-facing errors are stable Korean messages paired with safe error codes. Detailed secrets and raw external payloads are not displayed.

## Screens

1. Login: Google sign-in and pilot-access denial.
2. Canvas setup: connect, replace, disconnect, and view safe status.
3. Course selection: active courses, three type switches, preview, empty, and unavailable states.
4. Notification settings: lookahead, one or two times, provider, webhook, and explicit test button.
5. Dashboard: connection status, next run, recent run, course failures, and destination problems.
6. Run detail: included items, per-course outcomes, and per-part delivery results.
7. Account management: remove Canvas connection, destination, or the entire local account.

All screens are server-rendered and responsive. Native form controls and server validation are the default. Small JavaScript modules handle only asynchronous connection checks, previews, and test delivery feedback. The feature remains usable when JavaScript-enhanced actions fall back to normal form submission.

## Testing

Automated tests use mocked external responses and never require real credentials. Coverage includes:

- Canvas pagination and active-enrolment filtering.
- Per-type selection.
- Submitted and completed exclusion.
- `now < due_at <= now + lookahead` boundary behavior.
- UTC and Asia/Seoul conversion, including scheduler slot calculation.
- Empty and failed lookup distinction.
- Invalid token rejection without storage.
- Provider URL validation, redirect validation, and private-address rejection.
- Discord and Slack confirmed success, definite failure, and ambiguous outcomes.
- Run and delivery uniqueness.
- Worker restart before and after delivery starts.
- User A isolation from user B across every view and service query.
- Cascading account deletion.
- Log and displayed-error redaction.

The feasibility phase uses two voluntarily supplied accounts and test channels with explicit approval. `FEASIBILITY.md` records support as verified, unavailable, or unverified for each account, course, and item type without storing tokens or sensitive response bodies.

## Deployment

Local development runs the Django web server and scheduler management command as separate processes. Production uses one Docker image with separate `web` and `worker` services, a shared SQLite persistent volume, and Caddy in front of the web service.

The OCI firewall exposes only the ports required for HTTPS and restricted administration. The deployment uses a real domain and HTTPS before accepting Canvas tokens or webhooks. The SQLite file and secret-bearing environment configuration are readable only by the service operator.

## Delivery sequence

1. Create the private repository and baseline project safety files.
2. Build a read-only Canvas and LearningX feasibility probe plus `FEASIBILITY.md` structure.
3. Verify the first account without persisting its token.
4. Implement Google login and one-account Canvas connection.
5. Add course selection, preview, and test notification.
6. Add tenant isolation and the second account.
7. Add scheduling, execution history, and idempotent delivery.
8. Run the two-account end-to-end pilot and record redacted results.
9. Deploy to OCI only after the feasibility gate passes for the advertised scope.

If LearningX external-tool launch or completion-state access fails for the second account, the public scope is reduced to verified Canvas assignment alerts unless the user separately approves further institutional integration work.

## Acceptance criteria

- Two allowlisted users see only their own courses, settings, secrets, and run history.
- Invalid credentials are not stored.
- Completed, submitted, expired, disabled-course, and disabled-type items are absent from alerts.
- Exact lookahead-boundary items are included.
- Empty results, lookup failures, definite delivery failures, and ambiguous deliveries remain distinct.
- A repeated worker scan cannot duplicate a confirmed scheduled delivery.
- Test delivery occurs only after a direct user action.
- Tokens and webhook URLs do not appear in Git, ordinary logs, UI responses, screenshots used as evidence, or another user's data.
- Two-account setup, collection, scheduling, receipt, and source comparison are documented with secrets removed.
