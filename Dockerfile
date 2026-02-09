FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# Data volume for SQLite persistence
VOLUME /app/data

CMD ["python", "bot.py"]
