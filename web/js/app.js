"use strict";

// ---------- 股票实仓与预计年分红（实时行情） ----------
let state = {
  config: null,       // { total_principal, stocks: [...] }
  quotes: null,       // 最近一次行情结果
  lookup: null,       // 添加股票时的查询结果
};

// 数字与文本工具统一由 common.js 提供
const fmt = DSH.fmt;
const fmtMoney = DSH.money;
const fmtOpt = DSH.numOrDash;
const pct = DSH.pct;
const pctOpt = DSH.pctOrDash;
const escapeHtml = DSH.escape;
const setText = DSH.setText;

function parseInput(el) {
  const raw = (el.value || "").trim().replace(/%/g, "");
  const v = parseFloat(raw);
  return isNaN(v) ? 0 : v;
}
function quoteFor(code) {
  return state.quotes && state.quotes.quotes ? state.quotes.quotes[code] : null;
}
function currentCodes() {
  return (state.config && state.config.stocks ? state.config.stocks : [])
    .map((s) => s.code)
    .filter(Boolean);
}

function applySearch() {
  if (!state.config || !state.config.stocks) return;
  const q = (document.getElementById("holdings-search").value || "").trim().toLowerCase();
  document.querySelectorAll("#holdings-body tr[data-row]").forEach((tr) => {
    const i = parseInt(tr.dataset.row, 10);
    const s = state.config && state.config.stocks[i];
    const hit = !q || (s && ((s.name || "").toLowerCase().includes(q) || (s.code || "").toLowerCase().includes(q)));
    tr.hidden = !hit;
  });
}

function readRow(i) {
  const s = state.config.stocks[i];
  const heldEl = document.getElementById("h-held-" + i);
  if (heldEl) s.shares_held = parseInput(heldEl);
}

function readCash() {
  const el = document.getElementById("h-cash");
  if (!el || !state.config) return Number(state.config && state.config.stock_cash || 0);
  const cash = Math.max(0, Number(el.value || 0) || 0);
  state.config.stock_cash = cash;
  return cash;
}

function recalc() {
  if (!state.config || !state.config.stocks) return;
  const stocks = state.config.stocks;
  for (let i = 0; i < stocks.length; i++) readRow(i);
  const cash = readCash();

  let sumValue = 0, sumDividend = 0;
  let hasValue = false, hasDividend = false;
  stocks.forEach((s, i) => {
    const q = quoteFor(s.code);
    const held = Number(s.shares_held || 0);
    const livePrice = q && q.is_live_price ? q.price : null;
    const per10 = q && q.is_live_yield ? q.per10 : null;
    const value = livePrice == null ? null : held * livePrice;
    const dividend = per10 == null ? null : held * per10 / 10;
    if (value != null) { sumValue += value; hasValue = true; }
    if (dividend != null) { sumDividend += dividend; hasDividend = true; }
    setText("h-price-" + i, fmtOpt(livePrice, 2));
    setText("h-yield-" + i, q && q.is_live_yield ? pctOpt(q.yield, 2) : "—");
    setText("h-value-" + i, fmtOpt(value, 2));
    setText("h-dividend-" + i, fmtOpt(dividend, 2));
  });

  const totalValue = sumValue + cash;
  if (cash > 0) hasValue = true;
  setText("holdings-sum-value", hasValue ? fmtMoney(totalValue) : "—");
  setText("holdings-sum-dividend", hasDividend ? fmtMoney(sumDividend) : "—");
  setText("holdings-sum-yield",
    sumValue > 0 && hasDividend ? pct(sumDividend / sumValue, 3) : "—");
  setText("holdings-sum-count", String(stocks.length));

  setText("holdings-foot-value", hasValue ? fmtMoney(totalValue) : "—");
  setText("holdings-foot-dividend", hasDividend ? fmtMoney(sumDividend) : "—");
  renderHoldingsSummary(totalValue, sumDividend, stocks.length, hasValue, hasDividend, sumValue);
  window.dispatchEvent(new CustomEvent("stocks:updated", {
    detail: { value: hasValue ? totalValue : 0, count: stocks.length },
  }));
}

