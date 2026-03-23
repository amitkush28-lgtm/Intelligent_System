FROM python:3.12-slim

WORKDIR /app

COPY shared/requirements.txt /app/shared/requirements.txt
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

COPY services/agents/requirements.txt /app/services/agents/requirements.txt
RUN pip install --no-cache-dir -r /app/services/agents/requirements.txt

COPY shared/ /app/shared/
COPY services/__init__.py /app/services/__init__.py
COPY services/agents/ /app/services/agents/

# Prompts directory (optional — agents have prompts built in, but external
# prompts can override via the agent_prompts database table)
COPY prompts/ /app/prompts/

ENV PYTHONPATH=/app

CMD ["python", "-m", "services.agents.main"]
