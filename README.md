# Realtime Transition Agent Fraud Lab

AI 해킹/보안 교육용으로 만든 실시간 이상거래 탐지 샌드박스입니다. 하나의 이상탐지 모델을 두고 공격팀은 모델 업데이트 정보를 보고 우회/오염/드리프트 시나리오를 실험하고, 방어팀은 로그·라벨·MCP 액션을 보면서 모델과 정책을 강화하는 흐름을 연습할 수 있습니다.

## 포함된 기능

- 금융거래 이상탐지 모델: 스키마 기반 파생 피처와 `RandomForestClassifier` supervised baseline, 라벨 부족 시 `IsolationForest` fallback
- 계속 재학습: trusted seed 데이터, 관리자 정답 라벨 공개, 고신뢰 pseudo label을 재학습 로그와 함께 저장
- 유연한 데이터 스키마: `configs/schemas/kaggle_fraud_transactions.json` 수정만으로 입력 UI와 학습 피처 변경
- 거래 생성 UI: 실시간 거래 봇, 수동 폼, 일괄 시뮬레이터
- 로그 UI: 거래 판정 로그, 학습에 사용된 데이터 로그, 모델 업데이트/강건성 로그, 공격/방어 로그
- 공격팀 인텔: 최신 모델 버전, 임계값, 주요 피처, 샌드박스 공격 카드
- 방어팀/MCP 환경: 위험 판정에 따라 계정 검토·정지·복구 액션을 로컬 MCP 스타일 커넥터로 실행

## 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn fraud_lab.main:app --reload --host 127.0.0.1 --port 8000
```

브라우저에서 `http://127.0.0.1:8000`을 열면 됩니다. 최초 실행 시 Kaggle 형식의 synthetic seed 거래가 생성되고 모델이 학습됩니다.

## 테스트

```bash
pytest
```

## 스키마 교체

컬럼 구조는 `configs/schemas/kaggle_fraud_transactions.json`가 담당합니다.

- `fields[].role = "feature"`: 모델 학습/추론에 사용
- `fields[].role = "entity"` 또는 `train = false`: 계정 ID처럼 정책/로그에는 쓰지만 학습에서는 제외
- `target`: 라벨 컬럼 이름
- `decision.review_threshold`, `decision.block_threshold`: 검토/차단 임계값
- `retrain.*`: 재학습 주기, 최소 라벨 수, pseudo label 정책
- `derived_features`: 스키마 기반 파생 피처. 현재는 고객-상점 거리와 잔액 차이를 생성합니다.

기본 스키마는 Kaggle `fraud transactions dataset`의 해석 가능한 컬럼을 기준으로 잡았습니다.

- source: `https://www.kaggle.com/datasets/dermisfit/fraud-transactions-dataset`
- 주요 컬럼: `trans_date_trans_time`, `cc_num`, `merchant`, `category`, `amt`, `gender`, `city`, `state`, `zip`, `lat`, `long`, `city_pop`, `job`, `dob`, `trans_num`, `unix_time`, `merch_lat`, `merch_long`, `is_fraud`
- 학습 파생 피처: 거래 시간대/요일/월/주말, 고객 나이, 고객-상점 거리, 잔액 차이

다른 Kaggle 신용카드/이상거래 데이터로 바꾸려면 이 JSON을 새 데이터셋 형태에 맞게 바꾸고, 필요한 경우 `fraud_lab/simulator.py`의 생성 규칙만 함께 바꾸면 됩니다. DB와 로그는 `schema_id`별로 분리됩니다.

## 라벨 정책

거래 생성자는 정답 라벨을 넣지 않습니다.

- `POST /api/transactions`, `POST /api/simulate`, 실시간 `world_bot` 거래는 모두 `label = null`로 저장됩니다.
- `is_fraud` 같은 target 컬럼을 payload에 넣어도 거래 저장 전에 제거됩니다.
- 모델 학습 라벨은 초기 trusted seed 데이터, 방어자 수동 피드백, 또는 명시적으로 표시된 고신뢰 pseudo label에서만 생깁니다.
- 공격자는 라벨 없는 거래를 주입해 모델 경계와 pseudo-label 정책을 흔드는 역할을 하고, 방어자는 거래 목록에서 라벨 피드백과 재학습 로그로 대응합니다.

