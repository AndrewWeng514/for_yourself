"use strict";

// ---------- 基金实仓 ----------
const F = { funds: [], errors: [], loaded: false, busy: false, results: [], selected: null };

const esc = DSH.escape;
const fMoney = DSH.money;
const fNum = DSH.numOrDash;

function fundBadge(f) {
  const kind = f.market === "ETF" ? "etf" : (f.market === "MONEY" ? "money" : "otc");
  const label = f.market === "ETF" ? "场内" : (f.market === "MONEY" ? "货币" : "场外");
  const type = String(f.fund_type || "").split("-")[0];
  const text = f.market === "MONEY" ? "货币" : (type ? label + "·" + type : label);
  return `<span class="fund-type ${kind}" title="${esc(f.fund_type || label)}">${esc(text)}</span>`;
}

function fundQuoteTime(value) {
  const s = String(value || "");
  if (/^\d{14}$/.test(s)) {
    return s.slice(4, 6) + "-" + s.slice(6, 8) + " " + s.slice(8, 10) + ":" + s.slice(10, 12);
  }
  return s;
}

function fundPriceCell(f) {
  if (f.market === "MONEY") {
    const y = (f.seven_day_yield == null) ? "—" : Number(f.seven_day_yield).toFixed(2) + "%";
    const w = (f.wanfen == null) ? "—" : Number(f.wanfen).toFixed(4);
    return `7日年化 ${y}<span class="fund-price-sub">万份收益 ${w}</span>`;
  }
  if (f.market === "ETF") {
    const price = (f.price == null) ? "—" : Number(f.price).toFixed(3);
    let sub = "实时价";
    if (f.pct != null) {
      const pct = Number(f.pct);
      sub = `<span class="${pct >= 0 ? "pos" : "neg"}">${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%</span>`;
    }
    return `${price}<span class="fund-price-sub">${sub}${f.quote_time ? " · " + fundQuoteTime(f.quote_time) : ""}</span>`;
  }
  const nav = (f.nav == null ? f.price : f.nav);
  const navText = (nav == null) ? "—" : Number(nav).toFixed(4);
  return `${navText}<span class="fund-price-sub">净值日期 ${esc(f.nav_date || "—")}</span>`;
}

function fundReturnCell(f) {
  if (f.return_1y == null || !isFinite(Number(f.return_1y))) return "—";
  const r = Number(f.return_1y);
  return `<span class="${r >= 0 ? "pos" : "neg"}">${r >= 0 ? "+" : ""}${r.toFixed(2)}%</span>`;
}

function fundStatus(text, kind) {
  const el = document.getElementById("fund-save-status");
  if (!el) return;
  el.textContent = text || "";
  el.className = "save-status" + (kind ? " " + kind : "");
}

function renderFundErrors() {
  const box = document.getElementById("fund-errors");
  if (!box) return;
  if (F.errors.length) {
    box.innerHTML = "<strong>行情提示：</strong>" + F.errors.map(esc).join("；");
    box.classList.remove("hidden");
  } else {
    box.classList.add("hidden");
  }
}

function renderFundSummary() {
  const el = document.getElementById("fund-summary");
  if (!el) return;
  const total = F.funds.reduce((a, f) => a + Number(f.value || 0), 0);
  let sum = 0, weight = 0, up = 0;
  F.funds.forEach((f) => {
    const r = Number(f.return_1y);
    const v = Number(f.value || 0);
    if (isFinite(r)) {
      sum += r * v;
      weight += v;
      if (r > 0) up += 1;
    }
  });
  const avg = weight > 0 ? sum / weight : null;
  const avgText = avg == null ? "—" : `${avg >= 0 ? "+" : ""}${avg.toFixed(2)}%`;
  const cards = [
    { icon: "&#128176;", label: "基金市值", value: "¥" + fMoney(total) },
    { icon: "&#128200;", label: "近1年收益（加权）", value: avgText, cls: avg == null ? "" : (avg >= 0 ? "pos" : "neg") },
    { icon: "&#128994;", label: "近1年上涨", value: `${up} / ${F.funds.length}` },
    { icon: "&#128220;", label: "持仓数量", value: String(F.funds.length) },
  ];
  el.innerHTML = cards.map((c, i) => `
    <div class="summary-item${i === 1 ? " highlight" : ""}">
      <div class="summary-icon">${c.icon}</div>
      <div class="summary-label">${c.label}</div>
      <div class="summary-value ${c.cls || ""}">${c.value}</div>
    </div>`).join("");
}

