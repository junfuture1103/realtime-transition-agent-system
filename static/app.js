const state = {
  schema: null,
  transactions: [],
  health: null,
  bot: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 2600);
}

function formatTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatScore(value) {
  return Number(value || 0).toFixed(3);
}

function money(value) {
  return `${Math.round(Number(value || 0)).toLocaleString("ko-KR")}원`;
}

function riskPill(risk) {
  return `<span class="pill ${risk}">${risk}</span>`;
}

function metricCard(label, value) {
  return `<div class="stat"><strong>${value}</strong><span>${label}</span></div>`;
}

async function loadBase() {
  state.schema = await fetchJson("/api/schema");
  renderSchemaExample();
  renderForm();
  await refreshAll();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderSchemaExample() {
  const schema = state.schema;
  const example = {};
  schema.fields.filter((field) => field.role !== "target").forEach((field) => {
    example[field.name] = field.default ?? sampleValueFor(field);
  });
  const features = schema.fields.filter((field) => field.role === "feature" && field.train !== false);
  const nonTraining = schema.fields.filter((field) => field.role !== "feature" || field.train === false);
  const chips = features.map((field) => `<span class="feature-chip">${field.name}</span>`).join("");
  const nonTrainingNames = nonTraining.map((field) => field.name).join(", ");
  const source = schema.source || {};
  $("#schemaExample").innerHTML = `
    <div class="schema-card">
      <h3>현재 모델 입력 예시</h3>
      <pre>${escapeHtml(JSON.stringify(example, null, 2))}</pre>
    </div>
    <div class="schema-card">
      <h3>스키마 기준</h3>
      <div class="meta">schema_id=${schema.schema_id}</div>
      <div class="meta">target=${schema.target}</div>
      <div class="meta">${source.name || "Kaggle fraud transaction dataset"} 형식을 기본값으로 적용했습니다.</div>
      <div class="meta">컬럼/타깃/임계값은 configs/schemas/kaggle_fraud_transactions.json에서 교체됩니다.</div>
      <div class="meta">거래 생성자는 정답 라벨을 넣지 않습니다. ${schema.target}은 방어자 피드백/검증 데이터에서만 붙습니다.</div>
      <h3>학습 피처</h3>
      <div class="feature-list">${chips}</div>
      <div class="meta">학습 제외/식별/라벨: ${nonTrainingNames}</div>
    </div>
  `;
}

function sampleValueFor(field) {
  if (field.type === "number") return 0;
  if (field.type === "integer") return 0;
  if (field.type === "boolean") return false;
  if (field.type === "categorical") return (field.allowed || [])[0] || "";
  return "";
}

async function refreshAll() {
  const [health, transactions, updates, logs, redBlue, intel, accounts, actions, bot] = await Promise.all([
    fetchJson("/api/health"),
    fetchJson("/api/transactions?limit=120"),
    fetchJson("/api/model/updates?limit=12"),
    fetchJson("/api/logs/training?limit=80"),
    fetchJson("/api/logs/red-blue?limit=80"),
    fetchJson("/api/model/attacker-intel"),
    fetchJson("/api/accounts?limit=80"),
    fetchJson("/api/actions?limit=80"),
    fetchJson("/api/bot/status"),
  ]);
  state.health = health;
  state.transactions = transactions.items;
  state.bot = bot;
  renderHealth(health);
  renderTransactions(transactions.items);
  renderBotStatus(bot);
  renderBotTransactions(transactions.items.filter((tx) => tx.source === "world_bot").slice(0, 30));
  renderUpdates(updates.items);
  renderTrainingLogs(logs.items);
  renderRedBlueLogs(redBlue.items);
  renderIntel(intel, updates.items);
  renderAccounts(accounts.items);
  renderActions(actions.items);
}

function renderHealth(health) {
  $("#modelChip").textContent = `v${health.model_version} · ${health.model_kind}`;
  const stats = health.stats || {};
  $("#stats").innerHTML = [
    metricCard("거래", stats.transactions ?? 0),
    metricCard("검토", stats.review ?? 0),
    metricCard("차단", stats.blocked ?? 0),
    metricCard("라벨", stats.labeled ?? 0),
    metricCard("계정", stats.accounts ?? 0),
    metricCard("정지", stats.suspended_accounts ?? 0),
  ].join("");
}

function renderForm() {
  const fields = state.schema.fields.filter((field) => field.role !== "target");
  const controls = fields.map((field) => {
    const id = `field-${field.name}`;
    const label = `<label for="${id}">${field.name}</label>`;
    if (field.type === "categorical") {
      const options = (field.allowed || [])
        .map((value) => `<option value="${value}" ${value === field.default ? "selected" : ""}>${value}</option>`)
        .join("");
      return `<div class="field">${label}<select id="${id}" data-field="${field.name}" data-type="${field.type}">${options}</select></div>`;
    }
    if (field.type === "boolean") {
      return `<div class="field check">${label}<input id="${id}" type="checkbox" data-field="${field.name}" data-type="${field.type}" ${field.default ? "checked" : ""} /></div>`;
    }
    const inputType = field.type === "number" || field.type === "integer" ? "number" : "text";
    const step = field.type === "integer" ? "1" : "any";
    const min = field.min !== undefined ? `min="${field.min}"` : "";
    const max = field.max !== undefined ? `max="${field.max}"` : "";
    return `<div class="field">${label}<input id="${id}" type="${inputType}" step="${step}" ${min} ${max} value="${field.default ?? ""}" data-field="${field.name}" data-type="${field.type}" /></div>`;
  });
  $("#transactionForm").innerHTML = controls.join("");
}

function collectPayload() {
  const payload = {};
  $$("[data-field]").forEach((node) => {
    const name = node.dataset.field;
    const type = node.dataset.type;
    if (type === "boolean") {
      payload[name] = node.checked;
    } else if (type === "number") {
      payload[name] = Number(node.value);
    } else if (type === "integer") {
      payload[name] = Number.parseInt(node.value, 10);
    } else {
      payload[name] = node.value;
    }
  });
  return payload;
}

function renderTransactions(items) {
  const display = state.schema?.display || {};
  const amountField = display.amount_field || "amount";
  const categoryField = display.category_field || "merchant_category";
  const channelField = display.channel_field || "channel";
  const countryField = display.country_field || "country";
  $("#transactionRows").innerHTML = items
    .map((tx) => {
      const payload = tx.payload || {};
      const reasons = (tx.decision?.reasons || []).join(", ");
      const label = tx.label === null || tx.label === undefined ? "unlabeled" : tx.label ? "fraud" : "normal";
      return `
        <tr>
          <td>${formatTime(tx.created_at)}</td>
          <td>${tx.account_id}<div class="meta">${tx.source} · v${tx.model_version}</div></td>
          <td>${moneyLike(payload[amountField])}</td>
          <td>${payload[channelField] || "-"} · ${payload[countryField] || "-"}<div class="meta">${payload[categoryField] || "-"}</div></td>
          <td>${riskPill(tx.risk_label)}<div class="meta">${formatScore(tx.anomaly_score)}</div></td>
          <td>${reasons}</td>
          <td>
            <div class="meta">${label}</div>
            <div class="inline-actions">
              <button data-label="0" data-id="${tx.id}">정상</button>
              <button data-label="1" data-id="${tx.id}">사기</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
  $$("button[data-label]").forEach((button) => {
    button.addEventListener("click", async () => {
      await fetchJson(`/api/transactions/${button.dataset.id}/label`, {
        method: "POST",
        body: JSON.stringify({ label: Number(button.dataset.label), label_source: "human_feedback_ui" }),
      });
      toast("라벨이 반영됐습니다.");
      refreshAll();
    });
  });
}

function moneyLike(value) {
  const amount = Number(value || 0);
  if (state.schema?.display?.amount_field === "amt") {
    return `$${amount.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
  }
  return money(amount);
}

function renderUpdates(items) {
  $("#modelUpdates").innerHTML = items
    .map((item) => {
      const metrics = item.metrics || {};
      const robust = item.robustness || {};
      const top = (robust.top_features || [])
        .slice(0, 5)
        .map((feature) => `${feature.feature} ${feature.importance}`)
        .join(" · ");
      return `
        <article class="item">
          <div class="item-head"><span>v${item.version} ${robust.model_kind || ""}</span><span>${formatTime(item.created_at)}</span></div>
          <div class="meta">rows=${item.training_rows} labeled=${item.labeled_rows} f1=${metrics.f1 ?? "-"} recall=${metrics.recall ?? "-"}</div>
          <div class="meta">${top}</div>
          <div class="meta">${item.notes}</div>
        </article>
      `;
    })
    .join("");
}

function renderTrainingLogs(items) {
  $("#trainingLogs").innerHTML = items
    .map((item) => `
      <article class="item">
        <div class="item-head"><span>${item.event_type}</span><span>${formatTime(item.created_at)}</span></div>
        <div class="meta">tx=${item.transaction_id || "-"} · label=${item.label ?? "none"} · ${item.label_source || "stream"}</div>
      </article>
    `)
    .join("");
}

function renderRedBlueLogs(items) {
  $("#redBlueLogs").innerHTML = items
    .map((item) => `
      <article class="item log-grid">
        <div>${item.team === "attack" ? riskPill("blocked") : riskPill("normal")}</div>
        <div>
          <div class="item-head"><span>${item.title}</span></div>
          <div class="meta">${item.description}</div>
          <div class="meta">${item.event_type} · schema=${item.schema_id}</div>
        </div>
        <div class="meta">${formatTime(item.created_at)}<br />v${item.model_version ?? "-"}</div>
      </article>
    `)
    .join("");
}

function renderIntel(intel, updates) {
  const thresholds = intel.thresholds || {};
  const cards = (intel.sandbox_attack_cards || [])
    .map((card) => `
      <article class="item">
        <div class="item-head"><span>${card.name}</span></div>
        <div class="meta">${card.objective}</div>
        <div class="meta">${card.learning_goal}</div>
      </article>
    `)
    .join("");
  const features = (intel.top_features || [])
    .slice(0, 8)
    .map((feature) => `<div class="meta">${feature.feature} · ${feature.importance}</div>`)
    .join("");
  $("#attackerIntel").innerHTML = `
    <article class="item">
      <div class="item-head"><span>v${intel.latest_version || "-"} ${intel.model_kind || ""}</span><span>${formatTime(intel.updated_at)}</span></div>
      <div class="meta">review=${thresholds.review ?? "-"} · block=${thresholds.block ?? "-"}</div>
      ${features}
    </article>
    ${cards}
  `;

  const latest = updates[0] || {};
  const controls = latest.robustness?.defense_controls || [];
  $("#defenderIntel").innerHTML = controls
    .map((control) => `<article class="item"><div class="meta">${control}</div></article>`)
    .join("");
}

function renderAccounts(items) {
  $("#accountList").innerHTML = items
    .map((item) => `
      <article class="item">
        <div class="item-head"><span>${item.account_id}</span><span>${item.status}</span></div>
        <div class="meta">risk=${formatScore(item.risk_score)} · ${formatTime(item.updated_at)}</div>
        <div class="meta">${item.notes || ""}</div>
      </article>
    `)
    .join("");
}

function renderActions(items) {
  $("#actionList").innerHTML = items
    .map((item) => `
      <article class="item">
        <div class="item-head"><span>${item.action_type}</span><span>${formatTime(item.created_at)}</span></div>
        <div class="meta">${item.account_id} · ${item.status}</div>
        <div class="meta">${item.reason}</div>
      </article>
    `)
    .join("");
}

function renderBotStatus(bot) {
  $("#botStatus").innerHTML = `
    <article class="item">
      <div class="item-head"><span>${bot.running ? "running" : "stopped"}</span><span>${bot.running ? riskPill("normal") : riskPill("review")}</span></div>
      <div class="meta">interval=${bot.interval_seconds}s · batch=${bot.batch_size} · suspicious_rate=${bot.fraud_rate}</div>
      <div class="meta">label_policy=${bot.label_policy || "unlabeled_stream"}</div>
      <div class="meta">generated=${bot.generated} · last_tick=${formatTime(bot.last_tick_at)}</div>
      <div class="meta">last_tx=${bot.last_transaction_id || "-"}</div>
      <div class="meta">${bot.last_error ? `error=${bot.last_error}` : "error=none"}</div>
    </article>
  `;
  $("#botIntervalInput").value = bot.interval_seconds;
  $("#botBatchInput").value = bot.batch_size;
  $("#botFraudRateInput").value = bot.fraud_rate;
}

function renderBotTransactions(items) {
  const display = state.schema?.display || {};
  const amountField = display.amount_field || "amount";
  $("#botTransactionRows").innerHTML = items
    .map((tx) => {
      const payload = tx.payload || {};
      const reasons = (tx.decision?.reasons || []).join(", ");
      return `
        <tr>
          <td>${formatTime(tx.created_at)}</td>
          <td>${tx.account_id}</td>
          <td>${moneyLike(payload[amountField])}</td>
          <td>${riskPill(tx.risk_label)}<div class="meta">${formatScore(tx.anomaly_score)}</div></td>
          <td>${reasons}</td>
        </tr>
      `;
    })
    .join("");
}

function bindEvents() {
  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".tab").forEach((node) => node.classList.remove("active"));
      $$(".view").forEach((node) => node.classList.remove("active"));
      tab.classList.add("active");
      $(`#view-${tab.dataset.tab}`).classList.add("active");
    });
  });

  $("#refreshBtn").addEventListener("click", refreshAll);
  $("#intelRefreshBtn").addEventListener("click", refreshAll);
  $("#simulateBtn").addEventListener("click", async () => {
    await fetchJson("/api/simulate", {
      method: "POST",
      body: JSON.stringify({ count: 20, fraud_rate: 0.18 }),
    });
    toast("라벨 없는 실생활 거래 스트림이 생성됐습니다.");
    refreshAll();
  });
  $("#submitTransactionBtn").addEventListener("click", async () => {
    await fetchJson("/api/transactions", {
      method: "POST",
      body: JSON.stringify({
        payload: collectPayload(),
        source: "manual_ui",
      }),
    });
    toast("라벨 없는 거래가 생성됐습니다.");
    refreshAll();
  });
  $("#startBotBtn").addEventListener("click", startBot);
  $("#stopBotBtn").addEventListener("click", stopBot);
  $("#retrainBtn").addEventListener("click", async () => {
    await fetchJson("/api/admin/retrain", {
      method: "POST",
      body: JSON.stringify({ reason: "manual_ui_retrain" }),
    });
    toast("재학습이 완료됐습니다.");
    refreshAll();
  });
  $("#mcpReviewBtn").addEventListener("click", () => manualMcp("flag_for_review"));
  $("#mcpRestoreBtn").addEventListener("click", () => manualMcp("restore_account"));
}

