"use strict";

// ---------- 储蓄计划页面 ----------
const S = { plan: null, trend: null, latest: null, trendMode: "week", forecastMonths: 3, monthlyAuto: true };

const DEFAULT_ITEMS = [
  { category: "asset", name: "中信股票", amount: 0 },
  { category: "asset", name: "支付宝", amount: 0 },
  { category: "asset", name: "招商基金", amount: 0 },
  { category: "asset", name: "流动备用金", amount: 0 },
  { category: "asset", name: "招商固定", amount: 0 },
  { category: "liability", name: "负债", amount: 0 },
];

const sMoney = DSH.money0;
const sWan = DSH.wan;
const sPct = DSH.pct1;
const sEsc = DSH.escape;
const sSetText = DSH.setText;

function normalizeItems(items) {
  if (!Array.isArray(items)) return [];
  return items.map((x) => ({
    category: x.category === "liability" ? "liability" : "asset",
    name: String(x.name == null ? "" : x.name).trim(),
    amount: Math.abs(Number(x.amount || 0)) || 0,
  })).filter((x) => x.name);
}
function itemsFromAccounts(accounts) {
  if (!accounts || typeof accounts !== "object") return [];
  const items = [];
  Object.entries(accounts).forEach(([name, raw]) => {
    const amount = Math.abs(Number(raw || 0));
    if (name === "负债") {
      items.push({ category: "liability", name, amount });
    } else {
      items.push({ category: "asset", name, amount });
    }
  });
  return items;
}
function latestPoint() {
  // 快照与趋势按时间取最新：趋势图用什么，KPI 和资产面板就用什么。
  const weeks = (S.trend && Array.isArray(S.trend.weeks)) ? S.trend.weeks : [];
  const week = weeks.length ? weeks[weeks.length - 1] : null;
  const manual = (S.latest && Array.isArray(S.latest.items) && S.latest.items.length) ? S.latest : null;
  const manualTs = manual ? String(manual.recorded_at || "") : "";
  const weekTs = week ? String(week.ts || "") : "";
  if (manual && (!week || manualTs > weekTs)) {
    return {
      items: normalizeItems(manual.items),
      source: "manual",
      week: manual.week || "",
      ts: manualTs,
    };
  }
  if (week) {
    const items = (Array.isArray(week.items) && week.items.length)
      ? normalizeItems(week.items)
      : itemsFromAccounts(week.accounts || {});
    return {
      items: items,
      source: week.source || "database",
      week: week.week || "",
      ts: weekTs,
    };
  }
  return null;
}
function snapshotItems() {
  const point = latestPoint();
  if (point && point.items.length) return point.items;
  return DEFAULT_ITEMS.map((x) => ({ ...x }));
}
function sNetWorth() {
  return snapshotItems().reduce((a, x) => (
    a + (x.category === "liability" ? -Math.abs(x.amount) : x.amount)
  ), 0);
}
function sMonthly() {
  return Number(S.plan && S.plan.monthly_invest || 0);
}

// ---------- 预测模型（按实际日期、按月化速度） ----------
// ISO 周标签 → 该周周一（UTC，仅用于推算日期）
function sWeekMonday(label) {
  const m = /^(\d{4})-W(\d{2})$/.exec(String(label || ""));
  if (!m) return null;
  const year = Number(m[1]), week = Number(m[2]);
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const offset = (jan4.getUTCDay() + 6) % 7;
  return new Date(jan4.getTime() - offset * 86400000 + (week - 1) * 7 * 86400000);
}

// 每个点用于拟合的日期：使用快照的录入日期
function sPointDate(w) {
  // 数据库快照用实际录入日；缺 ts 时退化为该周周日
  if (w.ts) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(w.ts));
    if (m) return new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  }
  const mon = sWeekMonday(w.week);
  return mon ? new Date(mon.getTime() + 6 * 86400000) : null;
}

// 取时间窗口内的点做最小二乘拟合，返回月均净增（含定投/市场/一次性收支）
function sForecastData() {
  const all = (S.trend && Array.isArray(S.trend.all_weeks))
    ? S.trend.all_weeks
    : ((S.trend && S.trend.weeks) || []);
  const months = [3, 6, 12].includes(Number(S.forecastMonths)) ? Number(S.forecastMonths) : 3;
  const cutoff = Date.now() - months * 30.44 * 86400000;
  const points = all.map((w) => {
    const d = sPointDate(w);
    return d ? { t: d.getTime(), net: Number(w.net), source: w.source } : null;
  }).filter((p) => p && isFinite(p.net) && p.t >= cutoff)
    .sort((a, b) => a.t - b.t);
  if (points.length < 2) return { months, points, insufficient: true };
  const spanDays = (points[points.length - 1].t - points[0].t) / 86400000;
  if (spanDays < 14) return { months, points, insufficient: true, spanDays };
  const xs = points.map((p) => (p.t - points[0].t) / 86400000);
  const ys = points.map((p) => p.net);
  const n = xs.length;
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = ys.reduce((a, b) => a + b, 0) / n;
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) {
    num += (xs[i] - mx) * (ys[i] - my);
    den += (xs[i] - mx) * (xs[i] - mx);
  }
  if (!den) return { months, points, insufficient: true, spanDays };
  const perDay = num / den;
  return {
    months, points, insufficient: false, spanDays, count: n,
    perDay, perWeek: perDay * 7, perMonth: perDay * 30.44,
  };
}

