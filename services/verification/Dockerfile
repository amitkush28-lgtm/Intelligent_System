FROM python:3.12-slim

WORKDIR /app

COPY shared/requirements.txt /app/shared/requirements.txt
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

COPY services/verification/requirements.txt /app/services/verification/requirements.txt
RUN pip install --no-cache-dir -r /app/services/verification/requirements.txt

COPY shared/ /app/shared/
COPY services/__init__.py /app/services/__init__.py
COPY services/verification/ /app/services/verification/

ENV PYTHONPATH=/app

CMD ["python", "-m", "services.verification.main"]