function updateCount(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = String(value);
}

function renderFunds() {
  updateCount("htab-fund-count", F.funds.length);
  const body = document.getElementById("fund-body");
  const foot = document.getElementById("fund-foot");
  if (!body || !foot) return;
  if (!F.funds.length) {
    body.innerHTML = '<tr><td colspan="8" class="c-name muted">暂无基金，点「添加基金」开始记录。</td></tr>';
    foot.innerHTML = "";
  } else {
    body.innerHTML = F.funds.map((f, i) => `
      <tr data-row="${i}">
        <td class="c-name">${esc(f.name)}</td>
        <td>${esc(f.code)}</td>
        <td>${fundBadge(f)}</td>
        <td class="num"><input id="f-shares-${i}" class="editable" type="number" min="0" step="100" value="${Number(f.shares || 0)}" data-code="${esc(f.code)}"></td>
        <td class="num">${fundPriceCell(f)}</td>
        <td class="num">${fMoney(f.value)}</td>
        <td class="num">${fundReturnCell(f)}</td>
        <td><button class="btn-del" type="button" data-fdel="${esc(f.code)}">删除</button></td>
      </tr>`).join("");
    const total = F.funds.reduce((a, f) => a + Number(f.value || 0), 0);
    let sum = 0, weight = 0;
    F.funds.forEach((f) => {
      const r = Number(f.return_1y);
      const v = Number(f.value || 0);
      if (isFinite(r)) { sum += r * v; weight += v; }
    });
    const avg = weight > 0 ? sum / weight : null;
    foot.innerHTML = `<tr>
      <td class="c-name">合计</td><td></td><td></td><td></td><td></td>
      <td class="num">${fMoney(total)}</td>
      <td class="num ${avg == null ? "" : (avg >= 0 ? "pos" : "neg")}">${avg == null ? "—" : (avg >= 0 ? "+" : "") + avg.toFixed(2) + "%"}</td>
      <td></td>
    </tr>`;
  }
  renderFundSummary();
  renderFundErrors();
  applyFundSearch();
  updateHoldingsTotal();
}

function updateFundStatus() {
  const dot = document.getElementById("fund-dot");
  const text = document.getElementById("fund-live-text");
  const time = document.getElementById("fund-fetched");
  if (dot) dot.className = "dot " + (F.funds.length ? "live" : "offline");
  if (text) text.textContent = F.funds.length ? `基金 ${F.funds.length} 只` : "暂无基金";
  if (time) time.textContent = F.fetched_at ? "更新于 " + F.fetched_at : "";
}

function applyFundSearch() {
  const q = (document.getElementById("fund-search")?.value || "").trim().toLowerCase();
  document.querySelectorAll("#fund-body tr[data-row]").forEach((tr) => {
    const f = F.funds[Number(tr.dataset.row)];
    const hit = !q || (f && ((f.name || "").toLowerCase().includes(q) || (f.code || "").includes(q)));
    tr.hidden = !hit;
  });
}

function currentStockValue() {
  if (typeof state === "undefined" || !state.config) return 0;
  return (state.config.stocks || []).reduce((a, s) => {
    const q = (state.quotes && state.quotes.quotes) ? state.quotes.quotes[s.code] : null;
    const price = (q && q.is_live_price && q.price != null) ? q.price : s.price;
    return a + Number(s.shares_held || 0) * Number(price || 0);
  }, 0);
}

function updateHoldingsTotal() {
  const el = document.getElementById("holdings-total");
  if (!el) return;
  const stock = (typeof window.__stockValue === "number") ? window.__stockValue : currentStockValue();
  const fund = F.loaded ? F.funds.reduce((a, f) => a + Number(f.value || 0), 0) : 0;
  if (!F.loaded) {
    el.textContent = stock ? `股票 ¥${fMoney(stock)}` : "";
    return;
  }
  if (!stock && !fund) { el.textContent = ""; return; }
  el.textContent = `合计 ¥${fMoney(stock + fund)}（股票 ¥${fMoney(stock)} + 基金 ¥${fMoney(fund)}）`;
}