function renderHoldingsSummary(sumValue, sumDividend, count, hasValue, hasDividend, stockValue) {
  const el = document.getElementById("holdings-summary");
  if (!el) return;
  const cards = [
    { icon: "&#128200;", label: "实仓总市值（元）", value: hasValue ? fmtMoney(sumValue) : "—" },
    { icon: "&#128184;", label: "预计年分红（元）", value: hasDividend ? fmtMoney(sumDividend) : "—" },
    {
      icon: "&#128202;", label: "实仓综合股息率",
      value: stockValue > 0 && hasDividend ? pct(sumDividend / stockValue, 3) : "—",
    },
    { icon: "&#128220;", label: "持仓数量", value: String(count) },
  ];
  el.innerHTML = cards.map((x, i) => `
    <div class="summary-item${i === 1 ? " highlight" : ""}">
      <div class="summary-icon">${x.icon}</div>
      <div class="summary-label">${x.label}</div>
      <div class="summary-value">${x.value}</div>
    </div>`).join("");
}

function buildTables() {
  if (!state.config || !state.config.stocks) return;
  const stocks = state.config.stocks;

  const body = document.getElementById("holdings-body");
  const cash = Math.max(0, Number(state.config.stock_cash || 0));
  body.innerHTML = stocks.map((s, i) => `<tr data-row="${i}">
    <td class="c-name">${escapeHtml(s.name)}</td>
    <td>${escapeHtml(s.code)}</td>
    <td class="num"><input id="h-held-${i}" class="editable" type="number" step="100" min="0" value="${Number(s.shares_held || 0)}" data-idx="${i}" data-kind="held"></td>
    <td class="num" id="h-price-${i}">—</td>
    <td class="num" id="h-value-${i}">—</td>
    <td class="num" id="h-yield-${i}">—</td>
    <td class="num" id="h-dividend-${i}">—</td>
    <td><button class="btn-del" type="button" data-idx="${i}" data-kind="del">删除</button></td>
  </tr>`).join("") + `<tr class="cash-row">
    <td class="c-name">现金（股票账户零钱）</td>
    <td>—</td>
    <td class="num">—</td>
    <td class="num">—</td>
    <td class="num"><input id="h-cash" class="editable" type="number" step="0.01" min="0" value="${cash.toFixed(2)}" data-kind="cash" aria-label="股票账户现金"></td>
    <td class="num">—</td>
    <td class="num">—</td>
    <td>—</td>
  </tr>`;

  document.getElementById("holdings-foot").innerHTML = `<tr>
    <td class="c-name">合计</td>
    <td></td><td></td><td></td>
    <td class="num" id="holdings-foot-value">—</td>
    <td></td>
    <td class="num" id="holdings-foot-dividend">—</td>
    <td></td>
  </tr>`;

  recalc();
  applySearch();
  updateLiveStatus();
}

function applyQuotes() {
  if (!state.config || !state.config.stocks) return;
  const stocks = state.config.stocks;
  stocks.forEach((s) => {
    const q = quoteFor(s.code);
    if (q && q.is_live_price && q.price != null) s.price = q.price;
    if (q && q.is_live_yield && q.yield != null) s.ref_yield = q.yield;
  });
  recalc();
}

function updateLiveStatus() {
  const dot = document.getElementById("live-dot");
  const text = document.getElementById("live-text");
  const timeEl = document.getElementById("fetched-time");
  if (!dot || !text) return;
  if (!state.quotes) {
    dot.className = "dot offline";
    text.textContent = "尚未获取行情";
    if (timeEl) timeEl.textContent = "";
    return;
  }
  const quotes = state.quotes.quotes || {};
  const codes = currentCodes();
  if (!codes.length) {
    dot.className = "dot offline";
    text.textContent = "暂无实仓股票";
    if (timeEl) timeEl.textContent = "";
    return;
  }
  const livePrice = codes.filter((c) => quotes[c].is_live_price).length;
  const liveYield = codes.filter((c) => quotes[c].is_live_yield).length;
  if (livePrice > 0) {
    dot.className = "dot live";
    text.textContent = `实时行情 ${livePrice}/${codes.length} 只 · 股息率 ${liveYield}/${codes.length} 只`;
  } else {
    dot.className = "dot offline";
    text.textContent = "未获取到实时行情";
  }
  if (timeEl) timeEl.textContent = state.quotes.fetched_at ? "更新于 " + state.quotes.fetched_at : "";
}

