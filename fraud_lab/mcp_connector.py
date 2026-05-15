from __future__ import annotations

from typing import Any

from fraud_lab.db import Repository, utc_now


class LocalMCPConnector:
    """Small MCP-style adapter used by the lab's agent policy layer.

    It intentionally stays local and auditable: every tool call writes a security
    action log before account state changes affect the rest of the app.
    """

    name = "local-account-control-mcp"

    def __init__(self, repository: Repository):
        self.repository = repository

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "suspend_account",
                "description": "Suspend an account after a high-risk model decision.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string"},
                        "risk_score": {"type": "number"},
                        "reason": {"type": "string"},
                        "transaction_id": {"type": "string"},
                    },
                    "required": ["account_id", "risk_score", "reason"],
                },
            },
            {
                "name": "flag_for_review",
                "description": "Place an account into analyst review without suspension.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string"},
                        "risk_score": {"type": "number"},
                        "reason": {"type": "string"},
                        "transaction_id": {"type": "string"},
                    },
                    "required": ["account_id", "risk_score", "reason"],
                },
            },
            {
                "name": "restore_account",
                "description": "Restore a lab account to active status.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["account_id"],
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "suspend_account":
            return self._set_status(name, arguments, "suspended")
        if name == "flag_for_review":
            current = self.repository.get_account(str(arguments["account_id"]))
            status = "suspended" if current and current["status"] == "suspended" else "under_review"
            return self._set_status(name, arguments, status)
        if name == "restore_account":
            return self._set_status(name, arguments, "active")
        raise ValueError(f"Unknown MCP tool: {name}")

    def _set_status(self, tool_name: str, arguments: dict[str, Any], status: str) -> dict[str, Any]:
        account_id = str(arguments["account_id"])
        risk_score = float(arguments.get("risk_score", 0))
        reason = str(arguments.get("reason", "manual MCP call"))
        transaction_id = arguments.get("transaction_id")
        account = self.repository.upsert_account(
            account_id=account_id,
            user_id=arguments.get("user_id"),
            status=status,
            risk_score=risk_score,
            notes=reason,
        )
        response = {
            "content": [
                {
                    "type": "text",
                    "text": f"{account_id} status={status} risk={risk_score:.4f}",
                }
            ],
            "account": account,
        }
        self.repository.log_security_action(
            {
                "created_at": utc_now(),
                "account_id": account_id,
                "transaction_id": transaction_id,
                "action_type": tool_name,
                "reason": reason,
                "status": "ok",
                "connector": self.name,
                "request": arguments,
                "response": response,
            }
        )
        return response


class PolicyEngine:
    def __init__(self, connector: LocalMCPConnector):
        self.connector = connector

    def apply(self, transaction: dict[str, Any]) -> dict[str, Any] | None:
        risk = transaction["risk_label"]
        if risk == "normal":
            return None
        decision = transaction["decision"]
        reason = ", ".join(decision.get("reasons", [])) or "model threshold exceeded"
        tool = "suspend_account" if risk == "blocked" else "flag_for_review"
        return self.connector.call_tool(
            tool,
            {
                "account_id": transaction["account_id"],
                "transaction_id": transaction["id"],
                "risk_score": float(decision.get("score", transaction.get("anomaly_score") or 0)),
                "reason": reason,
            },
        )


def handle_json_rpc(connector: LocalMCPConnector, request: dict[str, Any]) -> dict[str, Any]:
    request_id = request.get("id")
    method = request.get("method")
    try:
        if method == "tools/list":
            result = {"tools": connector.list_tools()}
        elif method == "tools/call":
            params = request.get("params", {})
            result = connector.call_tool(params["name"], params.get("arguments", {}))
        else:
            raise ValueError(f"Unsupported method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:  # noqa: BLE001 - returned as JSON-RPC error to the caller.
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": str(exc)},
        }
