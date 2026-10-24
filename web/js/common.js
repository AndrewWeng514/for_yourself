"use strict";

// 公共工具：转义 / 数字格式化 / 设置文本。
// 三个页面脚本共用，避免各写一份（原先 app.js、savings.js、screener.js 各有一套）。
window.DSH = (function () {
  function escape(str) {
    return String(str == null ? "" : str).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function fmt(n, d) {
    d = (d == null) ? 2 : d;
    const v = Number(n);
    if (!isFinite(v)) return "0";
    return v.toLocaleString("zh-CN", {
      minimumFractionDigits: d, maximumFractionDigits: d,
    });
  }

  function money0(n) {
    const v = Number(n);
    if (!isFinite(v)) return "0";
    return v.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  }

  function numOrDash(n, d) {
    if (n == null || !isFinite(Number(n))) return "—";
    return fmt(n, d == null ? 2 : d);
  }

  function pct(n, d) {
    const v = Number(n);
    return isFinite(v) ? (v * 100).toFixed(d == null ? 2 : d) + "%" : "0%";
  }

  function pctOrDash(n, d) {
    if (n == null || !isFinite(Number(n))) return "—";
    return (Number(n) * 100).toFixed(d == null ? 2 : d) + "%";
  }

  function wan(n) {
    const v = Number(n);
    return isFinite(v) ? (v / 10000).toFixed(2) + "w" : "—";
  }

  function pe(n) {
    if (n == null || n === "") return "—";
    const v = Number(n);
    if (!isFinite(v)) return "—";
    if (v <= 0) return '<span class="neg">亏损</span>';
    return v.toFixed(1);
  }

  return {
    escape: escape,
    setText: setText,
    fmt: fmt,
    money: (n) => fmt(n, 2),
    money0: money0,
    numOrDash: numOrDash,
    pct: pct,
    pct1: (n) => pctOrDash(n, 1),
    pct2: (n) => pctOrDash(n, 2),
    pctOrDash: pctOrDash,
    wan: wan,
    pe: pe,
  };
})();