function renderErrors(errors) {
  const box = document.getElementById("errors-box");
  if (!box) return;
  if (errors && errors.length) {
    box.innerHTML = "<strong>行情提示：</strong>" + errors.map(escapeHtml).join("；");
    box.classList.remove("hidden");
  } else {
    box.classList.add("hidden");
  }
}

async function refreshQuotes(showSpinner = true) {
  const btn = document.getElementById("btn-holdings-refresh-all");
  if (showSpinner && btn) { btn.disabled = true; btn.classList.add("spinning"); }
  try {
    const resp = await fetch("/api/quotes", { cache: "no-store" });
    const data = await resp.json();
    const fetchedCodes = Object.keys(data.quotes || {});
    const localCodes = currentCodes();
    const sameSet = fetchedCodes.length === localCodes.length &&
      fetchedCodes.every((code) => localCodes.includes(code));
    if (!sameSet) {
      try {
        const cfgResp = await fetch("/api/config", { cache: "no-store" });
        const fresh = await cfgResp.json();
        const localShares = {};
        (state.config && state.config.stocks ? state.config.stocks : []).forEach((s) => {
          if (s.code) localShares[s.code] = s.shares_held;
        });
        (fresh.stocks || []).forEach((s) => {
          if (Object.prototype.hasOwnProperty.call(localShares, s.code)) {
            s.shares_held = localShares[s.code];
          }
        });
        state.config = fresh;
        buildTables();
      } catch (syncErr) {
        /* 行情已取到，配置同步失败时保持当前列表 */
      }
    }
    state.quotes = data;
    applyQuotes();
    updateLiveStatus();
    renderErrors(data.errors);
  } catch (err) {
    state.quotes = {
      live: false, quotes: {},
      errors: ["无法连接本地服务：" + err],
      fetched_at: new Date().toLocaleString("zh-CN"),
    };
    applyQuotes();
    updateLiveStatus();
    renderErrors(state.quotes.errors);
  } finally {
    if (showSpinner && btn) { btn.disabled = false; btn.classList.remove("spinning"); }
  }
}

async function saveCash(showStatus = true) {
  const cash = readCash();
  const status = document.getElementById("holdings-save-status");
  if (showStatus && status) {
    status.textContent = "正在保存现金…";
    status.className = "save-status";
  }
  try {
    const resp = await fetch("/api/stocks/cash", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cash }),
    });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || "保存失败");
    state.config.stock_cash = Number(data.stock_cash || 0);
    recalc();
    if (showStatus && status) {
      status.textContent = "现金已保存";
      status.className = "save-status ok";
    }
    return true;
  } catch (err) {
    if (showStatus && status) {
      status.textContent = "现金保存失败：" + err.message;
      status.className = "save-status err";
    }
    return false;
  }
}

async function saveHoldings() {
  recalc();
  const shares = {};
  state.config.stocks.forEach((s) => {
    if (s.code) shares[s.code] = Number(s.shares_held || 0);
  });
  const status = document.getElementById("holdings-save-status");
  if (status) {
    status.textContent = "正在保存…";
    status.className = "save-status";
  }
  try {
    const resp = await fetch("/api/stocks/shares", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shares }),
    });
    const data = await resp.json();
    if (data.ok) {
      if (status) { status.textContent = "已保存"; status.className = "save-status ok"; }
      return true;
    }
    if (status) {
      status.textContent = "保存失败：" + (data.error || "未知错误");
      status.className = "save-status err";
    }
  } catch (err) {
    if (status) {
      status.textContent = "保存失败：" + err;
      status.className = "save-status err";
    }
  }
  return false;
}

// ---------- 添加股票弹窗 ----------
function openStockModal() {
  state.lookup = null;
  const input = document.getElementById("stock-lookup-input");
  const status = document.getElementById("stock-lookup-status");
  const result = document.getElementById("stock-lookup-result");
  const confirmBtn = document.getElementById("btn-stock-confirm");
  if (input) input.value = "";
  if (status) { status.textContent = ""; status.className = "save-status"; }
  if (result) { result.hidden = true; result.innerHTML = ""; }
  if (confirmBtn) confirmBtn.disabled = true;
  document.getElementById("stock-modal").hidden = false;
  if (input) setTimeout(() => input.focus(), 50);
}

