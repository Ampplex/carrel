# Carrel's API. Shares a box with a production MCP server, so this image is
# built to be small and to stay out of that server's way.
FROM python:3.11-slim

# Layer caching: dependencies change rarely, application code changes often.
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . && rm -rf /root/.cache

COPY app ./app
COPY scripts ./scripts

# Non-root. The container reaches Postgres and S3 and nothing on the host; there
# is no reason for it to run with more than that.
RUN useradd --create-home --uid 10002 carrel && chown -R carrel:carrel /app
USER carrel

EXPOSE 8010

# One worker on purpose. The box has ~1GB of RAM to spare and each worker holds
# its own Reeve SSE session and Postgres pool; more workers would multiply both
# for a service whose bottleneck is a remote call, not local CPU.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1"]
