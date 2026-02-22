# SWEMLS Coursework 6 (Huashan)

This repository runs the AKI detection service for Coursework 6 using Kubernetes.

Single source of truth: `deployment.yaml`

## Exam-Day Checklist (Quick Start, beginner-friendly)

Run these in order.

1) Build the app image
```bash
docker build -t imperialswemlsspring2026.azurecr.io/coursework6-huashan .
```

2) Push the image to the registry (so Kubernetes can pull it)
```bash
docker push imperialswemlsspring2026.azurecr.io/coursework6-huashan
```

3) Apply Kubernetes config from this repo
```bash
kubectl apply -f deployment.yaml
```

4) Wait until deployment is healthy
```bash
kubectl -n huashan rollout status deployment/aki-detection --timeout=120s
```
Expected: message like `successfully rolled out`

5) Follow live app logs
```bash
kubectl -n huashan logs -f deployment/aki-detection -c aki-detection
```
Expected: regular processing lines (for example, inserted creatinine records).

Quick health checks (copy/paste):

```bash
kubectl -n huashan get pods -l app=aki-detection -o wide
kubectl -n huashan get events --sort-by=.lastTimestamp | tail -n 20
```

If rollout is stuck (plain check first):

```bash
kubectl -n huashan describe deployment aki-detection | grep -E "ProgressDeadlineExceeded|ReplicaFailure|FailedCreate"
kubectl -n huashan get events --sort-by=.lastTimestamp | tail -n 40
# Optional safe nudge (brief interruption, pod recreated automatically):
kubectl -n huashan delete pod -l app=aki-detection
```

What “safe nudge” means: delete the current pod so Kubernetes recreates it cleanly. This causes a brief interruption but often clears transient runtime/network issues.

## Metrics check

```bash
POD=$(kubectl -n huashan get pods -l app=aki-detection -o jsonpath='{.items[0].metadata.name}')
kubectl -n huashan port-forward "$POD" 8000:8000
curl -s localhost:8000/metrics | head -n 80
```

Watch these first:
- `messages_received_total`
- `blood_tests_received_total`
- `aki_predictions_total`
- `pages_sent_total`
- `pager_errors_total`
- `mllp_reconnections_total`

## What is preconfigured in deployment.yaml

- Namespace: `huashan`
- Coursework 6 simulator endpoints:
	- `MLLP_ADDRESS=huashan-simulator.coursework6:8440`
	- `PAGER_ADDRESS=huashan-simulator.coursework6:8441`
- History init image: `imperialswemlsspring2026.azurecr.io/coursework6-history`
- Quota-safe rollout: `maxSurge: 0`, `maxUnavailable: 1`

## Common log message (usually okay)

`MLLP read timed out — connection may be dead.` can be normal if it is followed by reconnect and processing continues.
