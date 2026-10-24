"use strict";

// ---------- 动态选股页面 ----------
const SC = { data: null, rules: null, refreshing: false, timer: null, started: false };

const scEsc = DSH.escape;
const scNum = DSH.numOrDash;
const scPct = DSH.pct2;
const scPe = DSH.pe;

function scTag(text, cls) {
  if (!text) return "";
  return `<span class="tag ${cls}">${scEsc(text)}</span>`;
}

function renderScreenerKpi() {
  const el = document.getElementById("screener-kpi");
  if (!el || !SC.data) return;
  const d = SC.data;
  const cards = [
    { icon: "&#128200;", label: "覆盖股票", value: d.universe ? scNum(d.universe, 0) : "—" },
    { icon: "&#128184;", label: "有分红记录", value: d.dividend_stocks ? scNum(d.dividend_stocks, 0) : "—" },
    { icon: "&#127919;", label: "二次筛选通过", value: (d.candidates || []).length },
    { icon: "&#9989;", label: "优中选优 10 只", value: (d.top_picks || []).length, highlight: true },
  ];
  el.innerHTML = cards.map((c) => `
    <div class="summary-item${c.highlight ? " highlight" : ""}">
      <div class="summary-icon">${c.icon}</div>
      <div class="summary-label">${c.label}</div>
      <div class="summary-value">${c.value}</div>
    </div>`).join("");
}

function renderScreenerScoring() {
  const el = document.getElementById("screener-scoring");
  if (!el) return;
  const s = (SC.data && SC.data.scoring) || null;
  if (!s) { el.innerHTML = '<div class="rule-item"><div class="rule-name">暂无评分数据</div></div>'; return; }
  el.innerHTML = (s.items || []).map((it) => `
    <div class="rule-item">
      <div class="rule-desc">${scEsc(it)}</div>
    </div>`).join("");
}

function renderScreenerRules() {
  const el = document.getElementById("screener-rules");
  if (!el || !SC.rules) return;
  const r = SC.rules;
  const hard = (r.hard_rules || []).map((x) => `
    <div class="rule-item">
      <div class="rule-name">${scEsc(x.name)}</div>
      <div class="rule-desc">${scEsc(x.rule)}</div>
    </div>`).join("");
  const weight = (r.weight_rules || []).map((w, i) => `
    <div class="rule-item">
      <div class="rule-name">${String.fromCharCode(9312 + i)} 权重调节</div>
      <div class="rule-desc">${scEsc(w)}</div>
    </div>`).join("");
  const struct = (r.target_structure || []).map((s) => `
    <div class="rule-item">
      <div class="rule-name">${scEsc(s.industry)} ${scEsc(s.weight)}</div>
      <div class="rule-desc">${scEsc(s.stocks)}</div>
    </div>`).join("");
  el.innerHTML = `
    <div class="rule-grid">${hard}${weight}</div>
    <div class="card-title" style="margin:16px 0 10px">目标结构</div>
    <div class="rule-grid">${struct}</div>`;
}

function readFilters() {
  const val = (id) => (document.getElementById(id) ? document.getElementById(id).value : "");
  const checked = (id) => {
    const el = document.getElementById(id);
    return el ? el.checked : false;
  };
  return {
    industry: val("screener-filter-industry"),
    factor: val("screener-filter-factor"),
    near: checked("screener-filter-near"),
    defensive: checked("screener-filter-defensive"),
    bank: checked("screener-filter-bank"),
    showAll: checked("screener-filter-all"),
  };
}

function filteredCandidates() {
  const all = SC.data.candidates || [];
  const f = readFilters();
  let list = all;
  if (f.industry) list = list.filter((c) => c.board === f.industry);
  if (f.factor) list = list.filter((c) => f.factor === "无" ? !c.factor : c.factor === f.factor);
  if (f.near) list = list.filter((c) => c.near_dividend);
  if (f.defensive) list = list.filter((c) => (c.tags || []).includes("防御底仓"));
  if (f.bank) list = list.filter((c) => (c.tags || []).includes("银行"));
  return list;
}

