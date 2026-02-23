## ADDED Requirements

### Requirement: Notify helper function
The orchestrator SHALL provide a `notify(title, message, priority)` function that sends a push notification via ntfy.sh. The function SHALL POST to `https://ntfy.sh/<NTFY_TOPIC>` with the given title, message, and priority. When `NTFY_TOPIC` is empty or unset, the function SHALL return immediately without making any HTTP request.

#### Scenario: Notification sent when topic is configured
- **WHEN** `NTFY_TOPIC` is set to a non-empty string and `notify()` is called
- **THEN** the function SHALL POST to `https://ntfy.sh/<topic>` with headers `Title`, `Priority`, and the message as body

#### Scenario: Notification skipped when topic is not configured
- **WHEN** `NTFY_TOPIC` is empty or unset and `notify()` is called
- **THEN** the function SHALL return immediately without making any HTTP request

#### Scenario: Notification failure does not crash pipeline
- **WHEN** the HTTP POST to ntfy.sh fails (network error, timeout, non-2xx response)
- **THEN** the function SHALL log the error and return without raising an exception

#### Scenario: HTTP timeout is bounded
- **WHEN** ntfy.sh is unreachable
- **THEN** the HTTP POST SHALL timeout after 5 seconds

### Requirement: NTFY_TOPIC config key
The orchestrator SHALL accept an `NTFY_TOPIC` configuration value via env var `NTFY_TOPIC` or JSON config path `notifications.ntfy_topic`. The default SHALL be an empty string (notifications disabled). The `"notifications"` key SHALL be included in `VALID_TOP_LEVEL_KEYS` so JSON configs containing it pass validation.

#### Scenario: Config from env var
- **WHEN** `NTFY_TOPIC` env var is set to `"my-pipeline"`
- **THEN** `notify()` SHALL POST to `https://ntfy.sh/my-pipeline`

#### Scenario: Config from JSON file
- **WHEN** JSON config contains `{"notifications": {"ntfy_topic": "my-pipeline"}}`
- **THEN** `notify()` SHALL POST to `https://ntfy.sh/my-pipeline`

#### Scenario: JSON config with notifications section passes validation
- **WHEN** a JSON config file contains the top-level key `"notifications"`
- **THEN** the config loader SHALL NOT reject it as an unknown key

### Requirement: Pipeline completion notification
The orchestrator SHALL call `notify()` when the pipeline reaches a final PASS or FAIL result.

#### Scenario: PASS notification
- **WHEN** the pipeline completes with PASS
- **THEN** `notify()` SHALL be called with title "Pipeline PASS", a message including the round number, and priority 3 (default)

#### Scenario: FAIL notification (max rounds exhausted)
- **WHEN** the pipeline exhausts MAX_ROUNDS without PASS
- **THEN** `notify()` SHALL be called with title "Pipeline FAIL", a message including rounds used, and priority 4 (high)

### Requirement: Error and timeout notification
The orchestrator SHALL call `notify()` when `wait_for_response_file()` raises `RuntimeError` (terminal error state) or `TimeoutError` (response timeout). Other RuntimeErrors from different sources (e.g., safety cap exceeded) SHALL NOT trigger a notification from this requirement.

#### Scenario: Terminal error notification
- **WHEN** `wait_for_response_file()` raises `RuntimeError` whose message contains "entered ERROR state"
- **THEN** `notify()` SHALL be called with title "Pipeline error", the error message, and priority 4 (high)

#### Scenario: Response timeout notification
- **WHEN** `wait_for_response_file()` raises `TimeoutError`
- **THEN** `notify()` SHALL be called with title "Pipeline error", the timeout message, and priority 4 (high)

### Requirement: Stuck agent notification
The orchestrator SHALL call `notify()` when an agent is stuck on a permission prompt and auto-accept is disabled. To prevent notification spam, the orchestrator SHALL send at most one stuck-agent notification per role per agent turn (reset when `send_and_wait()` is called).

#### Scenario: Agent stuck with auto-accept off
- **WHEN** `waiting_user_answer` is detected and `AUTO_ACCEPT_PERMISSIONS` is off
- **THEN** `notify()` SHALL be called with title "Agent needs attention", a message including the role and terminal ID, and priority 5 (urgent)

#### Scenario: Stuck notification rate-limited to once per role per turn
- **WHEN** `waiting_user_answer` is detected multiple times for the same role within one `send_and_wait()` call and `AUTO_ACCEPT_PERMISSIONS` is off
- **THEN** `notify()` SHALL be called only once for that role (subsequent detections SHALL be skipped)
