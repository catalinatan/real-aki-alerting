FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    MLLP_ADDRESS=localhost:8440 \
    PAGER_ADDRESS=localhost:8441 \
    HISTORY_CSV=/data/history.csv \
    TRAINING_CSV=/data/training.csv

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY data/training.csv /data/training.csv
COPY main.py ./main.py

ENTRYPOINT ["python", "main.py"]