function closeStockModal() {
  document.getElementById("stock-modal").hidden = true;
}

async function lookupStock() {
  const input = document.getElementById("stock-lookup-input");
  const status = document.getElementById("stock-lookup-status");
  const result = document.getElementById("stock-lookup-result");
  const confirmBtn = document.getElementById("btn-stock-confirm");
  const q = (input && input.value || "").trim();
  state.lookup = null;
  if (!q) {
    if (status) { status.textContent = "请输入股票代码或名称"; status.className = "save-status err"; }
    return;
  }
  if (status) { status.textContent = "正在查询实时行情…"; status.className = "save-status"; }
  if (confirmBtn) confirmBtn.disabled = true;
  try {
    const resp = await fetch("/api/stock/lookup?q=" + encodeURIComponent(q), { cache: "no-store" });
    const data = await resp.json();
    if (!data.ok) {
      if (status) { status.textContent = data.error || "查询失败"; status.className = "save-status err"; }
      return;
    }
    state.lookup = data;
    if (result) {
      result.innerHTML = `<div class="lookup-name">${escapeHtml(data.name)}<span class="lookup-code">${escapeHtml(data.code)}</span></div>
        <div class="lookup-meta">最新价 ${fmtOpt(data.price, 2)} 元 · 股息率 ${pctOpt(data.yield, 2)}</div>`;
      result.hidden = false;
    }
    if (status) { status.textContent = "已获取实时数据，请确认添加"; status.className = "save-status ok"; }
    if (confirmBtn) confirmBtn.disabled = false;
  } catch (err) {
    if (status) { status.textContent = "查询失败：" + err; status.className = "save-status err"; }
  }
}

async function confirmAddStock() {
  const c = state.lookup;
  if (!c) return;
  if (state.config.stocks.some((s) => s.code === c.code)) {
    const status = document.getElementById("stock-lookup-status");
    if (status) { status.textContent = "该股票已在实仓中"; status.className = "save-status err"; }
    return;
  }
  const status = document.getElementById("holdings-save-status");
  if (status) { status.textContent = "正在添加…"; status.className = "save-status"; }
  try {
    const resp = await fetch("/api/stocks/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: c.name, code: c.code, weight: 0,
        price: c.price, ref_yield: c.yield || 0, shares_held: 0,
      }),
    });
    const data = await resp.json();
    if (!data.ok) {
      const msg = data.exists ? "该股票已在实仓中" : ("添加失败：" + (data.error || "未知错误"));
      if (status) { status.textContent = msg; status.className = "save-status err"; }
      const lookupStatus = document.getElementById("stock-lookup-status");
      if (lookupStatus) { lookupStatus.textContent = msg; lookupStatus.className = "save-status err"; }
      return;
    }
    state.config.stocks.push({
      name: c.name, code: c.code, weight: 0,
      price: c.price, ref_yield: c.yield || 0, shares_held: 0,
    });
    state.quotes = state.quotes || { quotes: {} };
    state.quotes.quotes[c.code] = {
      price: c.price, yield: c.yield, per10: c.per10,
      is_live_price: true, is_live_yield: c.per10 != null,
      ex_date: c.ex_date, quote_name: c.name,
    };
    buildTables();
    closeStockModal();
    if (status) {
      status.textContent = "已添加 " + c.name + "，请填写实仓股数";
      status.className = "save-status ok";
    }
  } catch (err) {
    if (status) { status.textContent = "添加失败：" + err; status.className = "save-status err"; }
  }
}

async function updateHoldings() {
  const saved = await saveHoldings();
  if (!saved) return;
  await refreshQuotes(true);
  const status = document.getElementById("holdings-save-status");
  if (status) {
    if (!state.quotes || !state.quotes.live) {
      status.textContent = "股数已保存；行情更新失败";
      status.className = "save-status err";
    } else {
      status.textContent = "已保存并更新";
      status.className = "save-status ok";
    }
  }
}

