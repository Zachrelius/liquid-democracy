FROM python:3.11-slim

# Install system dependencies for psycopg2
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev gcc curl && \
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

# Fix Windows CRLF line endings in shell scripts and config files
RUN find . -type f \( -name "*.sh" -o -name "*.ini" -o -name "*.cfg" -o -name "*.py" -o -name "*.txt" -o -name "*.mako" \) -exec sed -i 's/\r$//' {} + && \
    chmod +x start.sh

# Change ownership to non-root user
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["./start.sh"]