// 当前口径下的月投：自动=历史月均（负值取 0）；历史不足回退输入值；固定=输入值
function sMonthlyUsed(f) {
  if (S.monthlyAuto) {
    if (f.insufficient) return { value: Math.max(0, sMonthly()), mode: "fallback" };
    return { value: Math.max(0, f.perMonth), mode: "auto" };
  }
  return { value: Math.max(0, sMonthly()), mode: "fixed" };
}

// 单档情景：月投为 0 → 只滚余额；月投 >0 → 按月复利 + 定投（时间统一用月）
function sScenario(rate, nw, target, monthly) {
  if (target <= nw) return { years: 0, months: 0 };
  if (monthly > 0) {
    const r = rate / 12;
    let bal = nw, m = 0;
    while (bal < target && m < 1200) { bal = bal * (1 + r) + monthly; m++; }
    return { years: m / 12, months: m };
  }
  if (rate <= 0) return { years: Infinity, months: Infinity };
  const y = Math.log(target / nw) / Math.log(1 + rate);
  return { years: y, months: y * 12 };
}

function sMonthLabel(years) {
  const d = new Date();
  const end = new Date(d.getFullYear(), d.getMonth() + Math.ceil(years * 12), 1);
  return end.getFullYear() + " 年 " + (end.getMonth() + 1) + " 月";
}

function sMonthsText(months) {
  return isFinite(months) ? sMoney(Math.round(months)) + " 个月" : "—";
}

const FORECAST_BAD_YEARS = 20;  // 6% 下超过 20 年视为“暂不能达标”

function sIsBad(res) {
  return !isFinite(res.years) || res.years > FORECAST_BAD_YEARS;
}

function renderForecast() {
  const valueEl = document.getElementById("savings-forecast-value");
  const noteEl = document.getElementById("savings-forecast-note");
  if (!valueEl || !noteEl) return;
  valueEl.textContent = "—";
  valueEl.className = "";
  noteEl.textContent = "";
  noteEl.className = "forecast-note";

  const nw = sNetWorth();
  const target = Number(S.plan && S.plan.target || 0);
  if (!target) { valueEl.textContent = "未设置目标"; return; }
  if (target <= nw) { valueEl.textContent = "已达标"; noteEl.textContent = "当前净资产已超过目标"; return; }

  const f = sForecastData();
  const used = sMonthlyUsed(f);
  const six = sScenario(0.06, nw, target, used.value);
  const plan = sScenario(0.06, nw, target, sMonthly());

  let basis;
  if (used.mode === "auto") {
    const pm = f.perMonth;
    basis = "近 " + f.months + " 个月月均 " + (pm < 0 ? "−" : "+") +
      "¥" + sMoney(Math.abs(pm));
  } else if (used.mode === "fallback") {
    basis = "历史数据不足，按默认月投 ¥" + sMoney(used.value);
  } else {
    basis = "固定月投 ¥" + sMoney(used.value);
  }
  const sameAsPlan = Math.abs(used.value - sMonthly()) < 0.5;
  const planNote = (!sameAsPlan && isFinite(plan.months) && plan.months > 0)
    ? "；计划 " + sMonthsText(plan.months)
    : "";

  if (sIsBad(six)) {
    valueEl.textContent = "暂不能达标";
    valueEl.className = "bad";
    noteEl.textContent = basis +
      (isFinite(six.years)
        ? "；6% 下约 " + six.years.toFixed(1) + " 年（" + sMonthsText(six.months) + "）"
        : "；6% 下不可达") +
      planNote;
    return;
  }
  valueEl.textContent = "还需 " + sMonthsText(six.months);
  noteEl.textContent = basis + "；约 " + six.years.toFixed(1) + " 年 · " +
    sMonthLabel(six.years) + planNote;
}

