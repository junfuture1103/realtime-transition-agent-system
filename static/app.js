const state = {
  schema: null,
  transactions: [],
  health: null,
  bot: null,
  adminToken: sessionStorage.getItem("fraudLabAdminToken") || "",
  streamMetrics: null,
  labelMetrics: null,
};

const DASHBOARD_REFRESH_INTERVAL_MS = 5000;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

async function fetchJson(url, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  const response = await fetch(url, {
    ...options,
    headers,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

async function fetchFormJson(url, formData, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.headers || {}),
    },
    body: formData,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

function adminHeaders() {
  return state.adminToken ? { "X-Admin-Token": state.adminToken } : {};
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
  const [health, transactions, updates, logs, redBlue, intel, accounts, actions, streamMetrics, labelMetrics] = await Promise.all([
    fetchJson("/api/health"),
    fetchJson("/api/transactions?limit=120"),
    fetchJson("/api/model/updates?limit=12"),
    fetchJson("/api/logs/training?limit=80"),
    fetchJson("/api/logs/red-blue?limit=80"),
    fetchJson("/api/model/attacker-intel"),
    fetchJson("/api/accounts?limit=80"),
    fetchJson("/api/actions?limit=80"),
    fetchJson("/api/metrics/stream?seconds=180"),
    fetchJson("/api/metrics/label-comparison?windows=12"),
  ]);
  state.health = health;
  state.transactions = transactions.items;
  state.streamMetrics = streamMetrics;
  state.labelMetrics = labelMetrics;
  renderHealth(health);
  renderStreamMetrics(streamMetrics);
  renderLabelMetrics(labelMetrics);
  renderTransactions(transactions.items);
  renderBotGate();
  renderBotTransactions(transactions.items.filter((tx) => tx.source === "world_bot").slice(0, 30));
  renderUpdates(updates.items);
  renderTrainingLogs(logs.items);
  renderRedBlueLogs(redBlue.items);
  renderIntel(intel, updates.items);
  renderAccounts(accounts.items);
  renderActions(actions.items);
  if (state.adminToken) {
    refreshBotStatus();
  }
}

async function refreshMetrics() {
  const [streamMetrics, labelMetrics] = await Promise.all([
    fetchJson("/api/metrics/stream?seconds=180"),
    fetchJson("/api/metrics/label-comparison?windows=12"),
  ]);
  state.streamMetrics = streamMetrics;
  state.labelMetrics = labelMetrics;
  renderStreamMetrics(streamMetrics);
  renderLabelMetrics(labelMetrics);
  if (state.adminToken) {
    refreshBotStatus();
  }
}

function renderHealth(health) {
  $("#modelChip").textContent = `v${health.model_version} · ${health.model_kind}`;
  const stats = health.stats || {};
  const truth = health.truth_labels || {};
  const hasRevealed = Number(stats.revealed_truth || 0) > 0;
  $("#stats").innerHTML = [
    metricCard("거래 발생 수", compactNumber(stats.transactions ?? 0)),
    metricCard("이상거래 탐지율", pct(Number(stats.detection_rate || 0) * 100, 1)),
    metricCard("검토/차단", compactNumber(stats.detected ?? 0)),
    metricCard("정답 공개", `${compactNumber(stats.revealed_truth || 0)}/${compactNumber(truth.total_truth || 0)}`),
    metricCard("모델 정확도", hasRevealed ? pct(Number(stats.model_accuracy || 0) * 100, 1) : "대기"),
    metricCard("공격 성공률", hasRevealed ? pct(Number(stats.attack_success_rate || 0) * 100, 1) : "대기"),
  ].join("");
  renderLabelRevealStatus(health);
}

function renderLabelRevealStatus(health) {
  const node = $("#labelRevealStatus");
  if (!node) return;
  const truth = health?.truth_labels || {};
  const stats = health?.stats || {};
  node.innerHTML = `
    <article class="item">
      <div class="item-head"><span>공개 대기 ${compactNumber(truth.unrevealed || 0)}</span><span>공개됨 ${compactNumber(truth.revealed || 0)}</span></div>
      <div class="meta">현재 공개된 모집단 truth=${compactNumber(truth.total_truth || 0)} · 최신 데이터=${formatTime(truth.latest_dataset_time)}</div>
      <div class="meta">최신 공개=${formatTime(truth.latest_revealed_dataset_time)} · 모델 정확도=${Number(stats.revealed_truth || 0) ? pct(Number(stats.model_accuracy || 0) * 100, 1) : "대기"}</div>
      <div class="meta">사기 탐지율=${Number(stats.revealed_truth || 0) ? pct(Number(stats.fraud_recall || 0) * 100, 1) : "대기"} · 공격 성공률=${Number(stats.revealed_truth || 0) ? pct(Number(stats.attack_success_rate || 0) * 100, 1) : "대기"}</div>
    </article>
  `;
}

function fitCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  if (!canvas.dataset.chartHeight) {
    canvas.dataset.chartHeight = canvas.getAttribute("height") || "240";
  }
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.floor(rect.width || canvas.parentElement.clientWidth || 640));
  const height = Number(canvas.dataset.chartHeight) || 240;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, width, height };
}

