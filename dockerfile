FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY abs_dreimetadata.py .

EXPOSE 5000

CMD ["python", "abs_dreimetadata.py"]