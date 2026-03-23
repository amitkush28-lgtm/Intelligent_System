FROM python:3.12-slim

WORKDIR /app

# Install shared dependencies first (cache layer)
COPY shared/requirements.txt /app/shared/requirements.txt
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

# Install service dependencies
COPY services/api/requirements.txt /app/services/api/requirements.txt
RUN pip install --no-cache-dir -r /app/services/api/requirements.txt

# Copy shared library
COPY shared/ /app/shared/

# Copy service package init (required for services.api.* imports)
COPY services/__init__.py /app/services/__init__.py

# Copy service code
COPY services/api/ /app/services/api/

# Copy prompts (needed by chat endpoint)
COPY prompts/ /app/prompts/

# Copy alembic for migrations
COPY alembic.ini /app/
COPY migrations/ /app/migrations/

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
