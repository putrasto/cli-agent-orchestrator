## Context

The peer system analyst reviewer (`peer_system_analyst.md`) acts as a quality gate between the analyst and programmer phases. Currently, the agent profile is 24 lines with vague instructions ("review for correctness, scope, and OpenSpec completeness") and no rejection criteria. The evidence patterns in `ANALYST_EVIDENCE_PATTERNS` match common words like "artifact", "downstream", "handoff" that appear in any superficial review. Result: the reviewer almost always approves on the first eligible cycle.

## Goals / Non-Goals

**Goals:**
- Make the peer analyst adversarial-by-default: default stance is REVISE, reviewer must justify APPROVED
- Define concrete, checkable rejection criteria tied to ANALYST_SUMMARY sections
- Require the reviewer to verify file/path references against the codebase
- Tighten evidence patterns so trivial reviews fail the evidence gate
- Update the review prompt checklist to match the hardened profile

**Non-Goals:**
- Changing the peer programmer reviewer (separate change)
- Changing the orchestrator's approval gate logic (`is_review_approved` cycle/evidence thresholds)
- Changing the analyst profile or ANALYST_SUMMARY format
- Adding new environment variables or config

## Decisions

### 1. Adversarial-by-default profile structure

The profile will state: "Your default recommendation is REVISE. Only approve when ALL criteria below are met." This forces the LLM to work through rejection criteria before considering approval.

**Alternative considered:** Adding a "strictness" parameter to control review aggressiveness. Rejected — adds config complexity and the current problem is the profile text, not a missing knob.

### 2. Section-by-section rejection criteria

The profile will list each expected ANALYST_SUMMARY section (Scope, OpenSpec artifacts, Implementation notes, Risks, Downstream impact) with specific rejection triggers:
- Scope: reject if no file paths or module names mentioned
- OpenSpec artifacts: reject if no artifact filenames listed
- Implementation notes: reject if fewer than 3 concrete action items
- Risks: reject if "none" or single-line with no mitigation
- Downstream impact: reject if missing or says "N/A"

**Alternative considered:** A generic "must be detailed enough" instruction. Rejected — too subjective, LLMs interpret "detailed enough" generously.

### 3. Codebase verification requirement

The profile will instruct the reviewer to verify that at least 2 file paths mentioned in the analyst output actually exist (using `ls` or `find`). If paths don't exist, REVISE.

**Alternative considered:** Requiring verification of ALL paths. Rejected — could be slow and some paths may be new files the analyst proposes to create.

### 4. Tighter evidence patterns

Replace the current patterns:
- `artifact|proposal|design|tasks|spec` → require at least 2 of these words together with a verdict word (verified/missing/incomplete/correct)
- `P1|P2|P3|P4|traceability|phase` → require priority + coverage/gap language
- `downstream|contract` → require specific module/file reference near the keyword
- `handoff|actionable` → require concrete next-step language (not just the word "actionable")

New patterns will use multi-word regex that requires co-occurrence of domain term + assessment term.

**Alternative considered:** Raising `REVIEW_EVIDENCE_MIN_MATCH` from 3 to 4. Rejected — doesn't fix the root cause (patterns too loose), just raises the bar on the same weak patterns.

### 5. Updated review prompt checklist

The `build_analyst_review_prompt()` checklist will mirror the profile's rejection criteria, making the per-turn prompt reinforce the system prompt expectations.

## Risks / Trade-offs

- **Risk: Over-rejection causing endless cycles** → Mitigation: `MAX_REVIEW_CYCLES` still caps iterations. The analyst will improve its output to meet criteria over cycles, which is the desired behavior.
- **Risk: Codebase verification slows down review** → Mitigation: Only require 2 path checks, not exhaustive. The reviewer is already in a terminal with codebase access.
- **Risk: Tighter patterns break existing test assertions** → Mitigation: Update tests alongside pattern changes. Evidence text in tests will use the new co-occurrence format.