function renderKpi() {
  const nw = sNetWorth();
  const target = Number(S.plan.target || 0);
  const f = sForecastData();
  const used = sMonthlyUsed(f);
  const six = sScenario(0.06, nw, target, used.value);

  sSetText("overview-monthly-label", S.monthlyAuto ? "自动月投（按历史）" : "每月定投（手动）");
  sSetText("overview-monthly", "¥" + sMoney(used.value));
  let monthlyNote = "";
  if (used.mode === "auto") {
    const pm = f.perMonth;
    monthlyNote = "月均 " + (pm < 0 ? "−" : "+") + "¥" + sMoney(Math.abs(pm)) +
      (pm < 0 ? "，按 0 计" : "");
  } else if (used.mode === "fallback") {
    monthlyNote = "历史不足，按默认 ¥" + sMoney(used.value) + "/月";
  } else {
    monthlyNote = "按输入值计算";
  }
  sSetText("overview-monthly-note", monthlyNote);

  const etaEl = document.getElementById("overview-eta");
  if (!target) {
    if (etaEl) { etaEl.textContent = "—"; etaEl.className = ""; }
    sSetText("overview-eta-note", "未设置目标");
  } else if (nw >= target) {
    if (etaEl) { etaEl.textContent = "已达标"; etaEl.className = ""; }
    sSetText("overview-eta-note", "当前净资产已超过目标");
  } else {
    if (etaEl) {
      etaEl.textContent = isFinite(six.months) ? sMonthsText(six.months) : "—";
      etaEl.className = sIsBad(six) ? "bad" : "";
    }
    sSetText("overview-eta-note", isFinite(six.years)
      ? "约 " + six.years.toFixed(1) + " 年" + (sIsBad(six) ? " · 需关注" : "")
      : "当前口径下不可达");
  }
}

function renderGoal() {
  const nw = sNetWorth();
  const target = Number(S.plan.target || 0);
  const gap = target - nw;
  const pct = target > 0 ? Math.max(0, Math.min(100, nw / target * 100)) : 0;
  sSetText("savings-nw", sWan(nw));
  sSetText("savings-target", sWan(target));
  const bar = document.getElementById("savings-progress-bar");
  if (bar) bar.style.width = pct.toFixed(1) + "%";
  sSetText("savings-goal-meta", "缺口 " + sWan(Math.max(0, gap)) + "（进度 " + pct.toFixed(1) + "%）");
  const ti = document.getElementById("savings-target-input");
  if (ti) ti.value = target;

  const f = sForecastData();
  const used = sMonthlyUsed(f);
  const mi = document.getElementById("savings-monthly-input");
  if (mi) {
    mi.disabled = S.monthlyAuto;
    mi.value = S.monthlyAuto ? Math.round(used.value) : sMonthly();
  }
  const autoEl = document.getElementById("savings-monthly-auto");
  if (autoEl) autoEl.checked = S.monthlyAuto;
  const hint = document.getElementById("savings-auto-hint");
  if (hint) {
    if (!S.monthlyAuto) hint.textContent = "当前：手动 ¥" + sMoney(sMonthly());
    else if (used.mode === "fallback") hint.textContent = "当前：自动（默认 ¥" + sMoney(used.value) + "）";
    else hint.textContent = "当前：自动 ¥" + sMoney(used.value) + "/月";
  }
  renderForecast();
}

function renderDisciplines() {
  const ta = document.getElementById("disciplines-input");
  if (ta && S.plan) {
    ta.value = (Array.isArray(S.plan.disciplines) ? S.plan.disciplines : []).join("\n");
  }
}

async function saveDisciplines() {
  const ta = document.getElementById("disciplines-input");
  const status = document.getElementById("disciplines-status");
  const lines = ta ? ta.value.split("\n").map((s) => s.trim()).filter(Boolean) : [];
  if (!S.plan) return;
  S.plan.disciplines = lines;
  if (status) { status.textContent = "正在保存…"; status.className = "save-status"; }
  try {
    const resp = await fetch("/api/savings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ disciplines: lines }),
    });
    const data = await resp.json();
    if (data.ok) {
      if (status) { status.textContent = "已保存"; status.className = "save-status ok"; }
    } else {
      if (status) { status.textContent = "保存失败：" + (data.error || "未知错误"); status.className = "save-status err"; }
    }
  } catch (err) {
    if (status) { status.textContent = "保存失败：" + err; status.className = "save-status err"; }
  }
}

