# =============================================================================
# DFX Solution Backend — Production Dockerfile
#
# Python:  3.10-slim (matches runtime Python 3.10.10)
# User:    non-root (appuser:appgroup, uid/gid 1001)
# Port:    8000
# Health:  GET /api/v1/health  (python urllib — no curl dependency)
# Start:   scripts/entrypoint.sh → alembic upgrade head → uvicorn
# =============================================================================

FROM python:3.10-slim

# ---------------------------------------------------------------------------
# OS-level dependencies
#
# Why these packages:
#   libglib2.0-0  — required by opencv-python-headless (GLib runtime)
#   libgl1        — required by opencv-python-headless (OpenGL, headless uses
#                   stub implementations but still links against libGL)
#   libgomp1      — GNU OpenMP runtime; numpy and opencv use it for
#                   multi-threaded operations even in single-threaded code
#
# No curl — Docker HEALTHCHECK uses Python's built-in urllib.request instead,
# keeping the image smaller and the dependency surface minimal.
# ---------------------------------------------------------------------------
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Non-root user
# ---------------------------------------------------------------------------
RUN groupadd --gid 1001 appgroup \
    && useradd  \
        --uid 1001 \
        --gid appgroup \
        --shell /bin/sh \
        --create-home \
        appuser

WORKDIR /app

# ---------------------------------------------------------------------------
# Python dependencies
#
# requirements.txt is copied before the application source so that this
# layer is cached by Docker and only rebuilt when requirements change —
# not on every source file edit.
# ---------------------------------------------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Application source
#
# --chown sets ownership in a single layer (vs. a separate RUN chown which
# would double the layer size for large source trees).
# The .dockerignore file excludes: venv, uploads, __pycache__, .env*,
# tests, *.db, *.log, .git, IDE dirs.
# ---------------------------------------------------------------------------
COPY --chown=appuser:appgroup . .

# Make the entrypoint executable after copy
RUN chmod +x scripts/entrypoint.sh

# ---------------------------------------------------------------------------
# Uploads directory
#
# Created here so the named volume mount works correctly on first startup.
# The app also calls Path(LOCAL_UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
# in main.py, but the directory must be owned by appuser before we drop
# privileges — otherwise the volume mount root is owned by root.
# ---------------------------------------------------------------------------
RUN mkdir -p uploads \
    && chown -R appuser:appgroup uploads

# ---------------------------------------------------------------------------
# Drop privileges
# ---------------------------------------------------------------------------
USER appuser

EXPOSE 8000

# ---------------------------------------------------------------------------
# Health check
#
# Uses Python's standard library — no extra OS packages required.
# --start-period=20s gives the app time to connect to Supabase and complete
# its DB ping on startup before the healthcheck is considered failing.
# ---------------------------------------------------------------------------
HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=20s \
    --retries=3 \
    CMD python -c \
        "import urllib.request, sys; \
         r = urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=8); \
         sys.exit(0 if r.status == 200 else 1)"

ENTRYPOINT ["scripts/entrypoint.sh"]
