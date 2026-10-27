"use strict";

// ---------- AI 建议 ----------
const AI = { status: null, busy: false, hasAdvice: false, fullText: "", bodyError: false };

function aiSetStatus(text) {
  const el = document.getElementById("advice-status");
  if (el) el.textContent = text ? " · " + text : "";
}

function aiSetMeta(text) {
  const el = document.getElementById("advice-meta");
  if (el) el.textContent = text || "";
}

function aiRenderBody() {
  const el = document.getElementById("advice-body");
  if (!el) return;
  el.textContent = AI.fullText || "";
  el.classList.toggle("bad", AI.bodyError);
}

function aiSetBody(text, bad) {
  AI.fullText = String(text == null ? "" : text);
  AI.bodyError = !!bad;
  const details = document.getElementById("advice-details");
  if (details) details.open = true;
  aiRenderBody();
}

function aiUpdateGenerateButton() {
  const btn = document.getElementById("btn-advice-generate");
  if (btn && !AI.busy) btn.textContent = AI.hasAdvice ? "重新生成" : "生成建议";
}

async function aiLoadStatus() {
  try {
    const resp = await fetch("/api/ai/status", { cache: "no-store" });
    const data = await resp.json();
    AI.status = data;
    aiSetStatus(data.configured ? ("已配置 · " + data.model) : "未配置");
  } catch (err) {
    aiSetStatus("状态未知");
    aiSetBody("读取 AI 配置失败：" + err, true);
  }
}

function buildAdviceContext() {
  const nw = sNetWorth();
  const target = Number(S.plan.target || 0);
  const f = sForecastData();
  const used = sMonthlyUsed(f);
  const six = sScenario(0.06, nw, target, used.value);
  const plan = sScenario(0.06, nw, target, sMonthly());
  const items = snapshotItems();

  const months = ((S.trend && S.trend.months) ? S.trend.months.slice(-12) : []).map((m) => ({
    month: m.month, net: Math.round(m.net),
    change: (m.change == null ? null : Math.round(m.change)),
  }));
  const weeks = ((S.trend && S.trend.weeks) ? S.trend.weeks.slice(-12) : []).map((w) => ({
    week: w.week, net: Math.round(w.net),
    change: (w.change == null ? null : Math.round(w.change)),
  }));
  const assets = items.filter((x) => x.category === "asset")
    .map((x) => ({ name: x.name, amount: Math.round(x.amount) }));
  const liabilities = items.filter((x) => x.category === "liability")
    .map((x) => ({ name: x.name, amount: Math.round(x.amount) }));

  const stocks = ((typeof state !== "undefined" && state.config && state.config.stocks)
    ? state.config.stocks : []).map((s) => {
    const q = (typeof state !== "undefined" && state.quotes && state.quotes.quotes)
      ? state.quotes.quotes[s.code] : null;
    return {
      name: s.name, code: s.code, shares: Number(s.shares_held || 0),
      price: (q && q.price != null ? q.price : null),
      yield: (q && q.yield != null ? Math.round(q.yield * 10000) / 10000 : null),
      annual_dividend: (q && q.per10 != null
        ? Math.round(Number(s.shares_held || 0) * q.per10 / 10) : null),
    };
  });

  const scenarios = [0, 0.04, 0.06, 0.08].map((rate) => {
    const res = sScenario(rate, nw, target, used.value);
    return {
      rate: rate,
      months: isFinite(res.months) ? Math.round(res.months) : null,
      years: isFinite(res.years) ? Math.round(res.years * 10) / 10 : null,
    };
  });

  return {
    as_of: new Date().toISOString().slice(0, 10),
    goal: {
      target: target,
      net_worth: Math.round(nw),
      gap: Math.round(Math.max(0, target - nw)),
      progress_pct: target > 0 ? Math.round(nw / target * 1000) / 10 : null,
    },
    monthly: {
      mode: S.monthlyAuto ? "auto" : "fixed",
      used: Math.round(used.value),
      historical_monthly: f.insufficient ? null : Math.round(f.perMonth),
      manual_default: sMonthly(),
      window_months: f.months,
      data_points: f.insufficient ? 0 : f.count,
    },
    forecast: {
      branch: used.value > 0 ? "contribution" : "balance_only",
      six_percent_months: isFinite(six.months) ? Math.round(six.months) : null,
      six_percent_years: isFinite(six.years) ? Math.round(six.years * 10) / 10 : null,
      over_20_years: sIsBad(six),
      plan_months: isFinite(plan.months) ? Math.round(plan.months) : null,
    },
    history: { months: months, weeks: weeks },
    balance: { assets: assets, liabilities: liabilities, net: Math.round(nw) },
    stocks: stocks,
    funds: (typeof F !== "undefined" && Array.isArray(F.funds) ? F.funds.map((f) => ({
      name: f.name, code: f.code, market: f.market, fund_type: f.fund_type,
      shares: Number(f.shares || 0), value: Math.round(Number(f.value || 0)),
      return_1y: (f.return_1y == null ? null : f.return_1y),
    })) : []),
    disciplines: S.plan.disciplines || [],
    scenarios: scenarios,
  };
}

async function generateAdvice() {
  if (AI.busy) return;
  if (!AI.status || !AI.status.configured) {
    aiSetBody("请先在侧边栏「设置 → AI 模型」中配置服务地址、模型和 API Key。", true);
    return;
  }
  if (!S.plan || !S.trend) {
    aiSetBody("数据还在加载，请稍候再试。", true);
    return;
  }
  const btn = document.getElementById("btn-advice-generate");
  AI.busy = true;
  if (btn) { btn.disabled = true; btn.textContent = "生成中…"; }
  aiSetBody("正在生成建议（约 10–30 秒）…");
  aiSetMeta("");
  try {
    const resp = await fetch("/api/advice", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ context: buildAdviceContext(), force: true }),
    });
    const data = await resp.json();
    if (!data.ok) {
      aiSetBody(data.error || "生成失败", true);
      return;
    }
    AI.hasAdvice = true;
    aiSetBody(data.advice);
    aiUpdateGenerateButton();
    aiSetMeta("生成于 " + (data.generated_at || "") + " · " + (data.model || ""));
  } catch (err) {
    aiSetBody("生成失败：" + err, true);
  } finally {
    AI.busy = false;
    if (btn) { btn.disabled = false; btn.textContent = AI.hasAdvice ? "重新生成" : "生成建议"; }
  }
}

async function aiLoadCached() {
  try {
    const resp = await fetch("/api/advice", { cache: "no-store" });
    const data = await resp.json();
    if (data.ok) {
      AI.hasAdvice = true;
      aiSetBody(data.advice);
      aiUpdateGenerateButton();
      aiSetMeta("生成于 " + (data.generated_at || "") + " · " + (data.model || "") + "（缓存）");
    }
  } catch (err) { /* 忽略，保留空状态 */ }
}

function bindAdviceEvents() {
  document.getElementById("btn-advice-generate").addEventListener("click", generateAdvice);
}

async function initAdvice() {
  bindAdviceEvents();
  await aiLoadStatus();
  await aiLoadCached();
  if (!(AI.status && AI.status.configured) && !AI.hasAdvice) {
    aiSetBody("在侧边栏「设置 → AI 模型」配置好后点「生成建议」；建议会结合目标、月均结余、历史净值、资产负债、股票实仓和纪律条款。", false);
  }
}

document.addEventListener("DOMContentLoaded", initAdvice);
