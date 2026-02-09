const state = {
  config: null,
  currentJobId: null,
  polling: null,
  latestResult: null,
  stockCodes: [],
};

const el = (id) => document.getElementById(id);

const api = {
  async get(path) {
    const res = await fetch(path);
    if (!res.ok) {
      throw new Error(await res.text());
    }
    return res.json();
  },
  async post(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      throw new Error(await res.text());
    }
    return res.json();
  },
  async del(path) {
    const res = await fetch(path, { method: "DELETE" });
    if (!res.ok) {
      throw new Error(await res.text());
    }
    return res.json();
  },
};

function setStatus(text, ok = true) {
  const status = el("api-status");
  status.textContent = text;
  status.style.color = ok ? "#14b8a6" : "#ef4444";
}

function buildParamInput(name, value) {
  const wrapper = document.createElement("label");
  wrapper.className = "field";
  const label = document.createElement("span");
  label.textContent = name;
  wrapper.appendChild(label);

  let input;
  if (value && typeof value === "object") {
    input = document.createElement("textarea");
    input.value = JSON.stringify(value, null, 2);
    input.rows = 3;
    input.dataset.paramType = "json";
  } else if (typeof value === "boolean") {
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = value;
  } else if (typeof value === "number") {
    input = document.createElement("input");
    input.type = "number";
    input.step = "0.0001";
    input.value = value;
  } else {
    input = document.createElement("input");
    input.type = "text";
    input.value = value;
  }
  input.dataset.param = name;
  wrapper.appendChild(input);
  return wrapper;
}

function renderSelectors(selectors) {
  const container = el("selector-list");
  container.innerHTML = "";
  selectors.forEach((selector, index) => {
    const item = document.createElement("div");
    item.className = "selector-item";
    item.dataset.selector = selector.class;

    const header = document.createElement("div");
    header.className = "selector-header";
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = selector.activate;
    checkbox.className = "selector-active";
    label.appendChild(checkbox);
    const title = document.createElement("span");
    title.textContent = `${selector.alias || selector.class}`;
    label.appendChild(title);
    header.appendChild(label);
    const badge = document.createElement("span");
    badge.className = "tiny";
    badge.textContent = selector.class;
    header.appendChild(badge);

    const params = document.createElement("div");
    params.className = "params";
    const paramEntries = selector.params || {};
    Object.keys(paramEntries).forEach((key) => {
      params.appendChild(buildParamInput(key, paramEntries[key]));
    });

    item.appendChild(header);
    item.appendChild(params);
    container.appendChild(item);
  });
}

function renderSellStrategies(strategies) {
  const select = el("sell-strategy");
  select.innerHTML = "";
  Object.entries(strategies).forEach(([key, value]) => {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = `${key} — ${value.description || ""}`;
    select.appendChild(option);
  });
}

function renderSellParams(strategyKey) {
  const paramsContainer = el("sell-params");
  paramsContainer.innerHTML = "";
  if (!state.config) return;
  const strategies = state.config.sell_strategies || {};
  const strategy = strategies[strategyKey];
  if (!strategy) return;

  const summary = document.createElement("div");
  summary.className = "hint";
  summary.textContent = strategy.description || "";
  paramsContainer.appendChild(summary);

  if (strategy.strategies) {
    strategy.strategies.forEach((sub, idx) => {
      const card = document.createElement("div");
      card.className = "selector-item";
      card.dataset.subindex = idx;
      const title = document.createElement("strong");
      title.textContent = sub.class;
      card.appendChild(title);
      const params = document.createElement("div");
      params.className = "params";
      Object.entries(sub.params || {}).forEach(([key, value]) => {
        params.appendChild(buildParamInput(key, value));
      });
      card.appendChild(params);
      paramsContainer.appendChild(card);
    });
  } else if (strategy.params) {
    Object.entries(strategy.params).forEach(([key, value]) => {
      paramsContainer.appendChild(buildParamInput(key, value));
    });
  }
}

