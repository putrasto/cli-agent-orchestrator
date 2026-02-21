## 1. Config

- [x] 1.1 Add `post_processing` to `VALID_TOP_LEVEL_KEYS` in `run_orchestrator_loop.py`
- [x] 1.2 Add `post_processing.openspec_archive` and `post_processing.git_commit` entries to `_CONFIG_KEYS` (both default false, type bool)
- [x] 1.3 Add `post_processing` section to `config-fresh.json` and `config-incremental.json` samples (both false)

## 2. Post-processing functions

- [x] 2.1 Add `detect_active_change(wd)` function: scan `openspec/changes/` for non-`archive` subdirs, return name if exactly one, else None with log warning
- [x] 2.2 Add `post_openspec_archive(wd)` function: detect change, run `openspec archive <name> --yes` via subprocess with `cwd=wd`, return result enum/tuple distinguishing success/skipped/failed (commit gate needs skipped ≠ failed)
- [x] 2.3 Add `post_git_commit(wd)` function: check git repo, `git add -A`, check `git diff --cached --quiet`, `git commit -m "..."`, return success bool
- [x] 2.4 Add `run_post_processing(wd)` function: orchestrate archive then commit with gating logic (skip commit if archive failed when both enabled)

## 3. Integration

- [x] 3.1 Call `run_post_processing(WD)` in the PASS branch between `save_state()` and `cleanup()`

## 4. Tests

- [x] 4.1 Add unit tests for `detect_active_change()`: exactly one, zero, multiple, no directory
- [x] 4.2 Add unit tests for `post_openspec_archive()`: success, failure, skipped (disabled)
- [x] 4.3 Add unit tests for `post_git_commit()`: success, no changes, not a git repo, failure, skipped (archive failed)
- [x] 4.4 Add unit test for `run_post_processing()`: execution order (archive before commit), both disabled is no-op, archive failure skips commit, archive skipped (no change) still allows commit
- [x] 4.5 Add unit test for config: `post_processing` section maps to `POST_OPENSPEC_ARCHIVE` and `POST_GIT_COMMIT`