function renderScreenerCandidates() {
  const body = document.getElementById("screener-body");
  const count = document.getElementById("screener-count");
  if (!body || !SC.data) return;
  const f = readFilters();
  const hasFilter = f.industry || f.factor || f.near || f.defensive || f.bank;
  let list;
  if (f.showAll || hasFilter) {
    list = filteredCandidates().slice(0, 200);
  } else {
    list = SC.data.top_picks || (SC.data.candidates || []).slice(0, 10);
  }
  const total = filteredCandidates().length;
  const suffix = (f.showAll || hasFilter) ? "（筛选后 " + total + " 只）" : "（默认优中选优 10 只，可勾选“显示全部”）";
  count.textContent = "共 " + list.length + " 只 " + suffix;

  if (!list.length) {
    body.innerHTML = '<tr><td colspan="11" class="c-name muted">暂无符合条件的标的。</td></tr>';
    return;
  }
  body.innerHTML = list.map((c) => {
    const tags = (c.tags || []).map((t) => {
      if (t === "防御底仓") return scTag(t, "tag-defensive");
      if (t === "银行") return scTag(t, "tag-bank");
      if (t === "能源链" || t === "地产链" || t === "利率链") return scTag(t, "tag-factor");
      return scTag(t, "tag-none");
    }).join(" ");
    const warns = (c.warnings || []).map((w) => scTag(w, "tag-warn")).join(" ");
    const near = c.near_dividend ? scTag("临近分红", "tag-near") : "";
    const note = c.dividend_note || "—";
    return `<tr>
      <td>${scEsc(c.code)}</td>
      <td class="c-name">${scEsc(c.name)}</td>
      <td class="num">${scNum(c.price)}</td>
      <td class="num">${scPct(c.yield)}</td>
      <td class="num">${scPe(c.pe)}</td>
      <td class="num">${scNum(c.pb)}</td>
      <td class="num">${scNum(c.quality_score, 1)}</td>
      <td class="c-name">${scEsc(c.board)}</td>
      <td class="c-name">${tags} ${near} ${warns}</td>
      <td class="c-name">${scEsc(note)}</td>
      <td><button class="btn btn-outline btn-sm" type="button" data-add="${scEsc(c.code)}">加入实仓</button></td>
    </tr>`;
  }).join("");
}

function renderScreenerIndustry() {
  const el = document.getElementById("screener-industry");
  if (!el || !SC.data) return;
  const map = SC.data.industry_count || {};
  const total = (SC.data.candidates || []).length;
  const entries = Object.entries(map);
  if (!entries.length) { el.innerHTML = '<p class="muted">暂无数据。</p>'; return; }
  el.innerHTML = entries.map(([name, n]) => {
    const pct = total ? (n / total * 100).toFixed(0) : 0;
    const over = pct > 35;
    return `<div class="industry-chip" style="${over ? "border-color:var(--warn)" : ""}">
      <span>${scEsc(name)}</span><b>${n} 只 · ${pct}%${over ? "（超 35% 线）" : ""}</b>
    </div>`;
  }).join("");
}

function renderScreenerExcluded() {
  const card = document.getElementById("screener-excluded-card");
  const body = document.getElementById("screener-excluded");
  if (!card || !body || !SC.data) return;
  const list = SC.data.excluded || [];
  if (!list.length) { card.hidden = true; return; }
  card.hidden = false;
  body.innerHTML = list.map((c) => `<tr>
    <td>${scEsc(c.code)}</td>
    <td class="c-name">${scEsc(c.name)}</td>
    <td class="num">${scNum(c.price)}</td>
    <td class="num">${scPct(c.yield)}</td>
    <td class="c-name">${scEsc(c.board)}</td>
    <td class="c-name neg">${scEsc(c.exclude_reason)}</td>
  </tr>`).join("");
}

function renderScreener() {
  renderScreenerKpi();
  renderScreenerRules();
  renderScreenerScoring();
  renderScreenerCandidates();
  renderScreenerIndustry();
  renderScreenerExcluded();
}

function populateFilters() {
  const sel = document.getElementById("screener-filter-industry");
  if (!sel || !SC.data) return;
  const cur = sel.value;
  const industries = (SC.data.filters && SC.data.filters.industries) || [];
  sel.innerHTML = '<option value="">全部</option>' + industries.map((i) => `<option value="${scEsc(i)}">${scEsc(i)}</option>`).join("");
  sel.value = cur;

  const fsel = document.getElementById("screener-filter-factor");
  if (fsel) {
    const curF = fsel.value;
    const factors = (SC.data.filters && SC.data.filters.factors) || ["能源链", "地产链", "利率链"];
    fsel.innerHTML = '<option value="">全部</option>' +
      factors.map((f) => `<option value="${scEsc(f)}">${scEsc(f)}</option>`).join("") +
      '<option value="无">无</option>';
    fsel.value = curF;
  }
}

function setScreenerStatus(text, ok) {
  const el = document.getElementById("screener-status");
  if (!el) return;
  el.textContent = text;
  el.className = "save-status" + (ok === true ? " ok" : ok === false ? " err" : "");
}

function setRetryVisible(show) {
  const btn = document.getElementById("btn-screener-retry");
  if (btn) btn.hidden = !show;
}

function scheduleScreenerPoll(delayMs) {
  if (SC.timer) clearTimeout(SC.timer);
  SC.timer = setTimeout(() => {
    SC.timer = null;
    loadScreener(false);
  }, Math.max(1000, Number(delayMs) || 3000));
}