function renderScenarios() {
  const nw = sNetWorth();
  const target = Number(S.plan.target || 0);
  const f = sForecastData();
  const used = sMonthlyUsed(f);
  const rows = [
    { name: "纯储蓄", rate: 0 },
    { name: "保守（债/货为主）", rate: 0.04 },
    { name: "基准（债+权益均衡）", rate: 0.06 },
    { name: "积极（权益为主）", rate: 0.08 },
  ];
  const el = document.getElementById("savings-scenarios");
  if (el) el.innerHTML = rows.map((r) => {
    const res = sScenario(r.rate, nw, target, used.value);
    const bad = sIsBad(res);
    const time = isFinite(res.years)
      ? sMonthsText(res.months) + "（" + res.years.toFixed(1) + " 年）"
      : "不可达";
    const date = isFinite(res.years) ? sMonthLabel(res.years) : "—";
    const monthly = used.value > 0 ? "¥" + sMoney(used.value) : "¥0";
    return `<tr>
      <td class="c-name">${r.name}</td>
      <td class="num">${(r.rate * 100).toFixed(0)}%</td>
      <td class="num">${monthly}</td>
      <td class="num${bad ? " bad" : ""}">${time}</td>
      <td class="num${bad ? " bad" : ""}">${date}</td>
    </tr>`;
  }).join("");
}

function renderAccounts() {
  const items = snapshotItems();
  const nw = sNetWorth();
  const assets = items.filter((x) => x.category === "asset");
  const liabilities = items.filter((x) => x.category === "liability");
  const assetTotal = assets.reduce((a, x) => a + x.amount, 0);
  const liabilityTotal = liabilities.reduce((a, x) => a + x.amount, 0);
  const pctBase = assetTotal > 0 ? assetTotal : nw;
  const listHtml = (list) => {
    if (!list.length) {
      return '<div class="asset-line asset-line-empty"><span class="asset-line-name muted">暂无模块</span><span></span><span></span></div>';
    }
    return list.map((x) => `<div class="asset-line">
      <span class="asset-line-name">${sEsc(x.name)}</span>
      <span class="asset-line-pct">${sPct(pctBase !== 0 ? x.amount / pctBase : 0)}</span>
      <span class="asset-line-amount">${sMoney(x.amount)}</span>
    </div>`).join("");
  };
  const assetList = document.getElementById("asset-list");
  const liabilityList = document.getElementById("liability-list");
  if (assetList) assetList.innerHTML = listHtml(assets);
  if (liabilityList) liabilityList.innerHTML = listHtml(liabilities);
  sSetText("asset-total-label", sMoney(assetTotal));
  sSetText("liability-total-label", sMoney(liabilityTotal));
  sSetText("asset-net-value", sMoney(nw));
  const point = latestPoint();
  sSetText("asset-source", point
    ? (point.source === "manual" ? "来源：手动快照" : "来源：数据库") +
      (point.week ? " · " + point.week : "")
    : "来源：暂无记录");
}

