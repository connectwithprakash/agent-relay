# Agent Relay Dogfood Review

**Relay:** relay-EJNzDEvl7H0
**Date:** 2026-03-21
**Participants:** code_reviewer, dep_auditor, fixer, coordinator

## Summary

The relay successfully coordinated a 4-agent review cycle. The code_reviewer found 13 issues across registry, security, and quality categories. The dep_auditor identified 6 dependency and integration concerns. The fixer resolved 5 items with all 117 tests passing.

## What Was Found

### Code Review (code_reviewer)

**Bugs (4):**
1. registry.py:39-51 - Null relay crash when existing registration points to a deleted relay
2. registry.py:113-143 - Race condition allowing duplicate relay creation during concurrent registration
3. registry.py:138 - Only the last registering agent receives the api_key; earlier agents are locked out
4. models.py - Inconsistent datetime handling: mix of deprecated `utcnow()` and timezone-aware datetimes

**Security (3):**
5. No authentication on `/agents/register` - anyone can register in any namespace
6. No authentication on `/agents/discover/{namespace}` - leaks device_ids, agent names, relay_ids
7. No rate limiting on SSE `/watch` endpoint - could exhaust server resources

**Quality (3):**
8. QueueFull silently drops spectator messages with no logging
9. MCP server global mutable `_client` and `_session` are not thread-safe
10. config.py path handling bug when a directory path is passed

**Missing Features (3):**
11. No agent deregistration/cleanup endpoint
12. No TTL/expiry on heartbeats for offline agents
13. CLI register command fails for non-last agents due to bug #3

### Dependency Audit (dep_auditor)

- **Version pinning:** Backend uses `>=` floor pins only with no lockfile or upper bounds
- **Misplaced deps:** pytest, pytest-cov, pytest-asyncio in production requirements.txt
- **Misplaced deps:** psycopg2-binary included but SQLite is the default DB
- **Python version mismatch:** SDK requires >=3.9, MCP server requires >=3.10
- **Duplication:** MCP server uses direct httpx instead of reusing the SDK
- **No vulnerability scanning:** No safety/pip-audit/npm audit in CI

## What Was Fixed (fixer)

| # | Issue | Fix | Status |
|---|-------|-----|--------|
| 1 | Bug #4: deprecated `datetime.utcnow` | Replaced with `datetime.now(timezone.utc)` in all models | Done |
| 2 | Bug #8: silent QueueFull drop | Added warning log in websocket_manager.py | Done |
| 3 | Bug #10: config path handling | Fixed `load_config` to use `find_config(path)` for directory paths | Done |
| 4 | Dep: test deps in production | Moved pytest/pytest-cov/pytest-asyncio to requirements-dev.txt | Done |
| 5 | Dep: psycopg2-binary placement | Moved to dev deps (SQLite is default) | Done |

All 117 tests pass after fixes.

## What Is Still Open

### P0 - Must Fix Before Merge
- Registry null-check crash (bug #1)
- Race condition on relay creation (bug #2)
- api_key not returned to first registering agent (bug #3)

### P1 - Should Fix Before Release
- No auth on `/agents/register` and `/agents/discover` (security #5, #6)
- MCP global state thread-safety (bug #9)

### P2 - Track for Next Cycle
- No agent deregistration or TTL/heartbeat expiry (#11, #12)
- No rate limiting on SSE connections (#7)
- No dependency vulnerability scanning in CI
- No version upper bounds or lockfile for backend deps
- Python version requirement mismatch across packages
- MCP server should reuse SDK instead of raw httpx

## Quality Assessment

**Verdict: NEEDS WORK**

The fixer addressed 5 low-hanging issues effectively, but the 3 P0 registry bugs are crash/correctness blockers. The fixer confirmed registry.py does not exist in the current codebase, indicating the registry/discovery feature may be incomplete or not yet landed. Authentication on discovery endpoints is also required before any public release.

**Dogfood Process Observation:** The relay itself worked well for coordinating the review. Message delivery was reliable, turn ordering was respected, and all agents could read the full history. The 4-agent workflow (review -> audit -> fix -> coordinate) is a solid pattern for automated code quality checks.

## Next Steps

1. Land or complete the registry feature with fixes for bugs #1-3
2. Add authentication to registration and discovery endpoints
3. Address MCP thread-safety with proper client lifecycle management
4. Add `pip-audit` and `npm audit` to CI pipeline
5. Generate and commit lockfiles for reproducible builds