async function loadScreener(refresh) {
  if (SC.refreshing) return;
  SC.refreshing = true;
  const yieldV = document.getElementById("screener-yield") ? document.getElementById("screener-yield").value : "0.045";
  const priceV = document.getElementById("screener-price") ? document.getElementById("screener-price").value : "50";
  setScreenerStatus(refresh ? "正在抓取全市场数据（约 20–40 秒）…" : "正在加载…");
  try {
    const qs = "?yield=" + encodeURIComponent(yieldV) + "&price=" + encodeURIComponent(priceV) +
      (refresh ? "&refresh=1" : "");
    const resp = await fetch("/api/screener" + qs, { cache: "no-store" });
    const data = await resp.json();
    // 只有带完整结果的响应才替换页面数据；刷新中的占位响应保留旧表格。
    if (typeof data.universe === "number") SC.data = data;
    SC.rules = data.rules || SC.rules || null;

    if (data.refreshing) {
      setRetryVisible(false);
      setScreenerStatus(data.error
        ? "上次更新失败，正在自动重试…"
        : "首次抓取进行中（约 20–40 秒），稍后自动刷新…");
      renderScreenerRules();
      scheduleScreenerPoll(data.retry_in_ms || 2500);
      return;
    }

    // 有可用数据（含旧缓存）就先渲染，再提示错误。
    if (typeof data.universe === "number") {
      populateFilters();
      renderScreener();
    }

    if (data.error) {
      const secs = data.retry_in_ms ? Math.ceil(data.retry_in_ms / 1000) : 0;
      if (data.retry_exhausted) {
        setScreenerStatus("更新失败：" + data.error + "；已暂停自动重试，请点右侧「重试」", false);
      } else {
        setScreenerStatus("更新失败：" + data.error +
          (secs ? "；约 " + secs + " 秒后自动重试" : ""), false);
        if (secs) scheduleScreenerPoll(data.retry_in_ms);
      }
      setRetryVisible(true);
    } else {
      setRetryVisible(false);
      setScreenerStatus("更新于 " + (data.trade_date || ""), true);
    }
  } catch (err) {
    setScreenerStatus("加载失败：" + err, false);
    setRetryVisible(true);
  } finally {
    SC.refreshing = false;
  }
}

async function addToConfig(c) {
  const btn = document.querySelector('[data-add="' + c.code + '"]');
  if (btn) { btn.disabled = true; btn.textContent = "加入中…"; }
  try {
    const resp = await fetch("/api/stocks/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: c.name, code: c.code, weight: 0,
        price: c.price, ref_yield: c.yield, shares_held: 0,
      }),
    });
    const data = await resp.json();
    if (data.ok) {
      setScreenerStatus("已加入储蓄计划的股票实仓（" + c.name + "），请补充实仓股数后保存", true);
      if (window.reloadConfig) await window.reloadConfig();
      if (btn) { btn.textContent = "已加入"; btn.disabled = true; }
    } else if (data.exists) {
      setScreenerStatus("该股票已在实仓列表中", false);
      if (btn) { btn.disabled = false; btn.textContent = "加入实仓"; }
    } else {
      setScreenerStatus("加入失败：" + (data.error || "未知错误"), false);
      if (btn) { btn.disabled = false; btn.textContent = "加入实仓"; }
    }
  } catch (err) {
    setScreenerStatus("加入失败：" + err, false);
    if (btn) { btn.disabled = false; btn.textContent = "加入实仓"; }
  }
}

function bindScreenerEvents() {
  document.getElementById("btn-screener-refresh").addEventListener("click", () => loadScreener(true));
  const retryBtn = document.getElementById("btn-screener-retry");
  if (retryBtn) retryBtn.addEventListener("click", () => loadScreener(true));
  document.getElementById("screener-yield").addEventListener("change", () => loadScreener(false));
  document.getElementById("screener-price").addEventListener("change", () => loadScreener(false));
  document.addEventListener("click", (e) => {
    const add = e.target.closest("[data-add]");
    if (!add) return;
    const code = add.dataset.add;
    const all = SC.data ? (SC.data.top_picks || []).concat(SC.data.candidates || []) : [];
    const c = all.find((x) => x.code === code);
    if (c) addToConfig(c);
  });
  ["screener-filter-industry", "screener-filter-factor", "screener-filter-near",
   "screener-filter-defensive", "screener-filter-bank", "screener-filter-all"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", renderScreenerCandidates);
  });
}

async function initScreener() {
  bindScreenerEvents();
  try {
    const resp = await fetch("/api/screener/rules", { cache: "no-store" });
    SC.rules = await resp.json();
    renderScreenerRules();
  } catch (err) { /* 忽略，等待数据接口 */ }
  // 首屏不抓取全市场数据；切到「动态选股」页签时再加载一次
  window.addEventListener("tab:shown", (e) => {
    if (e.detail && e.detail.tab === "screener" && !SC.started) {
      SC.started = true;
      loadScreener(false);
    }
  });
}

document.addEventListener("DOMContentLoaded", initScreener);
