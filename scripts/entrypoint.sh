#!/bin/sh
# =============================================================================
# DFX Solution Backend â€” Container Entrypoint
#
# Responsibilities:
#   1. Optionally run Alembic migrations (controlled by SKIP_MIGRATIONS)
#   2. Start uvicorn (as PID 1 via exec, so OS signals reach it directly)
#
# Environment variables:
#   SKIP_MIGRATIONS   Set to "true" to skip automatic migrations.
#                     Useful for:
#                       - PgBouncer transaction-mode deployments (DDL requires
#                         a session-mode / direct connection)
#                       - Blue-green deployments where a separate migration job
#                         runs before traffic is cut over
#                       - Read-only replicas / scaled-out container instances
#                         (run migrations only on the primary/first instance)
#                     Default: false (migrations run on every container start)
#
#   APP_HOST          Bind host for uvicorn (default: 0.0.0.0)
#   APP_PORT          Bind port for uvicorn (default: 8000)
#   APP_WORKERS       Number of uvicorn workers (default: 1)
#                     NOTE: Keep at 1 unless you fully understand the async
#                     connection-pool implications. See implementation_plan.md.
# =============================================================================
set -eu

HOST="${APP_HOST:-0.0.0.0}"
PORT="${APP_PORT:-8000}"
WORKERS="${APP_WORKERS:-1}"

echo "[entrypoint] ============================================"
echo "[entrypoint] DFX Solution Backend â€” starting up"
echo "[entrypoint] ============================================"
echo "[entrypoint] Host    : ${HOST}:${PORT}"
echo "[entrypoint] Workers : ${WORKERS}"

# ---------------------------------------------------------------------------
# Alembic migrations
# ---------------------------------------------------------------------------
if [ "${SKIP_MIGRATIONS:-false}" = "true" ]; then
    echo "[entrypoint] SKIP_MIGRATIONS=true â€” skipping automatic migrations."
    echo "[entrypoint] Run 'alembic upgrade head' manually when ready."
else
    echo "[entrypoint] Running database migrations (alembic upgrade head)..."
    alembic upgrade head
    echo "[entrypoint] Migrations complete."
fi

echo "[entrypoint] ============================================"
echo "[entrypoint] Starting uvicorn..."
echo "[entrypoint] ============================================"

# exec replaces this shell with uvicorn so it becomes PID 1 and receives
# SIGTERM / SIGINT directly â€” required for graceful shutdown.
exec uvicorn app.main:app \
    --host "${HOST}" \
    --port "${PORT}" \
    --workers "${WORKERS}" \
    --no-access-log
