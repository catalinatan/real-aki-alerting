# AKI Inference Service

Real-time acute kidney injury (AKI) detection for hospital lab streams.

## What it does

Consumes HL7v2 ADT and ORU messages over MLLP, maintains a per-patient
creatinine history in SQLite, and runs a gradient-boosted classifier on each
new result. Positive predictions trigger an HTTP page to the clinical response
team.

## Tech stack

- Python 3.13, `asyncio`
- `hl7` (HL7v2 parsing), `scikit-learn` (`GradientBoostingClassifier`),
  `pandas`, `numpy`
- SQLite (WAL mode) for patient state
- Docker (Ubuntu `noble` base)
- `pytest` for unit and integration tests

## How to run

### Local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

### Docker

```bash
docker build -t aki-service .
docker run --rm \
  -e MLLP_ADDRESS=host.docker.internal:8440 \
  -e PAGER_ADDRESS=host.docker.internal:8441 \
  aki-service
```

### Simulator (for local testing)

```bash
docker build -t aki-simulator ./simulator
docker run --rm -p 8440:8440 -p 8441:8441 aki-simulator
```

### Configuration

| Variable       | Default               | Purpose              |
| -------------- | --------------------- | -------------------- |
| `MLLP_ADDRESS` | `localhost:8440`      | HL7 source           |
| `PAGER_ADDRESS`| `localhost:8441`      | Pager HTTP endpoint  |
| `DB_PATH`      | `data/patient.db`     | SQLite file          |
| `HISTORY_CSV`  | `data/history.csv`    | Bootstrap history    |
| `TRAINING_CSV` | `data/training.csv`   | Model training data  |
| `LOG_LEVEL`    | `INFO`                | Log verbosity        |

### Tests

```bash
pytest tests/
```

## Key results / metrics

_To be populated once benchmarks are run on the holdout set._

- Classification: F3 score on holdout set — _TBD_
- End-to-end latency (ORU receipt → pager POST): p50 / p95 — _TBD_
- Sustained throughput (messages/sec) — _TBD_

## Data

`data/history.csv` and `data/training.csv` are synthetic coursework fixtures —
no real patient data is committed to the repository. The simulator ships with
a fixed replay of HL7 messages in `simulator/messages.mllp`.
