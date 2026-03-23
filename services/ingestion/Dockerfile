FROM python:3.12-slim

WORKDIR /app

COPY shared/requirements.txt /app/shared/requirements.txt
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

COPY services/ingestion/requirements.txt /app/services/ingestion/requirements.txt
RUN pip install --no-cache-dir -r /app/services/ingestion/requirements.txt
RUN python -m spacy download en_core_web_sm

COPY shared/ /app/shared/
COPY services/__init__.py /app/services/__init__.py
COPY services/ingestion/ /app/services/ingestion/

ENV PYTHONPATH=/app

CMD ["python", "-m", "services.ingestion.main"]