async function startBot() {
  await fetchJson("/api/bot/start", {
    method: "POST",
    body: JSON.stringify({
      interval_seconds: Number($("#botIntervalInput").value),
      batch_size: Number($("#botBatchInput").value),
      fraud_rate: Number($("#botFraudRateInput").value),
    }),
  });
  toast("라벨 없는 실시간 거래 봇이 시작됐습니다.");
  refreshAll();
}

async function stopBot() {
  await fetchJson("/api/bot/stop", {
    method: "POST",
    body: JSON.stringify({}),
  });
  toast("실시간 거래 봇이 정지됐습니다.");
  refreshAll();
}

async function manualMcp(name) {
  const accountId = $("#mcpAccountInput").value.trim() || "acct-demo-001";
  await fetchJson("/api/mcp/call", {
    method: "POST",
    body: JSON.stringify({
      name,
      arguments: {
        account_id: accountId,
        risk_score: name === "restore_account" ? 0 : 0.61,
        reason: "manual_ui_mcp_call",
      },
    }),
  });
  toast("MCP 액션이 기록됐습니다.");
  refreshAll();
}

bindEvents();
loadBase().catch((error) => {
  console.error(error);
  toast("초기화 실패: " + error.message);
});

setInterval(() => {
  refreshAll().catch((error) => console.error(error));
}, 5000);