## 실생활 거래 봇

`world_bot`은 기본적으로 오프라인 synthetic CSV shard를 시간순으로 읽어서 운영 거래처럼 조금씩 공개합니다. 배포 환경에서는 `FRAUD_LAB_BOT_AUTO_START=true`, `FRAUD_LAB_BOT_INTERVAL_SECONDS=0.5`, `FRAUD_LAB_BOT_BATCH_SIZE=1`, `FRAUD_LAB_BOT_RANDOM_INTERVAL=true`로 서버 시작 시 자동 실행되고 평균 초당 2건을 자연스러운 랜덤 간격으로 공개합니다. 현재 운영 replay는 호스트 로컬 1,000만건 고정 dataset을 read-only mount로 읽고, `FRAUD_LAB_BOT_LOOP_DATASET=false`라 끝까지 읽으면 정지합니다. CSV에는 `is_fraud` 라벨이 있지만, 봇은 이 값을 버리고 payload만 `label = null` 운영 거래로 저장합니다. 봇 시작/정지는 `FRAUD_LAB_ADMIN_PASSWORD`로 보호됩니다.

CSV가 없을 때 테스트용으로 `stream_mode = synthetic`을 쓰면 즉석 생성 모드로 동작합니다. 이때 `suspicious_rate`는 라벨이 아니라 의심스러운 거래 패턴이 섞이는 비율입니다.

UI 상단에는 거래 발생 수, 이상거래 탐지율, 정답 공개 수, 모델 일치율, 공격 성공률을 표시합니다. 공격 성공률은 공개된 실제 사기 거래 중 모델이 정상으로 놓친 비율입니다.

UI의 거래 탭에는 최근 초 단위 유입량 그래프와 라벨 공개 비교 그래프가 있습니다. 비교 그래프는 dataset replay의 숨겨진 `is_fraud`를 별도 truth table에 보관하고, 관리자가 공개한 row만 모델 예측과 집계 비교합니다. 정답 라벨 공개는 관리자 탭의 `정답 라벨 일괄 부여` 버튼으로만 수행되며, 클릭 시 그 시점까지 봇이 공개한 전체 모집단 거래에 정답 라벨과 공개 시간이 함께 기록됩니다.

관리자 탭에서는 현재 스키마와 호환되는 joblib 모델 artifact를 업로드해 즉시 새 모델 버전으로 전환할 수 있습니다. 업로드 artifact는 `{pipeline, metadata, schema}` 구조를 권장하며, `model/transaction_fraud_model.py`가 생성하는 artifact와 호환됩니다.

## 포팅한 모델 학습

참고 모델은 `model/Credit-Card-Fraud-Detection/`에 클론했고, 우리 시스템 스키마에 맞춘 실행형 포팅 스크립트는 `model/transaction_fraud_model.py`입니다. 원본 레포의 핵심 흐름인 robust scaling, SMOTE, RandomForest 튜닝 파라미터, AUPRC 평가를 `configs/schemas/kaggle_fraud_transactions.json` 기반 feature extraction에 연결했습니다.

```bash
python model/transaction_fraud_model.py --rows 5000 --fraud-rate 0.08
```

이 명령은 `data/generated/synthetic_financial_transactions.csv` 학습용 CSV와 `data/models/ported_transaction_fraud_model.joblib` 모델 artifact를 만듭니다. 학습용 CSV에는 라벨이 있지만, 실시간 봇/시뮬레이터/수동 UI로 들어오는 운영 거래에는 라벨을 저장하지 않습니다.

이미 생성된 shard 데이터에서 일부만 뽑아 모델을 학습할 수도 있습니다.

```bash
python model/transaction_fraud_model.py \
  --input-dir data/generated/synthetic_financial_transactions_100000000 \
  --sample-rows 3000 \
  --sample-scan-rows 1000000
```

이 모드는 입력 shard를 reservoir sampling으로 읽기 때문에, 지금은 3,000개 샘플 학습에 쓰고 나머지 대용량 shard는 이후 지속 학습, drift 평가, batch scoring, active-learning 라벨 큐에 그대로 사용할 수 있습니다.

