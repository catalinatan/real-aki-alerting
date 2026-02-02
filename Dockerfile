FROM ubuntu:noble
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -yq install python3-pip python3-venv

WORKDIR /app
RUN python3 -m venv /app

COPY requirements.txt ./
RUN /app/bin/pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY data/training.csv /app/data/training.csv
COPY main.py ./main.py

ENV PYTHONUNBUFFERED=1 \
    HISTORY_CSV=/data/history.csv \
    TRAINING_CSV=/app/data/training.csv

ENTRYPOINT ["/app/bin/python", "main.py"]

