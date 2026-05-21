# Handoff: Realtime Fraud Detection Attack/Defense Lab

Last updated: 2026-05-21

## Goal

AI 해킹/보안 교육용 금융거래 이상탐지 샌드박스를 구축했다. 공격자는 라벨 없는 거래 데이터를 주입해 모델 경계, pseudo-label, 재학습 흐름을 흔들고, 방어자는 수동 라벨/로그/모델 업데이트 정보를 통해 모델과 정책을 강화하는 구성을 목표로 한다.

## Current Status

- FastAPI 기반 실시간 이상거래 탐지 서비스 구현 완료.
- 스키마 기반 금융거래 데이터 contract 적용.
- 실시간 거래 생성 봇은 `world_bot`으로 구현.
- 수동 거래 입력 UI, 거래 목록 UI, 모델 업데이트 로그, 학습 로그, 공격/방어 로그, MCP 스타일 보안 액션 로그 UI 구현.
- 공격자/방어자 관점의 모델 업데이트 정보와 강건성 로그 자동 생성.
- `seonhak123/Credit-Card-Fraud-Detection` 참고 레포를 `model/Credit-Card-Fraud-Detection/`에 클론하고, 우리 시스템 스키마에 맞는 Python 학습 스크립트로 포팅.

## Important Design Decision

운영 거래 생성자는 정답 라벨을 넣지 않는다.

- `POST /api/transactions`, `POST /api/simulate`, `world_bot` 거래는 `label = null`로 저장된다.
- payload에 `is_fraud`가 들어와도 거래 저장 전에 제거된다.
- 학습 라벨은 trusted seed, 방어자 수동 피드백, 명시된 pseudo-label 정책에서만 생긴다.
- 오프라인 학습용 synthetic CSV에는 `is_fraud` 라벨이 들어간다. 이 데이터는 모델 사전학습/검증용이다.

## Main Files

- `fraud_lab/main.py`: API, bot, retrain flow, model/log orchestration.
- `fraud_lab/modeling.py`: schema-driven feature extraction, supervised/unsupervised model manager, robustness report.
- `fraud_lab/simulator.py`: realistic synthetic financial transaction generator.
- `configs/schemas/kaggle_fraud_transactions.json`: current transaction schema.
- `static/index.html`, `static/app.js`, `static/styles.css`: browser UI.
- `model/transaction_fraud_model.py`: synthetic dataset generation, shard generation, sampled training, candidate model comparison.
- `model/Credit-Card-Fraud-Detection/`: cloned reference model repo.
- `README.md`: setup, schema, label policy, model porting, large dataset generation commands.

## Model Port

Reference repo:

- `https://github.com/seonhak123/Credit-Card-Fraud-Detection`

Original reference model uses `Time`, `Amount`, `V1`...`V28`, `Class`. That column set is not useful for this lab UI, so the training recipe was ported instead:

- robust scaling
- SMOTE imbalance handling
- RandomForest tuned params from the reference repo
- additional candidates: ExtraTrees, HistGradientBoosting, LogisticRegression
- AUPRC-first validation
- threshold tuning using validation precision-recall curve

## Latest 3,000 Row Training Result

Command:

```bash
python model/transaction_fraud_model.py \
  --input-dir data/generated/synthetic_financial_transactions_100000000 \
  --sample-rows 3000 \
  --sample-scan-rows 1000000 \
  --output-dir data/generated/training_3000_from_shards \
  --artifact-path data/models/financial_anomaly_3000_from_generated.joblib
```

Result:

- selected model: `hist_gradient_boosting`
- sample rows: `3000`
- class balance: normal `2737`, fraud `263`
- AUPRC: `0.8044`
- precision: `0.9200`
- recall: `0.6970`
- F1: `0.7931`
- ROC-AUC: `0.9343`
- decision threshold: `0.517272`

Compared models:

- `hist_gradient_boosting`: AUPRC `0.8044`, F1 `0.7931`
- `random_forest`: AUPRC `0.6993`, F1 `0.6415`
- `extra_trees`: AUPRC `0.5563`, F1 `0.5714`
- `logistic_regression`: AUPRC `0.5289`, F1 `0.5190`

The trained artifact is local only and ignored by Git:

- `data/models/financial_anomaly_3000_from_generated.joblib`

## Local Large Dataset State

A large synthetic generation run was started toward `100,000,000` rows and stopped at the user's request.

Clean local result:

- directory: `data/generated/synthetic_financial_transactions_100000000/`
- complete shards: `38`
- rows per shard: `1,000,000`
- complete rows: about `38,000,000`
- size: about `2.8GB`
- partial shard was removed after validation.

This dataset is intentionally ignored by Git and is not pushed to GitHub.

Generate more shards later:

```bash
python model/transaction_fraud_model.py \
  --generate-only \
  --rows 100000000 \
  --fraud-rate 0.08 \
  --shard-rows 1000000 \
  --progress-every 1000000
```

Train from existing shards:

```bash
python model/transaction_fraud_model.py \
  --input-dir data/generated/synthetic_financial_transactions_100000000 \
  --sample-rows 3000 \
  --sample-scan-rows 1000000
```

Increase `--sample-rows` and `--sample-scan-rows` for broader training.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn fraud_lab.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

## Verification

Previously verified during this handoff:

```bash
python -m compileall fraud_lab model/transaction_fraud_model.py
pytest -q
```

Recent observed test result:

```text
1 passed
```

Note: the FastAPI integration test can take about 70 seconds because startup/retrain paths train real models.

## Next Work

- Add batch scoring over the remaining local shard dataset.
- Add active-learning queue: high uncertainty transactions should request defender labels.
- Add incremental/continual training snapshots from shard samples.
- Add drift reports comparing current stream vs synthetic baseline.
- Add model artifact registry metadata in the UI.
- Consider replacing the current educational model with a larger online-learning capable model if true continual learning is required.

