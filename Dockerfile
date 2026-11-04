FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY frontend ./frontend
# The database lives in /data. Mount a persistent disk or volume there, or accounts and listings are lost on every redeploy.
ENV BHOJAN_DB=/data/bhojanchain.db BHOJAN_SEED=0 PYTHONUNBUFFERED=1
RUN mkdir -p /data
WORKDIR /app/backend
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
