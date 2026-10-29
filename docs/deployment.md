# Deployment

The project ships a production-like container stack. It has been run locally. It has not been
deployed to hosted infrastructure.

## Components

| Service | Image | Role |
|---|---|---|
| `db` | `postgres:17-alpine` | All state |
| `migrate` | `agentops-backend` | `alembic upgrade head`, then exits |
| `api` | `agentops-backend` | FastAPI on port 8000 (internal only) |
| `worker` | `agentops-backend` | `scripts/run_worker.py`, claims and executes queued runs |
| `web` | `agentops-web` | nginx serving the console and proxying `/api` |

The API and worker share one image. You can scale workers horizontally: leases and fencing
generations prevent duplicate execution.

## Running the stack

```bash
cp deploy/stack.env.example deploy/stack.env
# Set POSTGRES_PASSWORD, OPERATOR_TOKEN_SHA256 (digest only) and OPERATOR_ID.
GIT_COMMIT_SHA=$(git rev-parse HEAD) docker compose --env-file deploy/stack.env up --build -d
```

Open `http://localhost:8080` (or `WEB_PORT`). Stop with `docker compose --env-file deploy/stack.env down`.
Add `-v` to also delete the database and benchmark volumes.

## Configuration

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | `postgresql://user:password@host:5432/db` (psycopg 3) |
| `APP_ENV` | no | `development` (default), `test` or `production` |
| `OPERATOR_TOKEN_SHA256` | in production | SHA-256 hex digest of the operator bearer token |
| `OPERATOR_ID` | in production | Identity recorded on operator actions |
| `CORS_ORIGINS` | no | Comma-separated HTTPS origins if the console is on another origin |
| `BENCHMARK_DATA_DIR` | no | Manifest directory; mount a volume in containers |
| `GIT_COMMIT_SHA` | no | Build arg recorded in benchmark manifests |

The API refuses to start in production without valid operator credentials or with unsafe CORS
settings.

## Before a shared or public deployment

1. Resolve finding F1 in [security-review.md](security-review.md): authenticate agent
   registration and run submission.
2. Terminate TLS in front of `web`, and set `CORS_ORIGINS` only if the console is on another
   origin.
3. Use a managed PostgreSQL instance with backups. Run `migrate` as a release step.
4. Store `OPERATOR_TOKEN_SHA256` and the database password in the platform's secret manager.
5. Keep benchmark manifests on persistent storage, or treat them as disposable CI artifacts.

## Health and operations

- `GET /api/v1/health` is the liveness probe and is used by the API container's `HEALTHCHECK`.
- The worker logs each processed run and retries after unexpected errors. An abandoned run's
  lease expires and another worker recovers it.
- Expired approvals are swept on every worker cycle.
