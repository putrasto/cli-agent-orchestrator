*** ORIGINAL EXPLORE SUMMARY ***
Task ID: <optional-id>
Business goal:
- <what the feature/fix must achieve>

OpenSpec explore summary:
- Current behavior:
  - <what happens today>
- Root cause / gap:
  - <why current behavior fails>
- Proposed OpenSpec direction:
  - <artifacts/changes expected from analyst>
- Constraints:
  - <performance/security/compatibility constraints>
- Non-goals:
  - <what should not be changed>

Implementation scope:
- In scope:
  - <modules/files/components expected to change>
- Out of scope:
  - <modules/files/components that must not change>

Quality bar:
- Required coding standards:
  - <style, safety, reliability requirements>
- Regression sensitivity:
  - <critical existing behavior that must remain intact>


*** SCENARIO TEST ***
Scenario name: <short-name>
Environment:
- Runtime/version:
  - <python/node/java/etc>
- Dependencies/data source:
  - <db/api/file inputs>

Real input data:
```text
<paste real representative input data here>
```

Execution steps:
1) <step 1 with exact command or action>
2) <step 2>
3) <step 3>

Expected result (exact):
```text
<paste exact expected output/result here>
```

Validation checks:
- Functional:
  - <exact assertion(s) to verify>
- Data correctness:
  - <exact values/fields that must match>
- Error handling:
  - <expected behavior for edge/error conditions>
- Regression checks:
  - <existing behavior that must still pass>

Pass criteria:
- All validation checks pass.
- No critical errors in logs.
- Output matches expected result exactly (unless tolerance explicitly defined).

Fail criteria:
- Any validation check fails.
- Unexpected error/exception occurs.
- Output deviates from expected result.
