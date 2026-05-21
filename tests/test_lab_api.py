from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def build_client(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_LAB_DB_PATH", str(tmp_path / "fraud_lab.sqlite3"))
    monkeypatch.setenv("FRAUD_LAB_MODEL_DIR", str(tmp_path / "models"))

    import fraud_lab.config as config

    importlib.reload(config)
    import fraud_lab.main as main

    importlib.reload(main)
    return TestClient(main.app)


def test_lab_core_flow(tmp_path, monkeypatch):
    with build_client(tmp_path, monkeypatch) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["model_version"] >= 1

        schema = client.get("/api/schema").json()
        assert schema["schema_id"] == "kaggle_fraud_transactions_v1"

        response = client.post(
            "/api/transactions",
            json={
                "source": "test",
                "payload": {
                    "trans_date_trans_time": "2020-06-21 03:14:25",
                    "cc_num": "4767265376804500",
                    "merchant": "fraud_Kilback LLC",
                    "category": "shopping_net",
                    "amt": 2400.0,
                    "gender": "F",
                    "city": "Birmingham",
                    "state": "AL",
                    "zip": 35203,
                    "lat": 33.5207,
                    "long": -86.8025,
                    "city_pop": 212237,
                    "job": "Engineer",
                    "dob": "1988-04-12",
                    "trans_num": "pytest-transaction-001",
                    "unix_time": 1592709265,
                    "merch_lat": 40.7128,
                    "merch_long": -74.006,
                    "old_balance": 2600.0,
                    "new_balance": 200.0,
                    "is_fraud": True,
                },
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["transaction"]["risk_label"] in {"review", "blocked"}
        assert body["transaction"]["label"] is None
        assert "is_fraud" not in body["transaction"]["payload"]

        simulated = client.post("/api/simulate", json={"count": 3, "fraud_rate": 0.5})
        assert simulated.status_code == 200
        assert all(item["label"] is None for item in simulated.json()["created"])

        tools = client.get("/api/mcp/tools")
        assert tools.status_code == 200
        assert tools.json()["tools"]

        bot = client.post(
            "/api/bot/start",
            json={"interval_seconds": 10, "batch_size": 1, "fraud_rate": 0.2},
        )
        assert bot.status_code == 200
        assert bot.json()["running"] is True

        bot_status = client.get("/api/bot/status")
        assert bot_status.status_code == 200
        assert bot_status.json()["batch_size"] == 1
        assert bot_status.json()["label_policy"] == "unlabeled_stream"

        bot_stop = client.post("/api/bot/stop")
        assert bot_stop.status_code == 200
        assert bot_stop.json()["running"] is False

        mcp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "restore_account",
                    "arguments": {"account_id": "acct-test-001", "reason": "pytest"},
                },
            },
        )
        assert mcp.status_code == 200
        assert "result" in mcp.json()

        updates = client.get("/api/model/updates")
        assert updates.status_code == 200
        assert updates.json()["items"]

        red_blue = client.get("/api/logs/red-blue")
        assert red_blue.status_code == 200
        assert red_blue.json()["items"]
