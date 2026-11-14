FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 libsqlite3-dev curl net-tools && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8099
ENV PYTHONUNBUFFERED=1

EXPOSE 8099

CMD ["python3", "app.py"]
