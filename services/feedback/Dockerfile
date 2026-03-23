FROM python:3.12-slim

WORKDIR /app

COPY shared/requirements.txt /app/shared/requirements.txt
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

COPY services/feedback/requirements.txt /app/services/feedback/requirements.txt
RUN pip install --no-cache-dir -r /app/services/feedback/requirements.txt

COPY shared/ /app/shared/
COPY services/__init__.py /app/services/__init__.py
COPY services/feedback/ /app/services/feedback/

ENV PYTHONPATH=/app

CMD ["python", "-m", "services.feedback.main"]