function drawEmptyChart(canvas, label) {
  const { ctx, width, height } = fitCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  drawGrid(ctx, width, height, { top: 18, right: 18, bottom: 34, left: 44 }, 1, (value) => value);
  ctx.fillStyle = "#68736f";
  ctx.font = "700 12px Inter, sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(label, width / 2, height / 2);
}

function chartColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function compactNumber(value) {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(Number(value || 0));
}

function pct(value, digits = 1) {
  return `${Number(value || 0).toFixed(digits)}%`;
}

function renderKpis(selector, items) {
  const node = $(selector);
  if (!node) return;
  node.innerHTML = items
    .map((item) => `<div class="chart-kpi"><strong>${item.value}</strong><span>${item.label}</span></div>`)
    .join("");
}

function renderLegend(selector, items) {
  const node = $(selector);
  if (!node) return;
  node.innerHTML = items
    .map(
      (item) => `
        <span class="legend-item">
          <span class="legend-swatch" style="background:${item.color}"></span>
          ${item.label}
        </span>
      `,
    )
    .join("");
}

function drawGrid(ctx, width, height, padding, maxValue, formatter) {
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;
  ctx.strokeStyle = "#e3e8e0";
  ctx.lineWidth = 1;
  ctx.fillStyle = "#68736f";
  ctx.font = "11px Inter, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let index = 0; index <= 4; index += 1) {
    const ratio = index / 4;
    const y = padding.top + chartH - chartH * ratio;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(padding.left + chartW, y);
    ctx.stroke();
    ctx.fillText(formatter(maxValue * ratio), padding.left - 8, y);
  }
  ctx.strokeStyle = "#cfd7cd";
  ctx.beginPath();
  ctx.moveTo(padding.left, padding.top);
  ctx.lineTo(padding.left, padding.top + chartH);
  ctx.lineTo(padding.left + chartW, padding.top + chartH);
  ctx.stroke();
}

