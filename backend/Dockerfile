FROM python:3.11-slim

ARG AGE_VERSION=1.3.1
ARG AGE_LINUX_AMD64_SHA256=bdc69c09cbdd6cf8b1f333d372a1f58247b3a33146406333e30c0f26e8f51377

# Install system dependencies for psycopg2 plus PostgreSQL 18 client tools.
# gosu is used by entrypoint.sh (Phase 26 B1) to drop privileges from root
# to appuser after fixing volume-mount ownership.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg libpq-dev gcc gosu && \
    install -d /usr/share/postgresql-common/pgdg && \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc && \
    . /etc/os-release && \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client-18 && \
    rm -rf /var/lib/apt/lists/*

# Phase 98: install the official, checksum-pinned age binary.  Production gets
# only an age recipient; age-keygen ships for disposable test-key generation
# and restore operators but no private identity is embedded in the image.
RUN test "$(dpkg --print-architecture)" = "amd64" && \
    curl -fsSLo /tmp/age.tar.gz \
      "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/age-v${AGE_VERSION}-linux-amd64.tar.gz" && \
    echo "${AGE_LINUX_AMD64_SHA256}  /tmp/age.tar.gz" | sha256sum -c - && \
    tar -xzf /tmp/age.tar.gz -C /tmp && \
    install -m 0755 /tmp/age/age /usr/local/bin/age && \
    install -m 0755 /tmp/age/age-keygen /usr/local/bin/age-keygen && \
    rm -rf /tmp/age /tmp/age.tar.gz && \
    pg_dump --version | grep -Eq ' 18([.]|$)' && \
    pg_restore --version | grep -Eq ' 18([.]|$)' && \
    age --version | grep -Eq "v?${AGE_VERSION}"

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
