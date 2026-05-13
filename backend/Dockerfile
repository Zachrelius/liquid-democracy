FROM python:3.11-slim

# Install system dependencies for psycopg2.
# gosu is used by entrypoint.sh (Phase 26 B1) to drop privileges from root
# to appuser after fixing volume-mount ownership.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev gcc curl gosu && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Install Python dependencies (separate layer for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Remove gcc after pip install (no longer needed)
RUN apt-get purge -y gcc && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY . .

# Fix Windows CRLF line endings in shell scripts and config files.
# entrypoint.sh joins the file list (Phase 26 B1).
RUN find . -type f \( -name "*.sh" -o -name "*.ini" -o -name "*.cfg" -o -name "*.py" -o -name "*.txt" -o -name "*.mako" \) -exec sed -i 's/\r$//' {} + && \
    chmod +x start.sh entrypoint.sh

# Change ownership of the app tree to appuser. The Railway volume mount at
# /data/uploads is owned by root and entrypoint.sh fixes that at runtime
# (Phase 26 B1).
RUN chown -R appuser:appuser /app

# Phase 26 B1: container starts as root so entrypoint.sh can chown the
# /data/uploads volume mount; it then drops to appuser via gosu before
# exec-ing start.sh. Healthcheck still runs as the container's effective
# user — once start.sh is running under appuser, curl is unaffected by
# the brief root window at startup.

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["./entrypoint.sh"]