async function loadFunds(refresh) {
  if (F.busy) return;
  F.busy = true;
  fundStatus(refresh ? "正在更新基金净值…" : "");
  try {
    const resp = await fetch("/api/funds" + (refresh ? "?refresh=1" : ""), { cache: "no-store" });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || "加载失败");
    F.funds = data.funds || [];
    F.errors = data.errors || [];
    F.fetched_at = data.fetched_at || "";
    F.loaded = true;
    if (refresh) fundStatus("已更新", "ok");
    renderFunds();
    updateFundStatus();
  } catch (err) {
    fundStatus("更新失败：" + err, "err");
    const body = document.getElementById("fund-body");
    if (body) body.innerHTML = `<tr><td colspan="8" class="c-name muted">加载失败：${esc(err)}</td></tr>`;
  } finally {
    F.busy = false;
  }
}

async function saveFundShares(reload = true) {
  const shares = {};
  document.querySelectorAll("#fund-body input[data-code]").forEach((el) => {
    shares[el.dataset.code] = Number(el.value || 0);
  });
  if (!Object.keys(shares).length) return true;
  fundStatus("正在保存…");
  try {
    const resp = await fetch("/api/funds/shares", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shares }),
    });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || "保存失败");
    fundStatus("已保存", "ok");
    if (reload) await loadFunds(false);
    return true;
  } catch (err) {
    fundStatus("保存失败：" + err, "err");
    return false;
  }
}

async function updateFunds() {
  const saved = await saveFundShares(false);
  if (!saved) return;
  await loadFunds(true);
  if (F.errors && F.errors.length) {
    fundStatus("份额已保存；部分基金更新失败", "err");
  } else {
    fundStatus("已保存并更新", "ok");
  }
}

async function deleteFund(code) {
  if (!confirm("确定从持仓中删除这只基金吗？")) return;
  try {
    const resp = await fetch("/api/funds?code=" + encodeURIComponent(code), { method: "DELETE" });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || "删除失败");
    fundStatus("已删除", "ok");
    await loadFunds(false);
  } catch (err) {
    fundStatus("删除失败：" + err, "err");
  }
}

function switchHoldingsTab(tab) {
  const isFund = tab === "fund";
  document.querySelectorAll("#holdings-tabs .seg-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.htab === tab);
    btn.setAttribute("aria-selected", btn.dataset.htab === tab ? "true" : "false");
  });
  const stockPanel = document.getElementById("stock-panel");
  const fundPanel = document.getElementById("fund-panel");
  if (stockPanel) stockPanel.hidden = isFund;
  if (fundPanel) fundPanel.hidden = !isFund;
  if (isFund && !F.loaded) loadFunds(false);
  updateHoldingsTotal();
}

// ---------- 添加基金弹窗 ----------
function openFundModal() {
  F.results = [];
  F.selected = null;
  const input = document.getElementById("fund-lookup-input");
  const results = document.getElementById("fund-results");
  const shares = document.getElementById("fund-shares-row");
  const status = document.getElementById("fund-lookup-status");
  const confirm = document.getElementById("btn-fund-confirm");
  if (input) input.value = "";
  if (results) results.innerHTML = "";
  if (shares) shares.hidden = true;
  if (status) { status.textContent = ""; status.className = "save-status"; }
  if (confirm) confirm.disabled = true;
  document.getElementById("fund-modal").hidden = false;
  if (input) setTimeout(() => input.focus(), 50);
}

function closeFundModal() {
  document.getElementById("fund-modal").hidden = true;
}

function selectFundResult(idx) {
  const item = F.results[idx];
  if (!item) return;
  F.selected = item;
  document.querySelectorAll("#fund-results .fund-result").forEach((el, i) => {
    el.classList.toggle("selected", i === idx);
  });
  document.getElementById("fund-shares-row").hidden = false;
  document.getElementById("btn-fund-confirm").disabled = false;
  const status = document.getElementById("fund-lookup-status");
  if (status) {
    status.textContent = `已选择 ${item.name}（${item.code}）`;
    status.className = "save-status ok";
  }
}