function parseSelectorsPayload() {
  const items = Array.from(document.querySelectorAll(".selector-item[data-selector]"));
  return items.map((item) => {
    const className = item.dataset.selector;
    const active = item.querySelector(".selector-active")?.checked ?? false;
    const params = {};
    item.querySelectorAll("[data-param]").forEach((input) => {
      const key = input.dataset.param;
      if (input.dataset.paramType === "json") {
        try {
          params[key] = JSON.parse(input.value);
        } catch {
          params[key] = input.value;
        }
      } else if (input.type === "checkbox") {
        params[key] = input.checked;
      } else if (input.type === "number") {
        params[key] = Number(input.value);
      } else {
        params[key] = input.value;
      }
    });
    const selector = state.config.selectors.find((s) => s.class === className) || {};
    return {
      class: className,
      alias: selector.alias || className,
      activate: active,
      params,
    };
  });
}

function parseSellStrategyPayload() {
  const key = el("sell-strategy").value;
  const base = state.config.sell_strategies[key];
  if (!base) return null;

  if (base.strategies) {
    const strategies = Array.from(el("sell-params").querySelectorAll(".selector-item")).map((card, idx) => {
      const sub = base.strategies[idx];
      const params = {};
      card.querySelectorAll("[data-param]").forEach((input) => {
        const pKey = input.dataset.param;
        if (input.dataset.paramType === "json") {
          try {
            params[pKey] = JSON.parse(input.value);
          } catch {
            params[pKey] = input.value;
          }
        } else if (input.type === "checkbox") {
          params[pKey] = input.checked;
        } else if (input.type === "number") {
          params[pKey] = Number(input.value);
        } else {
          params[pKey] = input.value;
        }
      });
      return { class: sub.class, params };
    });
    return { ...base, strategies };
  }

  const params = {};
  el("sell-params").querySelectorAll("[data-param]").forEach((input) => {
    const keyName = input.dataset.param;
    if (input.dataset.paramType === "json") {
      try {
        params[keyName] = JSON.parse(input.value);
      } catch {
        params[keyName] = input.value;
      }
    } else if (input.type === "checkbox") {
      params[keyName] = input.checked;
    } else if (input.type === "number") {
      params[keyName] = Number(input.value);
    } else {
      params[keyName] = input.value;
    }
  });
  return { ...base, params };
}

function buildPayload() {
  const stockPoolType = el("stock-pool-type").value;
  const stockPool = stockPoolType === "list" ? { type: "list", codes: state.stockCodes } : { type: "all" };

  return {
    name: el("session-name").value || "Backtest",
    start_date: el("start-date").value,
    end_date: el("end-date").value,
    initial_capital: Number(el("initial-capital").value),
    max_positions: Number(el("max-positions").value),
    position_sizing: el("position-sizing").value,
    lookback_days: Number(el("lookback-days").value),
    commission_rate: Number(el("commission-rate").value),
    stamp_tax_rate: Number(el("stamp-tax-rate").value),
    slippage_rate: Number(el("slippage-rate").value),
    buy_config: { selectors: parseSelectorsPayload() },
    sell_strategy_name: el("sell-strategy").value,
    sell_strategy_config: parseSellStrategyPayload(),
    stock_pool: stockPool,
  };
}

function updateProgress(status) {
  const progress = status.progress ?? 0;
  el("progress-fill").style.width = `${progress}%`;
  el("progress-label").textContent = `${status.status} · ${progress}%`;
}

function updateLogs(logs = []) {
  const panel = el("log-panel");
  panel.innerHTML = logs.map((log) => `${log.ts || ""} ${log.message}`).join("<br/>");
  panel.scrollTop = panel.scrollHeight;
}