대용량 학습 데이터만 만들 때는 메모리에 올리지 않는 shard 모드를 사용합니다.

```bash
python model/transaction_fraud_model.py \
  --generate-only \
  --rows 3000 \
  --fraud-rate 0.018 \
  --shard-rows 3000 \
  --shard-dir data/generated/realtime_financial_transactions_3000 \
  --profile-count 3000 \
  --start-at "2025-01-01 00:00:00" \
  --days 7 \
  --progress-every 1000
```

기본 출력은 `part-*.csv.gz`와 `manifest.json`입니다. manifest 경로를 `FRAUD_LAB_STREAM_DATASET_MANIFEST`에 넣으면 봇이 해당 shard를 replay합니다.

현재 배포 앱은 1,000만건 고정 replay dataset을 사용합니다. 전체 데이터셋은 호스트 로컬 `data/generated/realtime_financial_transactions_10000000/`에 shard로 보관하고, 사람이 확인하기 쉬운 단일 CSV는 `data/generated/realtime_financial_transactions_10000000.csv`에 둡니다. 두 경로 모두 GitHub에는 올리지 않습니다. 원본 shard, manifest, 단일 CSV는 read-only로 잠갔고 checksum은 `data/generated/realtime_financial_transactions_10000000/SHA256SUMS.txt`, `data/generated/realtime_financial_transactions_10000000.csv.sha256`에 저장했습니다.

현재 도메인 배포는 `https://caulab.hacktheworldtest.xyz`에서 Nginx가 Docker 컨테이너의 `127.0.0.1:18000`으로 프록시합니다.

## 공격/방어 로그

모델이 업데이트될 때마다 `red_blue_events` 로그가 자동으로 남습니다.

- 공격 방법: threshold probing, low-and-slow amount splitting, geo-distance evasion, label-noise poisoning
- 강건성 향상: schema contract audit, class imbalance aware baseline, poisoning/drift monitoring, MCP action separation

## 주요 API

- `GET /api/schema`: 현재 데이터 스키마
- `POST /api/transactions`: 거래 생성 및 모델 판정
- `POST /api/transactions/{id}/label`: 관리자 API 전용 단건 라벨 피드백. 웹 UI에서는 제공하지 않습니다.
- `GET /api/bot/status`: 실시간 거래 봇 상태
- `POST /api/bot/start`: 실시간 거래 봇 시작, `admin_password` 필요
- `POST /api/bot/stop`: 실시간 거래 봇 정지, `admin_password` 필요
- `POST /api/admin/labels/reveal`: 관리자 전용. 그 시점까지 공개된 전체 거래에 숨겨진 정답 라벨을 일괄 부여
- `POST /api/admin/model/upload`: 관리자 전용. 호환 모델 artifact 업로드 및 모델 버전 전환
- `GET /api/realtime-transactions.csv`: 최신 실시간 거래와 모델 판단 결과를 CSV로 export. 공개된 정답은 `truth_label`, 공개 시점은 `truth_revealed_at`에 표시하며, export는 최대 3,000건으로 제한합니다.
- `POST /api/simulate`: 거래 스트림 일괄 생성
- `POST /api/admin/retrain`: 즉시 재학습
- `GET /api/model/updates`: 모델 업데이트 로그
- `GET /api/model/attacker-intel`: 공격팀용 업데이트 인텔
- `GET /api/logs/training`: 학습 데이터 이벤트 로그
- `GET /api/logs/red-blue`: 공격/방어 로그
- `POST /mcp`: JSON-RPC 스타일 MCP 도구 호출

## MCP 예시

```bash
curl -s http://127.0.0.1:8000/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

```bash
curl -s http://127.0.0.1:8000/mcp \
  -H 'content-type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":2,
    "method":"tools/call",
    "params":{
      "name":"flag_for_review",
      "arguments":{
        "account_id":"acct-demo-001",
        "risk_score":0.72,
        "reason":"manual lab call"
      }
    }
  }'
```

## 저장 위치

- SQLite DB: `data/fraud_lab.sqlite3`
- 모델 artifact: `data/models/fraud_model_v*.joblib`
- 스키마: `configs/schemas/kaggle_fraud_transactions.json`
