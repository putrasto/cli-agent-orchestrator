## Context

The orchestrator loop runs autonomously for extended periods. Currently, the only way to know the pipeline finished or got stuck is to watch the terminal. Operators need mobile push notifications so they can step away from the machine.

ntfy.sh is a zero-setup, free, open-source push notification service. Sending a notification is a single HTTP POST — no API keys, no accounts, just a topic name.

## Goals / Non-Goals

**Goals:**
- Send push notifications for pipeline completion (PASS/FAIL), errors, timeouts, and stuck agents
- Zero-overhead when disabled (no config = no notifications, no import cost)
- Fire-and-forget: notification failures never crash the pipeline

**Non-Goals:**
- Supporting notification services other than ntfy.sh (Pushover, Slack, etc.)
- Rich notification content (images, actions, attachments)
- Bidirectional communication (receiving commands via notifications)

## Decisions

### 1. Use `urllib.request` instead of adding `requests` dependency
**Rationale**: The orchestrator already uses `httpx` for API calls, but ntfy.sh needs only a trivial POST. Using `urllib.request` from stdlib avoids any new dependency. The `notify()` function is a simple fire-and-forget POST.

**Alternative considered**: Using `httpx` — works but ties notification to the API client. `urllib` is simpler and keeps the notification self-contained.

### 2. Config key: `NTFY_TOPIC` (string, default empty)
**Rationale**: When empty/unset, notifications are silently skipped (the `notify()` function returns immediately). This is the simplest opt-in model — set the topic, get notifications. The topic doubles as the enable flag.

JSON config path: `notifications.ntfy_topic`. Env var: `NTFY_TOPIC`.

### 3. Notification events and priorities
ntfy.sh supports priorities 1-5 (min, low, default, high, urgent). Map pipeline events to priorities:

| Event | Priority | Title |
|-------|----------|-------|
| PASS | default (3) | "Pipeline PASS" |
| FAIL (max rounds) | high (4) | "Pipeline FAIL" |
| Agent stuck (waiting_user_answer, auto-accept off) | urgent (5) | "Agent needs attention" |
| Error / timeout | high (4) | "Pipeline error" |

### 4. Fire-and-forget with try/except
**Rationale**: Notification failures (network issues, ntfy.sh down) must never affect the pipeline. Wrap every `notify()` call in a try/except that logs the failure and continues. The `notify()` function itself catches all exceptions internally.

### 5. Timeout of 5 seconds for HTTP POST
**Rationale**: Prevents the pipeline from hanging if ntfy.sh is unreachable. 5 seconds is generous for a small POST to a CDN-backed service.

## Risks / Trade-offs

- **ntfy.sh availability** → Fire-and-forget with 5s timeout. Pipeline never blocked.
- **Topic name is public** → ntfy.sh topics are publicly accessible by default. Users who need privacy can self-host ntfy or use a hard-to-guess topic name. Notification content only includes pipeline status, not code.
- **Notification spam on rapid retries** → Each event fires at most once per occurrence. The orchestrator's natural flow (one PASS/FAIL per run, one error per failure) limits volume.
