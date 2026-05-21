# Credit-Card-Fraud-Detection

## Dataset
[Credit Card Fraud Detection](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud)

본 프로젝트에서 사용된 creditcard.csv 파일은 용량 문제로 레포지토리에 포함하지 않았습니다. 


해당 링크에서 다운로드하여 소스 코드와 동일한 폴더에 배치해 주시기 바랍니다.

## Environment & Setup
* **Operating System**: Ubuntu 22.04.5 LTS (Google Colab Environment)
* **Python Version**: 3.12.13
* **Installation**: 
    ```bash
    pip install -r requirements.txt
    ```

## 과정
### 1. 데이터 탐색 및 전처리 (EDA & Scaling)

EDA: 타겟 변수인 Class 분포 분석을 통해 데이터 불균형 상태(0.17%)를 확인


Scaling: Amount(거래 금액)와 Time(시간) 변수에 대해 RobustScaler를 적용하여 정규화



### 2. 클래스 불균형 해결 (SMOTE)

모델이 사기 패턴을 충분히 학습할 수 있도록 SMOTE 기법 사용


학습 데이터 내 사기/정상 비율을 5:5로 조정하여 불균형 해결



### 3. 모델링 및 성능 비교

사용 모델: Linear Classification, RandomForest, XGBoost, LightGBM  


평가지표: 불균형 데이터셋에 가장 적합한 AUPRC(Area Under the Precision-Recall Curve)를 주지표로 선정




최적 후보 모델 선별 : Random Forest, XGBoost


RF_AUPRC : 0.8274


XGB_AUPRC : 0.8249



### 4. 하이퍼파라미터 최적화 (Optuna)
Optuna 라이브러리를 활용 최적 후보 모델에 대한 파라미터 튜닝을 수행

RandomForest (AUPRC: 0.8140)


{n_estimators: 495, max_depth: 9, min_samples_split: 5, min_samples_leaf: 6, criterion: 'entropy'}




XGBoost (AUPRC: 0.8341)


{n_estimators: 455, max_depth: 9, learning_rate: 0.089, subsample: 0.775, scale_pos_weight: 3.47}



### 5. 앙상블(Voting & Stacking)

Voting과 Stacking 기법을 적용하여 모델의 일반화 성능 향상을 시도




voting : Random Forest 모델과 XGBoost 모델을 0.3, 0.7의 가중치로 soft voting 진행



### 6. 피처 선택(Feature Selection)

Feature Selection: 상관관계 절댓값 기준 하위 5개 컬럼을 노이즈로 판단하여 드롭 후 모델링 진행

AUPRC : 0.8411
