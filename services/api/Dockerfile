FROM python:3.12-slim

WORKDIR /app

# Install shared dependencies first (cache layer)
COPY shared/requirements.txt /app/shared/requirements.txt
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

# Install service dependencies (includes all worker deps for trigger routes)
COPY services/api/requirements.txt /app/services/api/requirements.txt
RUN pip install --no-cache-dir -r /app/services/api/requirements.txt

# Download spaCy model for ingestion
RUN python -m spacy download en_core_web_sm

# Copy shared library
COPY shared/ /app/shared/

# Copy service package init
COPY services/__init__.py /app/services/__init__.py

# Copy ALL services (needed for trigger routes to run pipelines in-process)
COPY services/api/ /app/services/api/
COPY services/ingestion/ /app/services/ingestion/
COPY services/agents/ /app/services/agents/
COPY services/feedback/ /app/services/feedback/
COPY services/signals/ /app/services/signals/
COPY services/verification/ /app/services/verification/

# Copy prompts (needed by agents and chat endpoint)
COPY prompts/ /app/prompts/

# Copy alembic for migrations
COPY alembic.ini /app/
COPY migrations/ /app/migrations/

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