async function deleteStock(idx) {
  const s = state.config && state.config.stocks ? state.config.stocks[idx] : null;
  if (!s) return;
  if (!confirm("确定从实仓中删除 " + s.name + "（" + s.code + "）吗？")) return;
  const status = document.getElementById("holdings-save-status");
  if (!s.code) {
    state.config.stocks.splice(idx, 1);
    buildTables();
    return;
  }
  if (status) { status.textContent = "正在删除…"; status.className = "save-status"; }
  try {
    const resp = await fetch("/api/stocks?code=" + encodeURIComponent(s.code), {
      method: "DELETE",
      cache: "no-store",
    });
    const data = await resp.json();
    if (data.ok) {
      state.config.stocks.splice(idx, 1);
      buildTables();
      if (status) { status.textContent = "已删除 " + s.name; status.className = "save-status ok"; }
    } else {
      if (status) { status.textContent = "删除失败：" + (data.error || "未知错误"); status.className = "save-status err"; }
    }
  } catch (err) {
    if (status) { status.textContent = "删除失败：" + err; status.className = "save-status err"; }
  }
}

function bindEvents() {
  const search = document.getElementById("holdings-search");
  if (search) search.addEventListener("input", applySearch);

  document.addEventListener("input", (e) => {
    const el = e.target;
    const kind = el.dataset && el.dataset.kind;
    if (kind === "cash") { recalc(); return; }
    if (kind !== "held") return;
    const idx = parseInt(el.dataset.idx, 10);
    if (isNaN(idx)) return;
    recalc();
  });

  document.addEventListener("change", (e) => {
    const el = e.target;
    if (el && el.id === "h-cash") saveCash();
  });

  document.addEventListener("click", (e) => {
    const del = e.target.closest("[data-kind='del']");
    if (!del) return;
    const idx = parseInt(del.dataset.idx, 10);
    if (!isNaN(idx)) {
      deleteStock(idx);
    }
  });

  document.getElementById("btn-holdings-add").addEventListener("click", openStockModal);

  document.getElementById("btn-stock-modal-close").addEventListener("click", closeStockModal);
  document.getElementById("btn-stock-cancel").addEventListener("click", closeStockModal);
  document.getElementById("stock-modal").addEventListener("click", (e) => {
    if (e.target.id === "stock-modal") closeStockModal();
  });
  document.getElementById("btn-stock-lookup").addEventListener("click", lookupStock);
  document.getElementById("btn-stock-confirm").addEventListener("click", confirmAddStock);
  document.getElementById("stock-lookup-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      lookupStock();
    }
  });

  document.getElementById("sidebar-toggle").addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("collapsed");
  });

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => {
        t.classList.toggle("active", t === tab);
        t.setAttribute("aria-selected", t === tab ? "true" : "false");
      });
      document.querySelectorAll(".tab-panel").forEach((p) => {
        const show = p.id === "tab-" + tab.dataset.tab;
        p.classList.toggle("active", show);
        p.hidden = !show;
      });
      const titleEl = document.getElementById("page-title");
      if (titleEl && tab.dataset.title) titleEl.textContent = tab.dataset.title;
      const subEl = document.getElementById("page-sub");
      if (subEl && tab.dataset.sub) subEl.textContent = tab.dataset.sub;
      window.dispatchEvent(new CustomEvent("tab:shown", { detail: { tab: tab.dataset.tab } }));
    });
  });
}

async function init() {
  bindEvents();
  try {
    const resp = await fetch("/api/config", { cache: "no-store" });
    state.config = await resp.json();
    buildTables();
  } catch (err) {
    const live = document.getElementById("live-text");
    if (live) live.textContent = "加载配置失败：" + err;
  }
  await refreshQuotes(true);
}

async function reloadConfig() {
  try {
    const resp = await fetch("/api/config", { cache: "no-store" });
    const localShares = {};
    if (state.config && state.config.stocks) {
      state.config.stocks.forEach((s) => {
        if (s.code) localShares[s.code] = s.shares_held;
      });
    }
    const fresh = await resp.json();
    (fresh.stocks || []).forEach((s) => {
      if (Object.prototype.hasOwnProperty.call(localShares, s.code)) {
        s.shares_held = localShares[s.code];
      }
    });
    state.config = fresh;
    buildTables();
    await refreshQuotes(false);
  } catch (err) {
    const live = document.getElementById("live-text");
    if (live) live.textContent = "重新加载配置失败：" + err;
  }
}
window.reloadConfig = reloadConfig;  // 动态选股页「加入实仓」后调用，刷新持仓表

document.addEventListener("DOMContentLoaded", init);