function drawLineChart(canvas, series, color, fill = false) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.clientWidth * window.devicePixelRatio;
  const height = canvas.clientHeight * window.devicePixelRatio;
  canvas.width = width;
  canvas.height = height;
  ctx.clearRect(0, 0, width, height);

  if (!series.length) return;
  const xs = series.map((p) => p.x);
  const ys = series.map((p) => p.y);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const padding = 24 * window.devicePixelRatio;
  const scaleX = (width - padding * 2) / (xs.length - 1 || 1);
  const scaleY = (height - padding * 2) / (maxY - minY || 1);

  ctx.strokeStyle = color;
  ctx.lineWidth = 2 * window.devicePixelRatio;
  ctx.beginPath();
  series.forEach((point, idx) => {
    const x = padding + idx * scaleX;
    const y = height - padding - (point.y - minY) * scaleY;
    if (idx === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();

  if (fill) {
    ctx.lineTo(width - padding, height - padding);
    ctx.lineTo(padding, height - padding);
    ctx.closePath();
    ctx.fillStyle = color + "33";
    ctx.fill();
  }
}

function drawMultiLineChart(canvas, seriesList, colors, fill = false) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.clientWidth * window.devicePixelRatio;
  const height = canvas.clientHeight * window.devicePixelRatio;
  canvas.width = width;
  canvas.height = height;
  ctx.clearRect(0, 0, width, height);

  const allSeries = seriesList.filter((s) => s && s.length);
  if (!allSeries.length) return;

  const ys = allSeries.flat().map((p) => p.y);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const padding = 24 * window.devicePixelRatio;
  const length = Math.max(...allSeries.map((s) => s.length));
  const scaleX = (width - padding * 2) / (length - 1 || 1);
  const scaleY = (height - padding * 2) / (maxY - minY || 1);

  allSeries.forEach((series, index) => {
    ctx.strokeStyle = colors[index] || "#94a3b8";
    ctx.lineWidth = 2 * window.devicePixelRatio;
    ctx.beginPath();
    series.forEach((point, idx) => {
      const x = padding + idx * scaleX;
      const y = height - padding - (point.y - minY) * scaleY;
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    if (fill && index === 0) {
      ctx.lineTo(padding + (series.length - 1) * scaleX, height - padding);
      ctx.lineTo(padding, height - padding);
      ctx.closePath();
      ctx.fillStyle = colors[index] + "33";
      ctx.fill();
    }
  });
}

function renderCharts(result) {
  if (!result) return;
  const equity = result.equity_curve || [];
  const initial = result.analysis?.summary?.initial_capital || result.analysis?.returns?.final_value || 1;
  const cumReturnSeries = equity.map((row) => ({
    x: row.date,
    y: ((row.total_value / initial) - 1) * 100,
  }));
  const equitySeries = equity.map((row) => ({ x: row.date, y: row.total_value }));

  let peak = -Infinity;
  const drawdownSeries = equity.map((row) => {
    if (row.total_value > peak) peak = row.total_value;
    const dd = peak > 0 ? ((row.total_value - peak) / peak) * 100 : 0;
    return { x: row.date, y: dd };
  });

  const benchmarkSeries = state.benchmarkSeries || [];
  drawMultiLineChart(
    el("chart-return"),
    [cumReturnSeries, benchmarkSeries],
    ["#14b8a6", "#f59e0b"],
    true
  );
  drawLineChart(el("chart-equity"), equitySeries, "#3b82f6", true);
  drawLineChart(el("chart-drawdown"), drawdownSeries, "#ef4444", true);
}

function renderResults(result) {
  if (!result) return;
  state.latestResult = result;
  const analysis = result.analysis || {};
  const returns = analysis.returns || {};
  const trades = analysis.trade_stats || {};

  el("stat-trades").textContent = trades.total_trades ?? "-";
  el("stat-win").textContent = trades.win_rate_pct ? `${trades.win_rate_pct.toFixed(1)}%` : "-";
  el("stat-return").textContent = returns.total_return_pct ? `${returns.total_return_pct.toFixed(2)}%` : "-";
  el("stat-capital").textContent = returns.final_value ? `¥${Number(returns.final_value).toLocaleString()}` : "-";

  const score = result.strategy_score || {};
  el("rating-score").textContent = score.score ?? "-";
  el("rating-return").style.width = `${Math.min(100, Math.max(0, (score.components?.total_return_pct || 0)))}%`;
  el("rating-risk").style.width = `${Math.min(100, Math.max(0, 100 - (score.components?.max_drawdown_pct || 0)))}%`;

  const exitReasons = analysis.distributions?.exit_reasons || {};
  const exitContainer = el("exit-reasons");
  exitContainer.innerHTML = "";
  Object.entries(exitReasons).forEach(([reason, count]) => {
    const pill = document.createElement("div");
    pill.className = "pill";
    pill.textContent = `${reason} · ${count}`;
    exitContainer.appendChild(pill);
  });

  const tradeTable = el("trade-table");
  const tradeFilter = el("trade-filter");
  const tradeSort = el("trade-sort");
  const tradeData = result.trades || [];

  const reasons = Array.from(new Set(tradeData.map((t) => t.exit_reason))).filter(Boolean);
  tradeFilter.innerHTML = "<option value=''>All Reasons</option>";
  reasons.forEach((reason) => {
    const option = document.createElement("option");
    option.value = reason;
    option.textContent = reason;
    tradeFilter.appendChild(option);
  });

  function renderTradeRows() {
    const filterValue = tradeFilter.value;
    const sortKey = tradeSort.value;
    const filtered = tradeData.filter((t) => !filterValue || t.exit_reason === filterValue);
    filtered.sort((a, b) => (b[sortKey] ?? 0) - (a[sortKey] ?? 0));

    tradeTable.innerHTML = "";
    filtered.forEach((trade) => {
      const row = document.createElement("tr");
      const cells = [
        trade.code,
        trade.entry_date,
        trade.exit_date,
        trade.holding_days,
        trade.entry_price,
        trade.exit_price,
        trade.shares,
        `${trade.net_pnl_pct ?? 0}%`,
        trade.net_pnl ?? 0,
        trade.exit_reason,
      ];
      cells.forEach((cell) => {
        const td = document.createElement("td");
        td.textContent = cell;
        row.appendChild(td);
      });
      tradeTable.appendChild(row);
    });
  }

  tradeFilter.onchange = renderTradeRows;
  tradeSort.onchange = renderTradeRows;
  renderTradeRows();
  renderCharts(result);
}

async function pollBacktest(jobId) {
  if (state.polling) clearInterval(state.polling);
  state.polling = setInterval(async () => {
    try {
      const status = await api.get(`/api/backtests/${jobId}`);
      updateProgress(status);
      updateLogs(status.logs || []);
      if (["COMPLETED", "FAILED", "CANCELLED"].includes(status.status)) {
        clearInterval(state.polling);
        state.polling = null;
        if (status.result) {
          renderResults(status.result);
        }
        await refreshHistory();
        await refreshRankings();
      }
    } catch (err) {
      console.error(err);
    }
  }, 2000);
}

async function refreshHistory() {
  const data = await api.get("/api/backtests");
  const list = el("history-list");
  list.innerHTML = "";
  data.items.forEach((item) => {
    const div = document.createElement("div");
    div.className = "history-item";
    const title = document.createElement("strong");
    title.textContent = item.name;
    const meta = document.createElement("div");
    meta.className = "tiny";
    meta.textContent = `${item.status} · ${item.start_date} → ${item.end_date}`;
    const metrics = document.createElement("div");
    metrics.className = "tiny";
    metrics.textContent = item.metrics
      ? `Return ${item.metrics.total_return_pct?.toFixed?.(2) || 0}% · Score ${item.metrics.score ?? "-"}`
      : "No metrics";
    div.appendChild(title);
    div.appendChild(meta);
    div.appendChild(metrics);
    list.appendChild(div);
  });
}

async function refreshRankings() {
  const data = await api.get("/api/rankings");
  const list = el("ranking-list");
  list.innerHTML = "";
  data.items.slice(0, 8).forEach((item, idx) => {
    const div = document.createElement("div");
    div.className = "history-item";
    const title = document.createElement("strong");
    title.textContent = `${idx + 1}. ${item.name}`;
    const meta = document.createElement("div");
    meta.className = "tiny";
    meta.textContent = `Score ${item.metrics?.score ?? "-"} · Return ${item.metrics?.total_return_pct?.toFixed?.(2) || 0}%`;
    div.appendChild(title);
    div.appendChild(meta);
    list.appendChild(div);
  });
}

async function loadConfig() {
  try {
    const config = await api.get("/api/config");
    state.config = config;
    renderSelectors(config.selectors);
    renderSellStrategies(config.sell_strategies);
    renderSellParams(Object.keys(config.sell_strategies)[0]);
    el("sell-strategy").value = Object.keys(config.sell_strategies)[0];
    setStatus("Online", true);
  } catch (err) {
    console.error(err);
    setStatus("Offline", false);
  }
}

function parseCSV(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => {
      const text = reader.result;
      const lines = text.split(/\r?\n/).filter(Boolean);
      const codes = lines.map((line) => line.split(",")[0].trim()).filter(Boolean);
      resolve(codes);
    };
    reader.readAsText(file);
  });
}

async function init() {
  await loadConfig();
  await refreshHistory();
  await refreshRankings();

  el("sell-strategy").addEventListener("change", (event) => {
    renderSellParams(event.target.value);
  });

  el("run-backtest").addEventListener("click", async () => {
    try {
      const payload = buildPayload();
      const res = await api.post("/api/backtests", payload);
      state.currentJobId = res.id;
      updateProgress({ status: "RUNNING", progress: 0 });
      pollBacktest(res.id);
    } catch (err) {
      alert(`Failed to start: ${err.message}`);
    }
  });

  el("stop-backtest").addEventListener("click", async () => {
    if (!state.currentJobId) return;
    await api.post(`/api/backtests/${state.currentJobId}/cancel`, {});
  });

  el("save-template").addEventListener("click", async () => {
    const name = prompt("Template name?");
    if (!name) return;
    const payload = buildPayload();
    payload.name = name;
    await api.post("/api/templates", { name, ...payload });
    alert("Template saved.");
  });

  el("load-templates").addEventListener("click", async () => {
    const data = await api.get("/api/templates");
    if (!data.items.length) {
      alert("No templates.");
      return;
    }
    const list = data.items.map((item, idx) => `${idx + 1}. ${item.name}`).join("\n");
    const choice = prompt(`Select template:\n${list}`);
    const index = Number(choice) - 1;
    if (!Number.isFinite(index) || index < 0 || index >= data.items.length) return;
    const payload = data.items[index].payload;
    applyTemplate(payload);
  });

  el("refresh-config").addEventListener("click", loadConfig);

  el("benchmark-select").addEventListener("change", async (event) => {
    if (!state.latestResult) return;
    const benchmark = event.target.value;
    if (!benchmark) {
      state.benchmarkSeries = [];
      renderCharts(state.latestResult);
      return;
    }
    try {
      const payload = buildPayload();
      const data = await api.get(
        `/api/benchmark?name=${benchmark}&start=${payload.start_date}&end=${payload.end_date}`
      );
      state.benchmarkSeries = (data.series || []).map((item) => ({
        x: item.date,
        y: (item.nav - 1) * 100,
      }));
      renderCharts(state.latestResult);
    } catch (err) {
      state.benchmarkSeries = [];
      renderCharts(state.latestResult);
    }
  });

  el("stock-csv").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    state.stockCodes = await parseCSV(file);
    const preview = el("stock-preview");
    preview.innerHTML = "";
    state.stockCodes.slice(0, 10).forEach((code) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = code;
      preview.appendChild(chip);
    });
  });
}

function applyTemplate(payload) {
  el("session-name").value = payload.name || "";
  el("start-date").value = payload.start_date || "2024-01-01";
  el("end-date").value = payload.end_date || "2024-12-31";
  el("initial-capital").value = payload.initial_capital || 1000000;
  el("max-positions").value = payload.max_positions || 10;
  el("position-sizing").value = payload.position_sizing || "equal_weight";
  el("lookback-days").value = payload.lookback_days || 200;
  el("commission-rate").value = payload.commission_rate || 0.0003;
  el("stamp-tax-rate").value = payload.stamp_tax_rate || 0.001;
  el("slippage-rate").value = payload.slippage_rate || 0.001;

  if (payload.buy_config?.selectors) {
    state.config.selectors = payload.buy_config.selectors;
    renderSelectors(payload.buy_config.selectors);
  }

  if (payload.sell_strategy_name) {
    el("sell-strategy").value = payload.sell_strategy_name;
    renderSellParams(payload.sell_strategy_name);
  }
}

init();