// ---------- 趋势图 ----------
function drawTrendSvg(points) {
  if (!points || points.length < 2) {
    return '<div class="placeholder"><p class="placeholder-title">数据点不足</p><p class="placeholder-desc">录入资产快照后即可看到趋势。</p></div>';
  }
  const W = 860, H = 300, L = 64, R = 16, T = 18, B = 40;
  const iw = W - L - R, ih = H - T - B;
  const vals = points.map((p) => p.net);
  let min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
  if (max === min) { min -= 10000; max += 10000; }
  const pad = (max - min) * 0.18;
  min -= pad; max += pad;
  const span = max - min;
  const x = (i) => (points.length === 1 ? L + iw / 2 : L + (i * iw) / (points.length - 1));
  const y = (v) => T + ih - ((v - min) / span) * ih;
  const rising = points[points.length - 1].net >= points[0].net;
  const lineColor = rising ? "#F54A45" : "#0a7d3a";
  const fmtY = (v) => (Math.abs(v) >= 10000 ? (v / 10000).toFixed(1) + "w" : Math.round(v).toLocaleString("zh-CN"));
  let grid = "";
  for (let i = 0; i <= 4; i++) {
    const val = min + (span * i) / 4;
    const yy = y(val);
    grid += `<line x1="${L}" y1="${yy}" x2="${W - R}" y2="${yy}" stroke="#ebedf0" stroke-width="1"/>`;
    grid += `<text x="${L - 8}" y="${yy + 4}" text-anchor="end" font-size="12" fill="#8a8f99">${fmtY(val)}</text>`;
  }
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.net).toFixed(1)}`).join(" ");
  const labels = points.map((p, i) => `<text x="${x(i)}" y="${H - 14}" text-anchor="middle" font-size="11" fill="#8a8f99">${sEsc(p.label)}</text>`).join("");
  const dots = points.map((p, i) => `<circle cx="${x(i)}" cy="${y(p.net)}" r="3.6" fill="${lineColor}"><title>${sEsc(p.label)} 净资产 ${p.net.toLocaleString("zh-CN")}</title></circle>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${grid}<path d="${d}" fill="none" stroke="${lineColor}" stroke-width="2.4" stroke-linejoin="round"/>${dots}${labels}</svg>`;
}

function renderTrendChart() {
  const el = document.getElementById("savings-trend-chart");
  if (!el) return;
  const t = S.trend;
  if (!t || !t.weeks || !t.weeks.length) {
    el.innerHTML = '<div class="placeholder"><p class="placeholder-title">暂无趋势数据</p><p class="placeholder-desc">点「更新当前资产」录入一次快照。</p></div>';
    sSetText("trend-latest", "");
    return;
  }
  let points;
  if (S.trendMode === "month" && t.months && t.months.length) {
    points = t.months.map((m) => ({ label: m.month.slice(5) + "月", net: m.net }));
  } else if (S.trendMode === "year" && t.years && t.years.length) {
    points = t.years.map((y) => ({ label: y.year, net: y.net }));
  } else {
    points = t.weeks.map((w) => ({ label: w.week.replace(/.*(?=W)/, ""), net: w.net }));
  }
  if (points.length === 1) {
    const p = points[0];
    el.innerHTML = `<div class="single-point">
      <div class="single-point-label">${sEsc(p.label)} 净资产</div>
      <div class="single-point-value">${sWan(p.net)}</div>
      <div class="single-point-note">当前仅有一个数据点，后续录入后会自动形成趋势线。</div>
    </div>`;
  } else {
    el.innerHTML = drawTrendSvg(points);
  }
  const latest = document.getElementById("trend-latest");
  if (!latest) return;
  if (S.trendMode === "year" && t.years && t.years.length) {
    const y = t.years[t.years.length - 1];
    latest.textContent = y.year + " 年：" + sWan(y.net) +
      (t.years.length < 2 ? "（后续年度自动形成趋势）" : "");
  } else if (S.trendMode === "month" && t.months && t.months.length) {
    const m = t.months[t.months.length - 1];
    latest.textContent = m.month + "：" + sWan(m.net) +
      (m.change == null ? "" : "（较上月 " + (m.change >= 0 ? "+" : "") + sWan(m.change) + "）");
  } else {
    const last = t.weeks[t.weeks.length - 1];
    latest.textContent = "最新 " + last.week + "：" + sWan(last.net) +
      (last.change == null ? "" : "（较上周 " + (last.change >= 0 ? "+" : "") + sWan(last.change) + "）");
  }
}

function levelSign(n) {
  if (n == null) return "—";
  return n > 0 ? "+" + sMoney(n) : sMoney(n);
}
function levelCls(n) {
  if (n == null || n === 0) return "num";
  return "num " + (n > 0 ? "pos" : "neg");
}

function renderLevels() {
  const el = document.getElementById("savings-levels");
  if (!el || !S.trend) return;
  const t = S.trend;
  let html = "";
  if (t.year) {
    html += `<div class="level-block"><div class="level-title">年（${sEsc(t.year.year)}）</div><div class="table-wrap"><table class="grid"><thead><tr><th>起点周</th><th>最新周</th><th>年初净资产</th><th>最新净资产</th><th>年度变动</th></tr></thead><tbody><tr><td class="c-name">${sEsc(t.year.first_week || "—")}</td><td class="c-name">${sEsc(t.year.last_week || "—")}</td><td class="num">${sMoney(t.year.first_net)}</td><td class="num">${sMoney(t.year.net)}</td><td class="${levelCls(t.year.change)}">${levelSign(t.year.change)}</td></tr></tbody></table></div></div>`;
  }
  if (t.quarters && t.quarters.length) {
    html += `<div class="level-block"><div class="level-title">季</div><div class="table-wrap"><table class="grid"><thead><tr><th>季度</th><th>季末净资产</th><th>较上季</th><th>最新周</th></tr></thead><tbody>` +
      t.quarters.map((q) => `<tr><td class="c-name">${sEsc(q.quarter)}</td><td class="num">${sMoney(q.net)}</td><td class="${levelCls(q.change)}">${levelSign(q.change)}</td><td class="c-name">${sEsc(q.last_week)}</td></tr>`).join("") +
      `</tbody></table></div></div>`;
  }
  if (t.months && t.months.length) {
    html += `<div class="level-block"><div class="level-title">月</div><div class="table-wrap"><table class="grid"><thead><tr><th>月份</th><th>月末净资产</th><th>较上月</th><th>月内变动</th><th>最新周</th></tr></thead><tbody>` +
      t.months.map((m) => `<tr><td class="c-name">${sEsc(m.month)}</td><td class="num">${sMoney(m.net)}</td><td class="${levelCls(m.change)}">${levelSign(m.change)}</td><td class="${levelCls(m.month_delta)}">${levelSign(m.month_delta)}</td><td class="c-name">${sEsc(m.last_week)}</td></tr>`).join("") +
      `</tbody></table></div></div>`;
  }
  if (t.weeks && t.weeks.length) {
    html += `<div class="level-block"><div class="level-title">周</div><div class="table-wrap"><table class="grid"><thead><tr><th>周</th><th>净资产</th><th>较上周</th></tr></thead><tbody>` +
      t.weeks.map((w) => `<tr><td class="c-name">${sEsc(w.week)}</td><td class="num">${sMoney(w.net)}</td><td class="${levelCls(w.change)}">${levelSign(w.change)}</td></tr>`).join("") +
      `</tbody></table></div></div>`;
  }
  el.innerHTML = html || '<p class="muted">暂无数据，录入资产快照后自动生成。</p>';
  if (t.year) {
    const ch = t.year.change;
    sSetText("levels-summary", "最新 " + (t.year.last_week || "—") + "：" + sWan(t.year.net) +
      " · 年度 " + (ch == null ? "—" : (ch >= 0 ? "+" : "") + sWan(ch)));
  } else {
    sSetText("levels-summary", "");
  }
}

function renderTrend() {
  renderTrendChart();
  renderLevels();
}

function bindTrendEvents() {
  const seg = document.getElementById("trend-mode");
  if (!seg) return;
  seg.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-mode]");
    if (!btn) return;
    seg.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
    S.trendMode = btn.dataset.mode;
    renderTrendChart();
  });
}

// ---------- 资产快照弹窗 ----------
function addItemRow(category, name = "", amount = 0, focus = true) {
  const container = document.getElementById(category === "asset" ? "asset-rows" : "liability-rows");
  if (!container) return;
  const row = document.createElement("div");
  row.className = "item-row";
  row.dataset.category = category;
  row.innerHTML = `
    <input class="item-name" type="text" placeholder="模块名称" value="${sEsc(name)}">
    <input class="item-amount" type="number" step="1" min="0" placeholder="0" value="${amount ? Number(amount) : ""}">
    <button class="btn-del item-remove" type="button">删除</button>`;
  container.appendChild(row);
  if (focus && !name) {
    const input = row.querySelector(".item-name");
    if (input) input.focus();
  }
}

function renderModalItems(items) {
  const assetRows = document.getElementById("asset-rows");
  const liabilityRows = document.getElementById("liability-rows");
  if (!assetRows || !liabilityRows) return;
  assetRows.innerHTML = "";
  liabilityRows.innerHTML = "";
  items.filter((x) => x.category === "asset")
    .forEach((x) => addItemRow("asset", x.name, x.amount, false));
  items.filter((x) => x.category === "liability")
    .forEach((x) => addItemRow("liability", x.name, x.amount, false));
  if (!assetRows.children.length) addItemRow("asset", "", 0, false);
  if (!liabilityRows.children.length) addItemRow("liability", "", 0, false);
}

function collectModalItems() {
  const out = [];
  document.querySelectorAll("#savings-modal .item-row").forEach((row) => {
    const nameEl = row.querySelector(".item-name");
    const amountEl = row.querySelector(".item-amount");
    const name = (nameEl && nameEl.value || "").trim();
    if (!name) return;
    out.push({
      category: row.dataset.category,
      name,
      amount: Math.abs(Number(amountEl && amountEl.value || 0)),
    });
  });
  return out;
}

function openSnapshotModal() {
  openSnapshotModalWith(null);
}
function openSnapshotModalWith(items) {
  renderModalItems(items || snapshotItems().map((x) => ({ ...x })));
  refreshNetPreview();
  setSnapshotStatus("", "");
  const del = document.getElementById("btn-snapshot-delete");
  if (del) {
    del.disabled = !S.latest;
    del.title = S.latest ? "删除最后一次手动快照" : "暂无手动快照可删除";
  }
  document.getElementById("savings-modal").hidden = false;
}
function closeSnapshotModal() {
  document.getElementById("savings-modal").hidden = true;
}

// 股票实仓总市值（用于「从持仓同步」）
function stockHoldingsValue() {
  if (typeof state === "undefined" || !state.config || !Array.isArray(state.config.stocks)) return 0;
  const stockValue = state.config.stocks.reduce((a, s) => {
    const q = (state.quotes && state.quotes.quotes) ? state.quotes.quotes[s.code] : null;
    const price = (q && q.is_live_price && q.price != null) ? q.price : s.price;
    return a + Number(s.shares_held || 0) * Number(price || 0);
  }, 0);
  return stockValue + Math.max(0, Number(state.config.stock_cash || 0));
}

// 把股票、基金实仓市值填入快照的「中信股票 / 招商基金」，打开弹窗供核对
async function syncSnapshotFromHoldings() {
  if (typeof F !== "undefined" && !F.loaded) {
    try { await loadFunds(false); } catch (err) { /* 基金加载失败按 0 处理 */ }
  }
  const stockValue = stockHoldingsValue();
  const fundValue = (typeof F !== "undefined" && Array.isArray(F.funds))
    ? F.funds.reduce((a, f) => a + Number(f.value || 0), 0) : 0;
  const items = snapshotItems().map((x) => ({ ...x }));
  const setOrPush = (name, value) => {
    const found = items.find((x) => x.category === "asset" && x.name === name);
    if (found) found.amount = Math.round(value);
    else items.push({ category: "asset", name, amount: Math.round(value) });
  };
  setOrPush("中信股票", stockValue);
  setOrPush("招商基金", fundValue);
  openSnapshotModalWith(items);
  setSnapshotStatus("已按持仓填入「中信股票 / 招商基金」，请核对后点「保存快照」", "ok");
}
async function refreshAllHoldings() {
  const btn = document.getElementById("btn-holdings-refresh-all");
  if (!btn || btn.disabled) return;
  const status = document.getElementById("holdings-save-status");
  btn.disabled = true;
  btn.classList.add("spinning");
  if (status) { status.textContent = "正在保存并刷新…"; status.className = "save-status"; }
  try {
    const cashOk = await saveCash(false);
    const stockOk = await saveHoldings();
    const fundOk = await saveFundShares(false);
    if (!cashOk || !stockOk || !fundOk) {
      if (status) { status.textContent = "保存失败，已停止刷新"; status.className = "save-status err"; }
      return;
    }
    await Promise.all([refreshQuotes(false), loadFunds(true)]);
    if (status) { status.textContent = "股票和基金已刷新"; status.className = "save-status ok"; }
  } catch (err) {
    if (status) { status.textContent = "刷新失败：" + err.message; status.className = "save-status err"; }
  } finally {
    btn.disabled = false;
    btn.classList.remove("spinning");
  }
}

function refreshNetPreview() {
  const items = collectModalItems();
  const assets = items.filter((x) => x.category === "asset")
    .reduce((a, x) => a + x.amount, 0);
  const liabilities = items.filter((x) => x.category === "liability")
    .reduce((a, x) => a + x.amount, 0);
  const net = assets - liabilities;
  sSetText("snap-asset-subtotal", sMoney(assets));
  sSetText("snap-liability-subtotal", sMoney(liabilities));
  const preview = document.getElementById("snap-net-preview");
  if (preview) preview.textContent = sMoney(net);
}

function setSnapshotStatus(text, cls) {
  ["snapshot-modal-status", "savings-snapshot-status"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = text;
      el.className = "save-status" + (cls ? " " + cls : "");
    }
  });
}

function bindModalEvents() {
  document.getElementById("btn-savings-snapshot").addEventListener("click", openSnapshotModal);
  document.getElementById("btn-savings-modal-close").addEventListener("click", closeSnapshotModal);
  document.getElementById("btn-snapshot-cancel").addEventListener("click", closeSnapshotModal);
  const modal = document.getElementById("savings-modal");
  modal.addEventListener("input", refreshNetPreview);
  modal.addEventListener("click", (e) => {
    if (e.target.id === "savings-modal") {
      closeSnapshotModal();
      return;
    }
    const remove = e.target.closest(".item-remove");
    if (remove) {
      const row = remove.closest(".item-row");
      if (row) row.remove();
      refreshNetPreview();
    }
  });
  document.getElementById("btn-add-asset-item").addEventListener("click", () => {
    addItemRow("asset");
    refreshNetPreview();
  });
  document.getElementById("btn-add-liability-item").addEventListener("click", () => {
    addItemRow("liability");
    refreshNetPreview();
  });
  document.getElementById("btn-snapshot-save").addEventListener("click", saveSnapshot);
  document.getElementById("btn-snapshot-delete").addEventListener("click", deleteSnapshot);
}

async function saveSnapshot() {
  const items = collectModalItems();
  if (!items.length) {
    setSnapshotStatus("请至少填写一个资产或负债模块", "err");
    return;
  }
  const seen = new Set();
  for (const item of items) {
    const key = item.category + "|" + item.name;
    if (seen.has(key)) {
      setSnapshotStatus("同一类别下的模块名称不能重复：" + item.name, "err");
      return;
    }
    seen.add(key);
  }
  setSnapshotStatus("正在保存…", "");
  try {
    const resp = await fetch("/api/savings/snapshot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });
    const data = await resp.json();
    if (data.ok) {
      setSnapshotStatus("已保存（" + (data.snapshot && data.snapshot.week || "") + "）", "ok");
      closeSnapshotModal();
      await reloadSavingsData();
    } else {
      setSnapshotStatus("保存失败：" + (data.error || "未知错误"), "err");
    }
  } catch (err) {
    setSnapshotStatus("保存失败：" + err, "err");
  }
}

async function deleteSnapshot() {
  if (!confirm("确定删除最后一次资产快照吗？删除后趋势会回退到上一条记录。")) return;
  setSnapshotStatus("正在删除…", "");
  try {
    const resp = await fetch("/api/savings/snapshot", { method: "DELETE", cache: "no-store" });
    const data = await resp.json();
    if (data.ok) {
      setSnapshotStatus("已删除最后一次快照", "ok");
      closeSnapshotModal();
      await reloadSavingsData();
    } else {
      setSnapshotStatus("删除失败：" + (data.error || "未知错误"), "err");
    }
  } catch (err) {
    setSnapshotStatus("删除失败：" + err, "err");
  }
}

// ---------- 目标设置 ----------
function bindSavingsEvents() {
  document.getElementById("savings-target-input").addEventListener("input", (e) => {
    S.plan.target = Number(e.target.value) || 0;
    recalcDisplay();
  });
  document.getElementById("savings-monthly-input").addEventListener("input", (e) => {
    S.plan.monthly_invest = Number(e.target.value) || 0;
    recalcDisplay();
  });
  document.getElementById("btn-savings-save").addEventListener("click", savePlan);
  const levelsBtn = document.getElementById("btn-levels-toggle");
  if (levelsBtn) {
    levelsBtn.addEventListener("click", () => {
      const body = document.getElementById("levels-body");
      if (!body) return;
      body.hidden = !body.hidden;
      levelsBtn.textContent = body.hidden ? "展开明细" : "收起明细";
    });
  }
  const discBtn = document.getElementById("btn-disciplines-save");
  if (discBtn) discBtn.addEventListener("click", saveDisciplines);
  const syncBtn = document.getElementById("btn-snapshot-sync");
  if (syncBtn) syncBtn.addEventListener("click", syncSnapshotFromHoldings);
  const refreshAllBtn = document.getElementById("btn-holdings-refresh-all");
  if (refreshAllBtn) refreshAllBtn.addEventListener("click", refreshAllHoldings);
  const fw = document.getElementById("savings-forecast-window");
  if (fw) {
    fw.value = String(S.forecastMonths);
    fw.addEventListener("change", () => {
      const v = Number(fw.value);
      S.forecastMonths = [3, 6, 12].includes(v) ? v : 3;
      try { localStorage.setItem("savings.forecastMonths", String(S.forecastMonths)); } catch (err) { /* 忽略隐私模式限制 */ }
      recalcDisplay();
    });
  }
  const autoEl = document.getElementById("savings-monthly-auto");
  if (autoEl) {
    autoEl.addEventListener("change", () => {
      S.monthlyAuto = !!autoEl.checked;
      try { localStorage.setItem("savings.monthlyAuto", S.monthlyAuto ? "1" : "0"); } catch (err) { /* 忽略 */ }
      recalcDisplay();
    });
  }
  bindModalEvents();
  bindTrendEvents();
}

async function savePlan() {
  const status = document.getElementById("savings-save-status");
  status.textContent = "正在保存…";
  status.className = "save-status";
  try {
    const resp = await fetch("/api/savings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target: S.plan.target,
        monthly_invest: S.plan.monthly_invest,
      }),
    });
    const data = await resp.json();
    if (data.ok) {
      status.textContent = "已保存";
      status.className = "save-status ok";
    } else {
      status.textContent = "保存失败：" + (data.error || "未知错误");
      status.className = "save-status err";
    }
  } catch (err) {
    status.textContent = "保存失败：" + err;
    status.className = "save-status err";
  }
}

function recalcDisplay() {
  renderKpi();
  renderGoal();
  renderScenarios();
  renderAccounts();
}

function renderAll() {
  renderKpi();
  renderGoal();
  renderScenarios();
  renderAccounts();
  renderTrend();
  renderDisciplines();
}

async function reloadSavingsData() {
  try {
    const [resp, tresp, sresp] = await Promise.all([
      fetch("/api/savings", { cache: "no-store" }),
      fetch("/api/trend", { cache: "no-store" }),
      fetch("/api/savings/snapshot", { cache: "no-store" }),
    ]);
    S.plan = await resp.json();
    S.trend = await tresp.json();
    const snapData = await sresp.json();
    S.latest = (snapData && snapData.latest) || null;
  } catch (err) {
    sSetText("savings-goal-meta", "加载储蓄计划失败：" + err);
    return;
  }
  renderAll();
}

async function initSavings() {
  try {
    const saved = Number(localStorage.getItem("savings.forecastMonths"));
    if ([3, 6, 12].includes(saved)) S.forecastMonths = saved;
    const auto = localStorage.getItem("savings.monthlyAuto");
    if (auto === "0") S.monthlyAuto = false;
    if (auto === "1") S.monthlyAuto = true;
  } catch (err) { /* 隐私模式下忽略 */ }
  await reloadSavingsData();
  bindSavingsEvents();
}

document.addEventListener("DOMContentLoaded", initSavings);
