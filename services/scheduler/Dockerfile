FROM python:3.12-slim

WORKDIR /app

# Shared dependencies
COPY shared/requirements.txt /app/shared/requirements.txt
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

# Scheduler-specific dependencies
COPY services/scheduler/requirements.txt /app/services/scheduler/requirements.txt
RUN pip install --no-cache-dir -r /app/services/scheduler/requirements.txt

# Install spaCy model AFTER spacy is installed
RUN python -m spacy download en_core_web_sm

# Copy shared code
COPY shared/ /app/shared/
COPY services/__init__.py /app/services/__init__.py

# Copy ALL service code (scheduler imports from ingestion, agents, feedback, signals)
COPY services/scheduler/ /app/services/scheduler/
COPY services/ingestion/ /app/services/ingestion/
COPY services/agents/ /app/services/agents/
COPY services/feedback/ /app/services/feedback/
COPY services/signals/ /app/services/signals/
COPY services/verification/ /app/services/verification/
COPY services/api/ /app/services/api/

# Copy prompts and migrations
COPY prompts/ /app/prompts/
COPY alembic.ini /app/alembic.ini
COPY migrations/ /app/migrations/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "services.scheduler.main"]
