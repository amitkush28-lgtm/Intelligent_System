FROM python:3.12-slim

WORKDIR /app

COPY shared/requirements.txt /app/shared/requirements.txt
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

COPY services/signals/requirements.txt /app/services/signals/requirements.txt
RUN pip install --no-cache-dir -r /app/services/signals/requirements.txt

COPY shared/ /app/shared/
COPY services/__init__.py /app/services/__init__.py
COPY services/signals/ /app/services/signals/

ENV PYTHONPATH=/app

CMD ["python", "-m", "services.signals.main"]
