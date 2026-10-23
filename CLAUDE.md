# AgentOps Control Plane — Claude Code Instructions

## Project Goal

Build a production-grade AI engineering platform for discovering, evaluating, observing, securing, and operating AI agents.

## Working Rules

1. Work only on the task explicitly requested.
2. Do not modify unrelated files.
3. Prefer small, reviewable changes.
4. Do not change architecture or API contracts unless explicitly requested.
5. Do not add paid services unless explicitly approved.
6. Never place secrets, API keys, passwords, or tokens in tracked files.
7. Never invent benchmark results, metrics, test results, or performance claims.
8. Run the relevant tests and quality checks after code changes.
9. If a test fails, report the failure instead of hiding or bypassing it.
10. Preserve existing working behavior unless the task explicitly requires changing it.

## Backend Rules

- Python 3.12
- FastAPI
- Pydantic
- PostgreSQL
- Type hints required
- Clear service boundaries
- Structured error handling
- Tests for important behavior

## Frontend Rules

- React
- TypeScript
- Responsive design
- Accessible UI
- Dark professional enterprise aesthetic
- No placeholder-quality UI for final features

## AI / Agent Rules

- Prefer deterministic checks before LLM judging where possible.
- Tool calls must use typed schemas.
- Consequential actions must be policy-controlled.
- Evaluation results must be reproducible.
- Safety and permission enforcement must not rely solely on model instructions.

## Security Rules

- Never commit `.env`.
- Follow least privilege.
- Validate tool inputs.
- Record auditable actions.
- Use human approval for sensitive actions where required.

## Git Rules

- Do not commit unless explicitly asked.
- Do not push unless explicitly asked.
- Do not rewrite Git history.
- Keep changes scoped and easy to review.

## Definition of Done

A task is not complete until:
- the requested behavior works,
- relevant tests pass,
- no secrets are exposed,
- the diff is reviewed,
- documentation is updated if needed.
