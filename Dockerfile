FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=5000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY abs_dreimetadata.py .

# Python als PID 1 reagiert nicht auf SIGTERM - SIGINT beendet waitress sauber
STOPSIGNAL SIGINT

# Nicht als root laufen
USER nobody

EXPOSE 5000

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=5)"

CMD ["python", "abs_dreimetadata.py"]