function renderFundResults(results) {
  const el = document.getElementById("fund-results");
  if (!el) return;
  if (!results.length) {
    el.innerHTML = '<p class="muted">没有找到匹配的基金。</p>';
    return;
  }
  el.innerHTML = results.map((r, i) => `
    <div class="fund-result" data-idx="${i}">
      <div class="fund-result-name">${esc(r.name)}<span class="fund-result-code">${esc(r.code)}</span></div>
      <div class="fund-result-meta">${esc(r.market === "ETF" ? "场内" : (r.market === "MONEY" ? "货币" : "场外"))} · ${esc(r.fund_type || "—")} · ${esc(r.company || "—")}${r.nav != null ? " · 净值 " + Number(r.nav).toFixed(4) + "（" + esc(r.nav_date || "—") + "）" : ""}</div>
    </div>`).join("");
}

async function lookupFund() {
  const q = (document.getElementById("fund-lookup-input").value || "").trim();
  const status = document.getElementById("fund-lookup-status");
  const confirm = document.getElementById("btn-fund-confirm");
  if (!q) {
    if (status) { status.textContent = "请输入基金代码或名称"; status.className = "save-status err"; }
    return;
  }
  if (status) { status.textContent = "正在查询…"; status.className = "save-status"; }
  if (confirm) confirm.disabled = true;
  F.selected = null;
  document.getElementById("fund-shares-row").hidden = true;
  try {
    const resp = await fetch("/api/fund/lookup?q=" + encodeURIComponent(q), { cache: "no-store" });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || "查询失败");
    F.results = data.results || [];
    renderFundResults(F.results);
    if (status) {
      status.textContent = F.results.length ? "请选择一只基金" : "没有找到匹配的基金";
      status.className = "save-status" + (F.results.length ? "" : " err");
    }
    if (F.results.length === 1) selectFundResult(0);
  } catch (err) {
    if (status) { status.textContent = "查询失败：" + err; status.className = "save-status err"; }
  }
}

async function confirmAddFund() {
  if (!F.selected) return;
  const shares = Number(document.getElementById("fund-shares-input").value || 0);
  const status = document.getElementById("fund-lookup-status");
  if (status) { status.textContent = "正在添加…"; status.className = "save-status"; }
  try {
    const resp = await fetch("/api/funds/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: F.selected.code, shares }),
    });
    const data = await resp.json();
    if (!data.ok) {
      const msg = data.exists ? "该基金已在持仓中" : ("添加失败：" + (data.error || "未知错误"));
      if (status) { status.textContent = msg; status.className = "save-status err"; }
      return;
    }
    closeFundModal();
    fundStatus("已添加 " + F.selected.name + "，请填写份额", "ok");
    await loadFunds(true);
  } catch (err) {
    if (status) { status.textContent = "添加失败：" + err; status.className = "save-status err"; }
  }
}

function bindFundEvents() {
  document.querySelectorAll("#holdings-tabs .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchHoldingsTab(btn.dataset.htab));
  });
  document.getElementById("btn-fund-add").addEventListener("click", openFundModal);
  document.getElementById("btn-fund-refresh").addEventListener("click", updateFunds);
  document.getElementById("fund-search").addEventListener("input", applyFundSearch);
  document.getElementById("btn-fund-modal-close").addEventListener("click", closeFundModal);
  document.getElementById("btn-fund-cancel").addEventListener("click", closeFundModal);
  document.getElementById("fund-modal").addEventListener("click", (e) => {
    if (e.target.id === "fund-modal") closeFundModal();
  });
  document.getElementById("btn-fund-lookup").addEventListener("click", lookupFund);
  document.getElementById("fund-lookup-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); lookupFund(); }
  });
  document.getElementById("fund-results").addEventListener("click", (e) => {
    const item = e.target.closest(".fund-result");
    if (item) selectFundResult(Number(item.dataset.idx));
  });
  document.getElementById("btn-fund-confirm").addEventListener("click", confirmAddFund);
  document.getElementById("fund-body").addEventListener("click", (e) => {
    const del = e.target.closest("[data-fdel]");
    if (del) deleteFund(del.dataset.fdel);
  });
  window.addEventListener("stocks:updated", (e) => {
    window.__stockValue = Number((e.detail && e.detail.value) || 0);
    updateCount("htab-stock-count", Number((e.detail && e.detail.count) || 0));
    updateHoldingsTotal();
  });
}

function initFunds() {
  bindFundEvents();
  if (typeof state !== "undefined" && state.config) {
    updateCount("htab-stock-count", (state.config.stocks || []).length);
  }
  // 基金行情首屏不加载，切到「基金」子页签时由 switchHoldingsTab 触发加载
}

document.addEventListener("DOMContentLoaded", initFunds);
