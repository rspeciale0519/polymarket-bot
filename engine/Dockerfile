FROM python:3.12-slim

WORKDIR /app

# Install netcat for wait-for-db script
RUN apt-get update && apt-get install -y --no-install-recommends netcat-openbsd && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (cached layer)
COPY engine/requirements.txt /app/engine/requirements.txt
RUN pip install --no-cache-dir -r /app/engine/requirements.txt

# Copy project code
COPY engine/ /app/engine/
COPY scripts/ /app/scripts/
COPY tests/ /app/tests/

# Wait-for-db entrypoint
RUN printf '#!/bin/bash\nset -e\nHOST="${DB_HOST:-postgres}"\nPORT="${DB_PORT:-5432}"\necho "Waiting for PostgreSQL at $HOST:$PORT..."\nwhile ! nc -z "$HOST" "$PORT" 2>/dev/null; do sleep 1; done\necho "PostgreSQL is ready."\nexec "$@"\n' > /usr/local/bin/wait-for-db.sh && chmod +x /usr/local/bin/wait-for-db.sh

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

ENTRYPOINT ["wait-for-db.sh"]
CMD ["python", "-m", "engine.main"]
