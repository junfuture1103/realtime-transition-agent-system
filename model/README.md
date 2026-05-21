# Model Porting Workspace

`Credit-Card-Fraud-Detection/` contains a local copy of the reference project from
`https://github.com/seonhak123/Credit-Card-Fraud-Detection`.

The original project uses the ULB/Kaggle credit card dataset columns
`Time`, `Amount`, `V1`...`V28`, and `Class`. Those PCA-style columns are not
the transaction contract used by this lab, so `transaction_fraud_model.py`
ports the training recipe instead of the raw column set:

- synthetic transaction generation with the lab schema
- `FeatureSchema` driven feature extraction
- robust scaling
- optional SMOTE for class imbalance
- Random Forest using the reference project's tuned parameters
- AUPRC-first validation

Run it from the repository root:

```bash
python model/transaction_fraud_model.py --rows 5000 --fraud-rate 0.08
```

Generated training data is written to `data/generated/`, and the trained
artifact is written to `data/models/ported_transaction_fraud_model.joblib`.
