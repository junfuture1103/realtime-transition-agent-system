# Realtime Transition Agent Fraud Lab

AI 해킹/보안 교육용으로 만든 실시간 이상거래 탐지 샌드박스입니다. 하나의 이상탐지 모델을 두고 공격팀은 모델 업데이트 정보를 보고 우회/오염/드리프트 시나리오를 실험하고, 방어팀은 로그·라벨·MCP 액션을 보면서 모델과 정책을 강화하는 흐름을 연습할 수 있습니다.

## 포함된 기능

- 금융거래 이상탐지 모델: 스키마 기반 파생 피처와 `RandomForestClassifier` supervised baseline, 라벨 부족 시 `IsolationForest` fallback
- 계속 재학습: 스트림 거래, 수동 라벨, 시뮬레이터 ground truth, 고신뢰 pseudo label을 재학습 로그와 함께 저장
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

## 공격/방어 로그

모델이 업데이트될 때마다 `red_blue_events` 로그가 자동으로 남습니다.

- 공격 방법: threshold probing, low-and-slow amount splitting, geo-distance evasion, label-noise poisoning
- 강건성 향상: schema contract audit, class imbalance aware baseline, poisoning/drift monitoring, MCP action separation

## 주요 API

- `GET /api/schema`: 현재 데이터 스키마
- `POST /api/transactions`: 거래 생성 및 모델 판정
- `POST /api/transactions/{id}/label`: 수동 라벨 피드백
- `GET /api/bot/status`: 실시간 거래 봇 상태
- `POST /api/bot/start`: 실시간 거래 봇 시작
- `POST /api/bot/stop`: 실시간 거래 봇 정지
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