function renderStreamMetrics(metrics) {
  const canvas = $("#streamChart");
  if (!canvas || !metrics) return;
  const buckets = metrics.buckets || [];
  const latest = metrics.latest_per_second || 0;
  $("#streamPulse").textContent = `${latest}/s`;
  $("#streamPulse").classList.toggle("active", latest > 0);
  if (!buckets.length) {
    drawEmptyChart(canvas, "no stream");
    return;
  }
  const { ctx, width, height } = fitCanvas(canvas);
  const padding = { top: 18, right: 18, bottom: 34, left: 44 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;
  const maxValue = Math.max(1, ...buckets.map((item) => item.total));
  const blue = chartColor("--blue");
  const green = chartColor("--green");
  const amber = chartColor("--amber");
  const red = chartColor("--red");
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  drawGrid(ctx, width, height, padding, maxValue, (value) => Math.round(value));

  const xFor = (index) => padding.left + (chartW * index) / Math.max(1, buckets.length - 1);
  const yFor = (value) => padding.top + chartH - (Number(value || 0) / maxValue) * chartH;
  const gradient = ctx.createLinearGradient(0, padding.top, 0, padding.top + chartH);
  gradient.addColorStop(0, "rgba(47, 95, 159, 0.28)");
  gradient.addColorStop(1, "rgba(47, 95, 159, 0.03)");

  ctx.beginPath();
  buckets.forEach((item, index) => {
    const x = xFor(index);
    const y = yFor(item.total);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.lineTo(xFor(buckets.length - 1), padding.top + chartH);
  ctx.lineTo(xFor(0), padding.top + chartH);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  ctx.beginPath();
  buckets.forEach((item, index) => {
    const x = xFor(index);
    const y = yFor(item.total);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = blue;
  ctx.lineWidth = 2.5;
  ctx.stroke();

  const barW = Math.max(2, chartW / buckets.length);
  buckets.forEach((item, index) => {
    const x = padding.left + index * barW;
    const review = Number(item.review || 0);
    const blocked = Number(item.blocked || 0);
    if (review) {
      ctx.fillStyle = amber;
      ctx.fillRect(x, padding.top + chartH - 12, Math.max(2, barW - 1), 5);
    }
    if (blocked) {
      ctx.fillStyle = red;
      ctx.fillRect(x, padding.top + chartH - 20, Math.max(2, barW - 1), 7);
    }
  });

  const lastIndex = buckets.length - 1;
  const lastX = xFor(lastIndex);
  const lastY = yFor(buckets[lastIndex].total);
  ctx.fillStyle = latest > 0 ? green : blue;
  ctx.beginPath();
  ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = "#68736f";
  ctx.font = "11px Inter, sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  ctx.fillText("180s ago", padding.left, height - 10);
  ctx.textAlign = "right";
  ctx.fillText("now", width - padding.right, height - 10);

  const reviewCount = buckets.reduce((sum, item) => sum + Number(item.review || 0), 0);
  const blockedCount = buckets.reduce((sum, item) => sum + Number(item.blocked || 0), 0);
  renderKpis("#streamKpis", [
    { label: "3분 유입", value: compactNumber(metrics.total || 0) },
    { label: "현재 속도", value: `${latest}/s` },
    { label: "검토/차단", value: compactNumber(reviewCount + blockedCount) },
  ]);
  renderLegend("#streamLegend", [
    { label: "초당 거래량", color: blue },
    { label: "검토", color: amber },
    { label: "차단", color: red },
  ]);
}

function renderLabelMetrics(metrics) {
  const canvas = $("#labelChart");
  if (!canvas || !metrics) return;
  const rows = metrics.windows || [];
  const revealed = metrics.revealed_before ? formatTime(metrics.revealed_before) : "관리자 공개 대기";
  $("#labelRevealChip").textContent = revealed;
  if (!rows.length) {
    renderKpis("#labelKpis", [
      { label: "모델 정확도", value: "대기" },
      { label: "공격 성공률(오탐률)", value: "대기" },
    ]);
    renderLegend("#labelLegend", [
      { label: "실제 fraud rate", color: chartColor("--blue") },
      { label: "모델 predicted rate", color: chartColor("--amber") },
      { label: "accuracy", color: chartColor("--green") },
    ]);
    drawEmptyChart(canvas, "label window pending");
    return;
  }
  const { ctx, width, height } = fitCanvas(canvas);
  const padding = { top: 18, right: 44, bottom: 38, left: 46 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;
  const series = rows.map((item) => ({
    ...item,
    actualRate: (Number(item.actual_fraud || 0) / Math.max(1, Number(item.total || 0))) * 100,
    predictedRate: (Number(item.predicted_fraud || 0) / Math.max(1, Number(item.total || 0))) * 100,
    accuracyRate: Number(item.accuracy || 0) * 100,
  }));
  const maxRate = Math.max(1, Math.ceil(Math.max(...series.map((item) => Math.max(item.actualRate, item.predictedRate))) * 1.3));
  const blue = chartColor("--blue");
  const amber = chartColor("--amber");
  const green = chartColor("--green");
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  drawGrid(ctx, width, height, padding, maxRate, (value) => pct(value, 0));
  ctx.fillStyle = "#68736f";
  ctx.font = "11px Inter, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("fraud rate", padding.left, 12);
  ctx.textAlign = "right";
  ctx.fillText("accuracy", width - padding.right + 34, 12);

  ctx.fillStyle = "#68736f";
  ctx.textAlign = "left";
  ctx.fillText("0%", width - padding.right + 10, padding.top + chartH);
  ctx.fillText("100%", width - padding.right + 10, padding.top + 4);

  const groupW = chartW / series.length;
  const barW = Math.max(8, Math.min(24, groupW * 0.24));
  const rateY = (value) => padding.top + chartH - (value / maxRate) * chartH;
  const accuracyY = (value) => padding.top + chartH - (value / 100) * chartH;
  series.forEach((item, index) => {
    const center = padding.left + groupW * index + groupW / 2;
    const actualH = padding.top + chartH - rateY(item.actualRate);
    const predictedH = padding.top + chartH - rateY(item.predictedRate);
    ctx.fillStyle = blue;
    ctx.fillRect(center - barW - 2, rateY(item.actualRate), barW, actualH);
    ctx.fillStyle = amber;
    ctx.fillRect(center + 2, rateY(item.predictedRate), barW, predictedH);
    if (index % Math.ceil(series.length / 6) === 0 || index === series.length - 1) {
      const label = formatTime(item.bucket_start).split(" ")[0] || "";
      ctx.save();
      ctx.translate(center, height - 12);
      ctx.rotate(-0.35);
      ctx.fillStyle = "#68736f";
      ctx.font = "10px Inter, sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(label, 0, 0);
      ctx.restore();
    }
  });

  ctx.beginPath();
  series.forEach((item, index) => {
    const x = padding.left + groupW * index + groupW / 2;
    const y = accuracyY(item.accuracyRate);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = green;
  ctx.lineWidth = 2.5;
  ctx.stroke();
  series.forEach((item, index) => {
    const x = padding.left + groupW * index + groupW / 2;
    const y = accuracyY(item.accuracyRate);
    ctx.fillStyle = green;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
  });

  const latest = series[series.length - 1] || {};
  const latestAttackSuccess = Number(latest.fn || 0) / Math.max(1, Number(latest.actual_fraud || 0));
  ctx.fillStyle = "#68736f";
  ctx.font = "11px Inter, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(`latest acc ${pct(latest.accuracyRate, 1)}`, padding.left, height - 8);

  renderKpis("#labelKpis", [
    { label: "모델 정확도", value: pct(latest.accuracyRate, 1) },
    { label: "공격 성공률(오탐률)", value: pct(latestAttackSuccess * 100, 1) },
  ]);
  renderLegend("#labelLegend", [
    { label: "실제 fraud rate", color: blue },
    { label: "모델 predicted rate", color: amber },
    { label: "accuracy", color: green },
  ]);
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
          <td><div class="meta">${label}</div></td>
        </tr>
      `;
    })
    .join("");
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
  const dataset = bot.dataset || {};
  $("#botStatus").innerHTML = `
    <article class="item">
      <div class="item-head"><span>${bot.running ? "running" : "stopped"}</span><span>${bot.running ? riskPill("normal") : riskPill("review")}</span></div>
      <div class="meta">mode=${bot.stream_mode || "dataset"} · interval=${bot.interval_seconds}s · batch=${bot.batch_size} · replay_speed=${bot.replay_speed}</div>
      <div class="meta">synthetic_suspicious_rate=${bot.fraud_rate}</div>
      <div class="meta">label_policy=${bot.label_policy || "unlabeled_stream"}</div>
      <div class="meta">generated=${bot.generated} · last_tick=${formatTime(bot.last_tick_at)}</div>
      <div class="meta">dataset=${dataset.available ? "ready" : "missing"} · rows=${dataset.rows ?? "-"} · emitted=${dataset.emitted ?? 0}</div>
      <div class="meta">dataset_time=${formatTime(dataset.dataset_time)} · next=${formatTime(dataset.next_dataset_time)}</div>
      <div class="meta">last_tx=${bot.last_transaction_id || "-"}</div>
      <div class="meta">${bot.last_error ? `error=${bot.last_error}` : "error=none"}</div>
    </article>
  `;
  $("#botIntervalInput").value = bot.interval_seconds;
  $("#botBatchInput").value = bot.batch_size;
  $("#botFraudRateInput").value = bot.fraud_rate;
  $("#botModeInput").value = bot.stream_mode || "dataset";
  $("#botReplaySpeedInput").value = bot.replay_speed || 3600;
}

function renderBotGate() {
  const unlocked = Boolean(state.adminToken);
  $("#botLock").classList.toggle("hidden", unlocked);
  $("#botAdminContent").classList.toggle("hidden", !unlocked);
  $("#botToolbar").classList.toggle("hidden", !unlocked);
}

async function refreshBotStatus() {
  try {
    const bot = await fetchJson("/api/bot/status", { headers: adminHeaders() });
    state.bot = bot;
    renderBotGate();
    renderBotStatus(bot);
  } catch (error) {
    state.adminToken = "";
    sessionStorage.removeItem("fraudLabAdminToken");
    renderBotGate();
  }
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
      if (tab.dataset.tab === "bot" && state.adminToken) {
        refreshBotStatus();
      }
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
  $("#botUnlockBtn").addEventListener("click", unlockBot);
  $("#labelRevealBtn").addEventListener("click", revealTruthLabels);
  $("#modelUploadBtn").addEventListener("click", uploadModelArtifact);
  $("#botAdminPasswordInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") unlockBot();
  });
  $("#retrainBtn").addEventListener("click", async () => {
    await fetchJson("/api/admin/retrain", {
      method: "POST",
      headers: adminHeaders(),
      body: JSON.stringify({ reason: "manual_ui_retrain" }),
    });
    toast("재학습이 완료됐습니다.");
    refreshAll();
  });
  $("#mcpReviewBtn").addEventListener("click", () => manualMcp("flag_for_review"));
  $("#mcpRestoreBtn").addEventListener("click", () => manualMcp("restore_account"));
}

async function unlockBot() {
  const password = $("#botAdminPasswordInput").value;
  const response = await fetchJson("/api/admin/login", {
    method: "POST",
    body: JSON.stringify({ admin_password: password }),
  });
  state.adminToken = response.token;
  sessionStorage.setItem("fraudLabAdminToken", response.token);
  $("#botAdminPasswordInput").value = "";
  renderBotGate();
  await refreshBotStatus();
  toast("봇 관리자 탭이 열렸습니다.");
}

async function startBot() {
  await fetchJson("/api/bot/start", {
    method: "POST",
    headers: adminHeaders(),
    body: JSON.stringify({
      interval_seconds: Number($("#botIntervalInput").value),
      batch_size: Number($("#botBatchInput").value),
      fraud_rate: Number($("#botFraudRateInput").value),
      stream_mode: $("#botModeInput").value,
      replay_speed: Number($("#botReplaySpeedInput").value),
    }),
  });
  toast("라벨 없는 데이터셋 리플레이 봇이 시작됐습니다.");
  refreshAll();
}

async function stopBot() {
  await fetchJson("/api/bot/stop", {
    method: "POST",
    headers: adminHeaders(),
    body: JSON.stringify({}),
  });
  toast("실시간 거래 봇이 정지됐습니다.");
  refreshAll();
}

async function revealTruthLabels() {
  const retrainAfter = $("#labelRevealRetrainInput").checked;
  const response = await fetchJson("/api/admin/labels/reveal", {
    method: "POST",
    headers: adminHeaders(),
    body: JSON.stringify({ reveal_all: true, retrain_after: retrainAfter }),
  });
  toast(`${response.result.revealed}건의 공개 데이터에 정답 라벨을 부여했습니다.`);
  await refreshAll();
}

async function uploadModelArtifact() {
  const input = $("#modelUploadInput");
  const file = input.files?.[0];
  if (!file) {
    toast("업로드할 모델 artifact를 선택해주세요.");
    return;
  }
  $("#modelUploadStatus").textContent = "업로드 중...";
  const form = new FormData();
  form.append("file", file);
  form.append("notes", $("#modelUploadNotesInput").value || "manual_model_upload");
  try {
    const response = await fetchFormJson("/api/admin/model/upload", form, {
      method: "POST",
      headers: adminHeaders(),
    });
    $("#modelUploadStatus").textContent = `v${response.update.version} 모델로 전환됨`;
    input.value = "";
    toast("모델 업데이트가 반영됐습니다.");
    await refreshAll();
  } catch (error) {
    $("#modelUploadStatus").textContent = error.message;
    throw error;
  }
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
}, DASHBOARD_REFRESH_INTERVAL_MS);

window.addEventListener("resize", () => {
  renderStreamMetrics(state.streamMetrics);
  renderLabelMetrics(state.labelMetrics);
});
