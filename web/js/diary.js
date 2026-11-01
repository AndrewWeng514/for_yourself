/* 日记 + 速记：真实数据版 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const pad = (n) => String(n).padStart(2, "0");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));

  const state = {
    thinoLoaded: false,
    diaryLoaded: false,
    gran: "day",
    date: new Date(),
    calYear: new Date().getFullYear(),
    calMonth: new Date().getMonth(),
    entry: null,
    parts: null,
    complex: false,
    sourceMode: false,
    dirty: false,
    autosaveTimer: null,
    saving: false,
    editVersion: 0,
    composing: false,
    vditor: null,
    vditorPromise: null,
    vditorReady: false,
    suppressVditor: false,
    vditorAssetsPromise: null,
    calendar: null,
    entries: [],
    pendingDate: null,
    templateGran: null,
    templateRaw: "",
    templateContent: "",
    templateEdit: false,
    thinoMemos: [],
    summaryGran: "week",
    summaryData: null,
  };

  function isoDate(d) {
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function isoWeek(d) {
    const x = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    const day = x.getUTCDay() || 7;
    x.setUTCDate(x.getUTCDate() + 4 - day);
    const yearStart = new Date(Date.UTC(x.getUTCFullYear(), 0, 1));
    const week = Math.ceil(((x - yearStart) / 86400000 + 1) / 7);
    return x.getUTCFullYear() + "-W" + pad(week);
  }

  function weekStart(key) {
    const m = /^(\d{4})-W(\d{2})$/.exec(key || "");
    if (!m) return new Date();
    const jan4 = new Date(Date.UTC(Number(m[1]), 0, 4));
    const offset = (jan4.getUTCDay() + 6) % 7;
    return new Date(jan4.getTime() - offset * 86400000 + (Number(m[2]) - 1) * 7 * 86400000);
  }

  function weekdayName(d) {
    return ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][d.getDay()];
  }

  async function api(path, opts) {
    const resp = await fetch(path, Object.assign({ cache: "no-store" }, opts || {}));
    const data = await resp.json().catch(() => ({ ok: false, error: "响应不是 JSON" }));
    if (!resp.ok || data.ok === false) {
      const err = new Error(data.error || ("HTTP " + resp.status));
      err.status = resp.status;
      err.code = data.code;
      throw err;
    }
    return data;
  }

  function setStatus(id, text, kind) {
    const el = $(id);
    if (!el) return;
    el.textContent = text || "";
    el.className = "diary-toast" + (kind ? " " + kind : "");
  }

  // ---------- Markdown ----------

  function assetUrl(src) {
    src = String(src || "");
    if (src.startsWith("/diary-assets/")) return src;
    if (src.startsWith("assets/")) return "/diary-assets/" + src.slice("assets/".length);
    return src;
  }

  function mdAsset(src) {
    src = String(src || "");
    if (src.startsWith("/diary-assets/")) return "assets/" + src.slice("/diary-assets/".length);
    return src;
  }

  function inlineMd(s) {
    s = esc(s);
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (m, alt, src) =>
      '<img src="' + esc(assetUrl(src)) + '" alt="' + esc(alt) + '" loading="lazy">');    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, text, href) => {
      const safe = /^(https?:|mailto:|\/|#)/i.test(href) ? href : "#";
      return '<a href="' + esc(safe) + '" target="_blank" rel="noopener">' + text + "</a>";
    });
    s = s.replace(/\[\[([^\]]+)\]\]/g, (m, t) =>
      '<span class="wikilink" data-link="' + esc(t.split("|")[0]) + '">' + esc(t.split("|")[0]) + "</span>");
    s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
    s = s.replace(/~~(.+?)~~/g, "<del>$1</del>");
    return s;
  }

  function mdToHtml(text) {
    let src = String(text || "").replace(/^---\n[\s\S]*?\n---\n?/, "");
    const lines = src.split("\n");
    let html = "";
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      if (/^```/.test(line)) {
        const lang = line.replace(/^```/, "").trim();
        const code = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) { code.push(lines[i]); i++; }
        i++;
        html += '<pre><code' + (lang ? ' class="lang-' + esc(lang) + '"' : "") + ">" +
          esc(code.join("\n")) + "</code></pre>";
        continue;
      }
      const h = /^(#{1,6})\s+(.*)$/.exec(line);
      if (h) {
        html += "<h" + h[1].length + ">" + inlineMd(h[2]) + "</h" + h[1].length + ">";
        i++; continue;
      }
      if (/^\s*-----?\s*$/.test(line)) { html += "<hr>"; i++; continue; }
      if (/^>\s?/.test(line)) {
        const parts = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) { parts.push(inlineMd(lines[i].replace(/^>\s?/, ""))); i++; }
        html += "<blockquote>" + parts.join("<br>") + "</blockquote>";
        continue;
      }
      if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
        const ordered = /^\s*\d+\.\s+/.test(line);
        const items = [];
        while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
          let t = lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, "");
          let cls = "";
          if (/^\[[ xX]\]\s+/.test(t)) {
            cls = "task";
            t = t.replace(/^\[[ xX]\]\s+/, (m) => m.includes("x") || m.includes("X") ? "☑ " : "☐ ");
          }
          items.push("<li" + (cls ? ' class="' + cls + '"' : "") + ">" + inlineMd(t) + "</li>");
          i++;
        }
        html += "<" + (ordered ? "ol" : "ul") + ">" + items.join("") + "</" + (ordered ? "ol" : "ul") + ">";
        continue;
      }
      if (line.includes("|") && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1])) {
        const head = line.split("|").map((x) => x.trim()).filter((x) => x !== "");
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].includes("|")) {
          rows.push(lines[i].split("|").map((x) => x.trim()).filter((x) => x !== ""));
          i++;
        }
        html += "<table><thead><tr>" + head.map((x) => "<th>" + inlineMd(x) + "</th>").join("") +
          "</tr></thead><tbody>" + rows.map((r) => "<tr>" + r.map((x) => "<td>" + inlineMd(x) + "</td>").join("") + "</tr>").join("") +
          "</tbody></table>";
        continue;
      }
      const para = [];
      while (i < lines.length && lines[i].trim() &&
        !/^```/.test(lines[i]) && !/^#{1,6}\s+/.test(lines[i]) &&
        !/^>\s?/.test(lines[i]) && !/^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        para.push(inlineMd(lines[i]));
        i++;
      }
      html += "<p>" + para.join("<br>") + "</p>";
    }
    return html || '<p class="muted">（空）</p>';
  }

  function inlineHtmlToMd(node) {
    let out = "";
    node.childNodes.forEach((n) => {
      if (n.nodeType === 3) { out += n.nodeValue.replace(/\u00a0/g, " "); return; }
      if (n.nodeType !== 1) return;
      const tag = n.tagName.toLowerCase();
      const inner = inlineHtmlToMd(n);
      if (tag === "strong" || tag === "b") out += "**" + inner + "**";
      else if (tag === "em" || tag === "i") out += "*" + inner + "*";
      else if (tag === "del" || tag === "s" || tag === "strike") out += "~~" + inner + "~~";
      else if (tag === "code") out += "`" + inner + "`";
      else if (tag === "a") out += "[" + inner + "](" + (n.getAttribute("href") || "") + ")";
      else if (tag === "span" && n.classList.contains("wikilink")) out += "[[" + (n.getAttribute("data-link") || inner) + "]]";
      else if (tag === "img") out += "![" + (n.getAttribute("alt") || "") + "](" + mdAsset(n.getAttribute("src") || "") + ")";
      else if (tag === "br") out += "\n";
      else out += inner;
    });
    return out;
  }

  function listToMd(list, ordered, indent) {
    let n = 0;
    let out = "";
    Array.from(list.children).forEach((li) => {
      if (li.tagName.toLowerCase() !== "li") return;
      n++;
      const clone = li.cloneNode(true);
      const nested = [];
      clone.querySelectorAll("ul,ol").forEach((x) => { nested.push(x); x.remove(); });
      out += indent + (ordered ? n + ". " : "- ") + inlineHtmlToMd(clone).trim() + "\n";
      nested.forEach((x) => { out += listToMd(x, x.tagName.toLowerCase() === "ol", indent + "  "); });
    });
    return out;
  }

  function tableToMd(table) {
    const rows = Array.from(table.querySelectorAll("tr"));
    if (!rows.length) return "";
    const cells = (tr) => Array.from(tr.children).map((c) => inlineHtmlToMd(c).trim().replace(/\|/g, "\\|"));
    const head = cells(rows[0]);
    let out = "| " + head.join(" | ") + " |\n| " + head.map(() => "---").join(" | ") + " |\n";
    rows.slice(1).forEach((tr) => { out += "| " + cells(tr).join(" | ") + " |\n"; });
    return out;
  }

  function blockHtmlToMd(node) {
    let out = "";
    node.childNodes.forEach((n) => {
      if (n.nodeType === 3) { const t = n.nodeValue.replace(/\u00a0/g, " "); if (t.trim()) out += t; return; }
      if (n.nodeType !== 1) return;
      const tag = n.tagName.toLowerCase();
      if (/^h[1-6]$/.test(tag)) {
        out += "#".repeat(Number(tag[1])) + " " + inlineHtmlToMd(n).trim() + "\n\n";
      } else if (tag === "p" || tag === "div") {
        const t = inlineHtmlToMd(n).trim();
        if (t) out += t + "\n\n";
      } else if (tag === "ul" || tag === "ol") {
        out += listToMd(n, tag === "ol", "") + "\n";
      } else if (tag === "blockquote") {
        const t = inlineHtmlToMd(n).trim();
        if (t) out += t.split("\n").map((l) => "> " + l).join("\n") + "\n\n";
      } else if (tag === "pre") {
        const lang = n.getAttribute("data-lang") || "";
        out += "```" + lang + "\n" + n.textContent.replace(/\n$/, "") + "\n```\n\n";
      } else if (tag === "hr") {
        out += "---\n\n";
      } else if (tag === "table") {
        out += tableToMd(n) + "\n";
      } else if (tag === "img") {
        out += "![" + (n.getAttribute("alt") || "") + "](" + mdAsset(n.getAttribute("src") || "") + ")\n\n";
      } else {
        const t = inlineHtmlToMd(n).trim();
        if (t) out += t + "\n\n";
      }
    });
    return out.replace(/\n{3,}/g, "\n\n").trim();
  }

  // ---------- 日记结构 ----------

  function splitNote(content) {
    const raw = String(content || "");
    let front = "";
    let rest = raw;
    const fm = raw.match(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/);
    if (fm) { front = fm[0]; rest = raw.slice(fm[0].length); }
    rest = rest.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const lines = rest.split("\n");
    let idx = -1;
    lines.forEach((l, i) => { if (/^\s*#{0,6}\s*Memos\s*$/.test(l)) idx = i; });
    if (idx < 0) return { front: front, body: rest, memos: "" };
    let end = lines.length;
    for (let i = idx + 1; i < lines.length; i++) {
      if (/^#{1,6}\s+\S/.test(lines[i])) { end = i; break; }
    }
    const after = end < lines.length ? lines.slice(end).join("\n") : "";
    return {
      front: front,
      body: lines.slice(0, idx).join("\n") + (after ? "\n\n" + after : ""),
      memos: lines.slice(idx, end).join("\n"),
    };
  }

  function withoutFences(text) {
    const kept = [];
    let open = false;
    String(text || "").split("\n").forEach((line) => {
      if (/^\s*(```|~~~)/.test(line)) { open = !open; return; }
      if (!open) kept.push(line);
    });
    return kept.join("\n");
  }

  function isComplex(parts) {
    const body = withoutFences(parts && parts.body);
    return /<(iframe|script|object|embed|form|video|audio|style)\b/i.test(body);
  }

  function keyFor(gran, d) {
    if (gran === "day") return isoDate(d);
    if (gran === "week") return isoWeek(d);
    if (gran === "month") return d.getFullYear() + "-" + pad(d.getMonth() + 1);
    if (gran === "quarter") return d.getFullYear() + "-Q" + (Math.floor(d.getMonth() / 3) + 1);
    return String(d.getFullYear());
  }

  function titleFor(gran, key) {
    if (gran === "day") {
      const p = key.split("-").map(Number);
      return key + " " + weekdayName(new Date(p[0], p[1] - 1, p[2]));
    }
    return key;
  }

  function metaFor(gran, key) {
    if (gran === "day") {
      const p = key.split("-").map(Number);
      const d = new Date(p[0], p[1] - 1, p[2]);
      return "所属 " + isoWeek(d) + " · " + p[0] + "-" + pad(p[1]) + " · " + p[0] + "年";
    }
    if (gran === "week") return "所属 " + key.slice(0, 4) + "-" + key.slice(6, 8) + " · " + key.slice(0, 4) + "年";
    return key.slice(0, 4) + " 年";
  }

  // ---------- 日记编辑器 ----------

  function setGran(gran) {
    state.gran = gran;
    document.querySelectorAll("#diary-gran .seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.gran === gran);
    });
    loadEntry();
  }

  function renderMemosBlock(memos, raw) {
    const box = $("diary-memos");
    if ((!memos || !memos.length) && (!raw || !raw.trim())) { box.hidden = true; box.innerHTML = ""; return; }
    box.hidden = false;
    if (!memos || !memos.length) {
      box.innerHTML = '<div class="diary-memos-title">Memos（旧格式，只读）</div>' +
        '<pre class="memo-raw">' + esc(String(raw).replace(/^\s*#{0,6}\s*Memos\s*\n?/, "")) + "</pre>";
      return;
    }
    box.innerHTML = '<div class="diary-memos-title">Memos · ' + memos.length + ' 条（只读，去速记新增）</div>' +
      memos.map((m) =>
        '<div class="memo-static"><div class="memo-static-time">' + esc(m.time) + "</div>" +
        '<div class="memo-static-text">' + inlineMd(m.text) +
        (m.tags.length ? '<div class="memo-static-tags">' + m.tags.map((t) => '<span class="tag-chip">' + esc(t) + "</span>").join("") + "</div>" : "") +
        "</div></div>").join("");
  }

  const VDITOR_BASE = "vendor/vditor";

  function loadVditorAssets() {
    if (window.Vditor) return Promise.resolve();
    if (state.vditorAssetsPromise) return state.vditorAssetsPromise;
    state.vditorAssetsPromise = new Promise((resolve, reject) => {
      const fail = (message) => {
        state.vditorAssetsPromise = null;
        reject(new Error(message));
      };
      let cssDone = !!document.getElementById("vditor-lazy-css");
      let jsDone = false;
      const maybeResolve = () => {
        if (cssDone && jsDone && window.Vditor) resolve();
        else if (cssDone && jsDone && !window.Vditor) fail("Vditor 未加载");
      };

      if (!cssDone) {
        const link = document.createElement("link");
        link.id = "vditor-lazy-css";
        link.rel = "stylesheet";
        link.href = VDITOR_BASE + "/dist/index.css";
        link.onload = () => {
          cssDone = true;
          maybeResolve();
        };
        link.onerror = () => fail("Vditor CSS 加载失败");
        document.head.appendChild(link);
      }

      const script = document.createElement("script");
      script.src = VDITOR_BASE + "/dist/index.min.js";
      script.async = true;
      script.onload = () => {
        jsDone = true;
        maybeResolve();
      };
      script.onerror = () => fail("Vditor JS 加载失败");
      document.head.appendChild(script);
    });
    return state.vditorAssetsPromise;
  }

  function ensureVditor() {
    if (state.vditor) return Promise.resolve(state.vditor);
    if (state.vditorPromise) return state.vditorPromise;
    state.vditorPromise = loadVditorAssets().then(() => new Promise((resolve, reject) => {
      if (!window.Vditor) {
        reject(new Error("Vditor 未加载"));
        return;
      }
      const v = new Vditor("live-doc", {
        mode: "ir",
        cdn: "/vendor/vditor",
        lang: "zh_CN",
        preview: { hljs: { style: "github" } },
        cache: { enable: false },
        height: 620,
        toolbarConfig: { pin: true },
        toolbar: [
          "headings", "bold", "italic", "strike", "link",
          "|",
          "list", "ordered-list", "check", "|",
          "quote", "line", "code", "inline-code", "table", "|",
          "undo", "redo", "|", "fullscreen", "outline",
        ],
        input: () => onVditorInput(),
        after: () => {
          state.vditor = v;
          resolve(v);
        },
      });
    })).catch((err) => {
      state.vditorPromise = null;
      throw err;
    });
    return state.vditorPromise;
  }

  function onVditorInput() {
    if (state.suppressVditor || state.sourceMode || state.complex || !state.vditorReady) return;
    state.editVersion++;
    state.dirty = true;
    scheduleSave();
  }

  function scheduleSave(delay) {
    if (state.autosaveTimer) clearTimeout(state.autosaveTimer);
    state.autosaveTimer = setTimeout(() => {
      state.autosaveTimer = null;
      saveEntry(true);
    }, delay || 800);
    setStatus("editor-status", "编辑中，自动保存…", "warn");
  }

  function setVditorValue(value) {
    state.vditorReady = false;
    return ensureVditor().then((v) => {
      state.suppressVditor = true;
      v.setValue(value || "", true);
      const actual = String(v.getValue() || "");
      if (String(value || "").trim() && !actual.trim()) {
        state.vditorReady = false;
        state.suppressVditor = false;
        setStatus("editor-status", "编辑器没有载入原文，已阻止保存", "err");
        return false;
      }
      state.vditorReady = true;
      state.suppressVditor = false;
      return true;
    }).catch((err) => {
      state.vditorReady = false;
      setStatus("editor-status", "编辑器加载失败：" + err.message, "err");
      return false;
    });
  }

  function renderDoc() {
    const e = state.entry;
    if (!e) return;
    const key = e.key;
    $("doc-title").textContent = titleFor(state.gran, key);
    $("doc-meta").textContent = metaFor(state.gran, key);
    $("diary-path").textContent = "~/文档/portal-diary/" + e.path;
    $("doc-mode-badge").textContent = state.sourceMode ? "源码" : "Markdown";
    $("diary-notice").hidden = !state.complex;
    if (state.complex) {
      $("diary-notice").textContent = "这篇含原始 HTML 嵌入，已用源码模式保护；其余内容仍按 Markdown 保存。";
    }
    $("live-doc").hidden = state.sourceMode;
    $("diary-source").hidden = !state.sourceMode;
    $("doc-toolbar").hidden = !state.sourceMode;
    $("btn-diary-source").hidden = state.complex;
    $("diary-memos").hidden = state.sourceMode || (!e.memos.length && !state.parts.memos.trim());
    if (state.sourceMode) {
      $("diary-source").value = e.content;
      return Promise.resolve(true);
    }
    renderMemosBlock(e.memos, state.parts.memos);
    return setVditorValue(state.parts.body.trim());
  }

  async function loadEntry() {
    if (state.autosaveTimer) { clearTimeout(state.autosaveTimer); state.autosaveTimer = null; }
    if (state.dirty && state.entry) await saveEntry(true);
    const key = keyFor(state.gran, state.date);
    setStatus("editor-status", "读取中…");
    try {
      const data = await api("/api/diary/entry?gran=" + encodeURIComponent(state.gran) + "&key=" + encodeURIComponent(key));
      state.vditorReady = false;
      state.entry = data;
      state.parts = splitNote(data.content);
      state.complex = isComplex(state.parts);
      state.sourceMode = state.complex;
      state.editVersion = 0;
      state.dirty = false;
      renderDoc();
      setStatus("editor-status", data.exists ? "自动保存已开启" : "新文件，输入即自动创建");
    } catch (err) {
      setStatus("editor-status", "读取失败：" + err.message, "err");
    }
  }

  function noteIsProtected() {
    return state.complex || state.gran === "week" || state.gran === "month"
      || state.gran === "quarter" || state.gran === "year";
  }

  async function saveEntry(auto) {
    if (!state.entry) return;
    if (state.saving) {
      if (auto) scheduleSave(300);
      return;
    }
    if (auto && state.editVersion === 0) return;
    const key = state.entry.key;
    const version = state.editVersion;
    let content;
    let original = String(state.entry.content || "");
    let exists = !!state.entry.exists;
    if (state.sourceMode) {
      content = $("diary-source").value;
    } else if (!state.vditor || !state.vditorReady) {
      setStatus("editor-status", exists && original.trim()
        ? "编辑器尚未就绪，已阻止保存，避免覆盖原笔记"
        : "编辑器尚未就绪，请稍后再试", "err");
      return;
    } else {
      const body = state.vditor.getValue();
      let latest = state.entry;
      try {
        latest = await api("/api/diary/entry?gran=" + encodeURIComponent(state.gran) + "&key=" + encodeURIComponent(key));
      } catch (err) { /* 用当前状态 */ }
      const lp = splitNote(latest.content || "");
      const front = lp.front || (state.parts && state.parts.front) || "";
      const memos = lp.memos || "";
      content = front + (body || "") + (memos ? "\n\n" + memos : "") + "\n";
      if (latest && latest.sha256) state.entry.sha256 = latest.sha256;
      if (latest && latest.exists) {
        exists = true;
        original = String(latest.content || "");
      }
    }
    if (noteIsProtected() && exists && original.trim() && !String(content || "").trim()) {
      setStatus("editor-status", "内容为空，已阻止覆盖原笔记", "err");
      return;
    }
    const originalBody = (splitNote(original).body || "").trim();
    const nextBody = (splitNote(content).body || "").trim();
    if (noteIsProtected() && exists && originalBody && !nextBody) {
      setStatus("editor-status", "正文为空，已阻止覆盖原笔记", "err");
      return;
    }
    state.saving = true;
    setStatus("editor-status", auto ? "自动保存中…" : "保存中…");
    try {
      const data = await api("/api/diary/entry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          gran: state.gran, key: key, content: content,
          base_sha256: state.entry.sha256,
        }),
      });
      state.entry = data;
      state.parts = splitNote(data.content);
      state.complex = isComplex(state.parts);
      if (version === state.editVersion) {
        state.dirty = false;
        const t = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
        setStatus("editor-status", auto ? "已自动保存 " + t : "已保存", "ok");
      } else {
        state.dirty = true;
        setStatus("editor-status", "编辑中，自动保存…", "warn");
        scheduleSave(300);
      }
      refreshCalendar();
    } catch (err) {
      if (err.status === 409) {
        setStatus("editor-status", "文件已被其他页面修改，请刷新", "err");
      } else {
        setStatus("editor-status", (auto ? "自动保存失败：" : "保存失败：") + err.message, "err");
      }
    } finally {
      state.saving = false;
    }
  }

  function applyCommand(cmd) {
    if (cmd === "image") { $("diary-image-file").click(); return; }
    if (state.sourceMode) {
      const ta = $("diary-source");
      const snippets = {
        h1: "# ", h2: "## ", h3: "### ", bold: "****", italic: "**",
        underline: "", strike: "~~~~", code: "``", ul: "- ", ol: "1. ",
        task: "- [ ] ", quote: "> ", link: "[](https://)", image: "",
        table: "| 列1 | 列2 |\n| --- | --- |\n|  |  |\n", hr: "\n---\n",
      };
      const s = snippets[cmd] || "";
      const start = ta.selectionStart, end = ta.selectionEnd;
      ta.setRangeText(s, start, end, "end");
      ta.dispatchEvent(new Event("input"));
      return;
    }
    if (cmd === "image") { $("diary-image-file").click(); return; }
    const live = $("live-doc");
    live.focus();
    try {
      if (cmd === "undo") document.execCommand("undo");
      else if (cmd === "redo") document.execCommand("redo");
      else if (cmd === "h1") document.execCommand("formatBlock", false, "h1");
      else if (cmd === "h2") document.execCommand("formatBlock", false, "h2");
      else if (cmd === "h3") document.execCommand("formatBlock", false, "h3");
      else if (cmd === "bold") document.execCommand("bold");
      else if (cmd === "italic") document.execCommand("italic");
      else if (cmd === "underline") document.execCommand("underline");
      else if (cmd === "strike") document.execCommand("strikeThrough");
      else if (cmd === "code") document.execCommand("insertHTML", false, "<code>" + esc(window.getSelection().toString() || "code") + "</code>");
      else if (cmd === "ul") document.execCommand("insertUnorderedList");
      else if (cmd === "ol") document.execCommand("insertOrderedList");
      else if (cmd === "task") document.execCommand("insertHTML", false, "<div>☐ </div>");
      else if (cmd === "quote") document.execCommand("formatBlock", false, "blockquote");
      else if (cmd === "link") {
        const url = prompt("链接地址");
        if (url) document.execCommand("createLink", false, url);
      } else if (cmd === "table") {
        document.execCommand("insertHTML", false, "<table><tr><th>列 1</th><th>列 2</th></tr><tr><td> </td><td> </td></tr></table>");
      } else if (cmd === "hr") {
        document.execCommand("insertHTML", false, "<hr>");
      } else if (cmd === "clear") {
        document.execCommand("removeFormat");
      }
      state.editVersion++;
      state.dirty = true;
      scheduleSave();
    } catch (err) {
      setStatus("editor-status", "浏览器不支持该格式命令", "err");
    }
  }

  // ---------- 日历 ----------

  async function refreshCalendar() {
    try {
      const data = await api("/api/diary/calendar?year=" + state.calYear + "&month=" + (state.calMonth + 1));
      state.calendar = data;
      renderCalendar(data);
      renderFoot(data);
    } catch (err) {
      setStatus("diary-status", "日历加载失败：" + err.message, "err");
    }
  }

  function weekHas(data, week) {
    const w = data.weeks && data.weeks[week];
    return !!(w && (w.days || w.has_week));
  }

  function renderCalendar(data) {
    const y = state.calYear, m = state.calMonth;
    const first = new Date(y, m, 1);
    const offset = (first.getDay() + 6) % 7;
    const days = new Date(y, m + 1, 0).getDate();
    const start = new Date(y, m, 1 - offset);
    const rows = Math.ceil((offset + days) / 7);
    const selected = isoDate(state.date);
    let html = "";
    for (let row = 0; row < rows; row++) {
      const monday = new Date(start.getFullYear(), start.getMonth(), start.getDate() + row * 7);
      const wk = isoWeek(monday);
      const activeWeek = wk === isoWeek(state.date);
      html += '<div class="week-no' + (activeWeek ? " active" : "") + (weekHas(data, wk) ? " has-dot" : "") +
        '" data-week="' + wk + '" title="打开 ' + wk + ' 周记">' + wk.replace(/^\d{4}-W/, "") + "</div>";
      for (let col = 0; col < 7; col++) {
        const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + row * 7 + col);
        const key = isoDate(d);
        const inMonth = d.getMonth() === m;
        const info = data.days[key];
        const cls = "calendar-cell" + (inMonth ? "" : " other") +
          (key === selected ? " active" : "") + (info ? " has-dot" : "");
        html += '<div class="' + cls + '" data-date="' + key + '">' + d.getDate() + "</div>";
      }
    }
    $("cal-grid").innerHTML = html;
    $("cal-grid").querySelectorAll("[data-date]").forEach((el) => {
      el.addEventListener("click", () => {
        const p = el.dataset.date.split("-").map(Number);
        state.date = new Date(p[0], p[1] - 1, p[2]);
        state.calYear = p[0]; state.calMonth = p[1] - 1;
        state.gran = "day";
        document.querySelectorAll("#diary-gran .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.gran === "day"));
        loadEntry(); refreshCalendar();
      });
    });
    $("cal-grid").querySelectorAll("[data-week]").forEach((el) => {
      el.addEventListener("click", () => {
        const d = weekStart(el.dataset.week);
        state.date = d; state.calYear = d.getFullYear(); state.calMonth = d.getMonth();
        state.gran = "week";
        document.querySelectorAll("#diary-gran .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.gran === "week"));
        loadEntry(); refreshCalendar();
      });
    });
  }

  function renderFoot(data) {
    const total = data.total_days || 0;
    $("cal-foot").innerHTML = "<span>今天：" + isoDate(new Date()) + "</span><span>有记录 " + total + " 天</span>";
  }

  function renderRecent(items) {
    const days = items.filter((x) => x.gran === "day").sort((a, b) => b.key.localeCompare(a.key)).slice(0, 5);
    $("diary-recent").innerHTML = days.length ? days.map((x) =>
      '<div class="recent-item' + (x.key === isoDate(state.date) ? " active" : "") + '" data-key="' + x.key + '">' +
      "<span>" + esc(x.key.slice(5)) + "</span><span class=\"muted\">" + x.memos + " 条 memo</span></div>").join("") :
      '<div class="muted" style="font-size:12px;padding:6px">还没有记录</div>';
    $("diary-recent").querySelectorAll("[data-key]").forEach((el) => {
      el.addEventListener("click", () => {
        const p = el.dataset.key.split("-").map(Number);
        state.date = new Date(p[0], p[1] - 1, p[2]);
        state.calYear = p[0]; state.calMonth = p[1] - 1;
        state.gran = "day";
        document.querySelectorAll("#diary-gran .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.gran === "day"));
        loadEntry(); refreshCalendar();
      });
    });
  }

  function renderTodayMemos(memos) {
    $("diary-today-count").textContent = memos.length + " 条";
    $("diary-today-memos").innerHTML = memos.length ? memos.map((m) =>
      '<div class="today-memo-item"><span class="today-memo-time">' + esc(m.time) +
      '</span><span class="today-memo-text">' + inlineMd(m.text) + "</span></div>").join("") :
      '<div class="muted" style="font-size:12px">今天还没有 memo</div>';
  }

  async function loadDiary() {
    if (!state.diaryLoaded) {
      state.diaryLoaded = true;
      state.date = new Date();
      state.calYear = state.date.getFullYear();
      state.calMonth = state.date.getMonth();
      if (state.pendingDate) {
        const p = state.pendingDate.split("-").map(Number);
        state.date = new Date(p[0], p[1] - 1, p[2]);
        state.calYear = p[0];
        state.calMonth = p[1] - 1;
        state.pendingDate = null;
      }
      populateSelects();
      $("doc-title").textContent = "读取中…";
      loadEntry();
      refreshCalendar();
      refreshRecent();
      refreshTodayMemos();
    }
  }

  async function refreshRecent() {
    try {
      const data = await api("/api/diary/entries");
      state.entries = data.items || [];
      renderRecent(state.entries);
    } catch (err) { /* ignore */ }
  }

  async function refreshTodayMemos() {
    try {
      const data = await api("/api/diary/memos?date=" + isoDate(new Date()));
      renderTodayMemos(data.memos || []);
    } catch (err) { /* ignore */ }
  }

  function populateSelects() {
    const ys = $("cal-year"), ms = $("cal-month");
    if (!ys.options.length) {
      for (let y = 2023; y <= 2026; y++) ys.add(new Option(y + " 年", String(y)));
    }
    if (!ms.options.length) {
      for (let m = 1; m <= 12; m++) ms.add(new Option(m + " 月", String(m)));
    }
    ys.value = String(state.calYear);
    ms.value = String(state.calMonth + 1);
  }

  function shiftPeriod(delta) {
    const d = new Date(state.date);
    if (state.gran === "day") d.setDate(d.getDate() + delta);
    else if (state.gran === "week") d.setDate(d.getDate() + 7 * delta);
    else if (state.gran === "month") d.setMonth(d.getMonth() + delta);
    else if (state.gran === "quarter") d.setMonth(d.getMonth() + 3 * delta);
    else d.setFullYear(d.getFullYear() + delta);
    state.date = d;
    state.calYear = d.getFullYear();
    state.calMonth = d.getMonth();
    populateSelects();
    loadEntry(); refreshCalendar();
  }

  // ---------- 速记 ----------

  function heatLevel(n) {
    if (!n) return "";
    if (n >= 4) return "l4";
    if (n >= 3) return "l3";
    if (n >= 2) return "l2";
    return "l1";
  }

  function renderHeatmap(data) {
    const year = Number(data.year) || new Date().getFullYear();
    const map = data.days || {};
    const start = new Date(year, 0, 1);
    const end = new Date(year, 11, 31);
    const first = new Date(start);
    const offset = (first.getDay() + 6) % 7;
    const total = Math.ceil((offset + (end - start) / 86400000 + 1) / 7) * 7;
    let html = "";
    for (let i = 0; i < total; i++) {
      const d = new Date(year, 0, 1 - offset + i);
      const key = isoDate(d);
      const n = map[key] || 0;
      html += '<span class="' + heatLevel(n) + '" title="' + key + " · " + n + ' 条"></span>';
    }
    $("thino-heatmap").innerHTML = html;
    $("thino-year-label").textContent = year + " 记录热力";
    const count = Object.values(map).reduce((a, b) => a + b, 0);
    $("thino-heatmap-foot").innerHTML = "<span>" + Object.keys(map).length + " 天</span><span>" + count + " 条 memo</span>";
  }

  function renderThinoMemos(memos) {
    const list = $("thino-list");
    const head = $("thino-list-head");
    state.thinoMemos = memos;
    if (head) head.textContent = memos.length ? "历史 Memos · " + memos.length + " 条" : "历史 Memos";
    if (!memos.length) {
      list.innerHTML = '<div class="thino-memo"><div class="thino-memo-text muted">还没有记录，写一条吧。</div></div>';
      return;
    }
    const groups = {};
    memos.forEach((m) => {
      const d = m.date || isoDate(new Date());
      (groups[d] = groups[d] || []).push(m);
    });
    const dates = Object.keys(groups).sort().reverse();
    list.innerHTML = dates.map((date) => {
      const d = new Date(date + "T00:00:00");
      return '<div class="thino-date-head" data-date="' + date + '"><span>' + date + " " + weekdayName(d) +
        '</span><span class="muted">' + groups[date].length + ' 条</span></div>' +
        groups[date].map((m) => {
          const time = m.time ? esc(m.time) : "旧格式";
          return '<div class="thino-memo" data-date="' + date + '" data-index="' + Number(m.index || 0) + '">' +
            '<div class="thino-memo-head"><span class="thino-time">' + time +
            '</span><div class="thino-memo-tools"><button type="button" class="thino-more" data-menu title="更多">&#8943;</button>' +
            '<div class="memo-menu" hidden><button type="button" data-act="open">打开当天</button>' +
            '<button type="button" data-act="edit">编辑</button>' +
            '<button type="button" data-act="delete">删除</button></div></div></div>' +
            '<div class="thino-memo-text">' + inlineMd(m.text) + "</div>" +
            (m.tags && m.tags.length ? '<div class="thino-memo-tags">' + m.tags.map((t) => '<span class="tag-chip">' + esc(t) + "</span>").join("") + "</div>" : "") +
            "</div>";
        }).join("");
    }).join("");
    list.querySelectorAll(".thino-date-head").forEach((el) => {
      el.addEventListener("click", () => openDiaryDate(el.dataset.date));
    });
    list.querySelectorAll("[data-menu]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const menu = btn.parentElement.querySelector(".memo-menu");
        const wasHidden = menu.hidden;
        document.querySelectorAll(".memo-menu").forEach((m) => { m.hidden = true; });
        menu.hidden = !wasHidden;
      });
    });
    list.querySelectorAll(".memo-menu [data-act]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const card = btn.closest(".thino-memo");
        const date = card.dataset.date;
        const index = Number(card.dataset.index);
        const act = btn.dataset.act;
        btn.closest(".memo-menu").hidden = true;
        if (act === "open") openDiaryDate(date);
        else if (act === "edit") editMemo(date, index);
        else if (act === "delete") deleteMemo(date, index);
      });
    });
    filterThino();
  }

  async function editMemo(date, index) {
    const memo = (state.thinoMemos || []).find((m) =>
      m.date === date && Number(m.index) === Number(index));
    if (!memo) return;
    const text = prompt("编辑 memo", memo.text);
    if (text === null) return;
    const value = text.trim();
    if (!value) { setStatus("thino-status", "内容不能为空", "err"); return; }
    try {
      await api("/api/diary/memos/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: date, index: index, text: value }),
      });
      setStatus("thino-status", "已更新", "ok");
      await loadThino();
      refreshTodayMemos();
      if (state.entry && state.entry.key === date && state.gran === "day") loadEntry();
    } catch (err) {
      setStatus("thino-status", "更新失败：" + err.message, "err");
    }
  }

  async function deleteMemo(date, index) {
    if (!confirm("删除这条 memo？")) return;
    try {
      await api("/api/diary/memos/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: date, index: index }),
      });
      setStatus("thino-status", "已删除", "ok");
      await loadThino();
      refreshTodayMemos();
      if (state.entry && state.entry.key === date && state.gran === "day") loadEntry();
    } catch (err) {
      setStatus("thino-status", "删除失败：" + err.message, "err");
    }
  }

  function filterThino() {
    const q = ($("thino-search").value || "").trim().toLowerCase();
    const list = $("thino-list");
    if (!list) return;
    list.querySelectorAll(".thino-memo").forEach((el) => {
      el.style.display = (!q || el.textContent.toLowerCase().includes(q)) ? "" : "none";
    });
    list.querySelectorAll(".thino-date-head").forEach((head) => {
      let node = head.nextElementSibling;
      let visible = false;
      while (node && !node.classList.contains("thino-date-head")) {
        if (node.classList.contains("thino-memo") && node.style.display !== "none") visible = true;
        node = node.nextElementSibling;
      }
      head.style.display = visible ? "" : "none";
    });
  }

  async function loadThino() {
    try {
      const [memos, heat, tags] = await Promise.all([
        api("/api/diary/memos?all=1&limit=500"),
        api("/api/diary/heatmap?year=" + new Date().getFullYear()),
        api("/api/diary/tags?year=" + new Date().getFullYear()),
      ]);
      state.thinoLoaded = true;
      renderThinoMemos(memos.memos || []);
      renderHeatmap(heat);
      $("thino-tags").innerHTML = (tags.tags || []).slice(0, 12).map((t) =>
        '<span class="tag-chip" data-tag="' + esc(t.tag) + '">' + esc(t.tag) + " " + t.count + "</span>").join("") ||
        '<span class="muted" style="font-size:12px">还没有标签</span>';
      $("thino-tags").querySelectorAll("[data-tag]").forEach((el) => {
        el.addEventListener("click", () => { $("thino-search").value = el.dataset.tag; filterThino(); });
      });
    } catch (err) {
      $("thino-list").innerHTML = '<div class="thino-memo"><div class="thino-memo-text">加载失败：' + esc(err.message) + "</div></div>";
    }
  }

  async function addMemo() {
    const input = $("thino-input");
    const text = input.value.trim();
    if (!text) { input.focus(); return; }
    try {
      await api("/api/diary/memos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: isoDate(new Date()), text: text }),
      });
      input.value = "";
      setStatus("thino-status", "已记录", "ok");
      await loadThino();
      refreshTodayMemos();
      if (state.entry && state.entry.key === isoDate(new Date()) && state.gran === "day") loadEntry();
    } catch (err) {
      setStatus("thino-status", "记录失败：" + err.message, "err");
    }
  }

  function openDiaryDate(key) {
    const apply = () => {
      const p = key.split("-").map(Number);
      state.date = new Date(p[0], p[1] - 1, p[2]);
      state.calYear = p[0]; state.calMonth = p[1] - 1;
      state.gran = "day";
      document.querySelectorAll("#diary-gran .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.gran === "day"));
      populateSelects();
      loadEntry();
      refreshCalendar();
    };
    if (!state.diaryLoaded) {
      state.pendingDate = key;
      const tab = document.querySelector('.tab[data-tab="diary"]');
      if (tab) tab.click();
    } else {
      apply();
    }
  }

  // ---------- 图片 ----------

  async function handleThinoImage(file) {
    if (!file) return;
    try {
      setStatus("thino-status", "压缩图片中…");
      const bitmap = await createImageBitmap(file);
      const max = 2000;
      const scale = Math.min(1, max / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const ctx = canvas.getContext("2d");
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL("image/webp", 0.85);
      const res = await api("/api/diary/assets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: dataUrl.split(",")[1], ext: "webp" }),
      });
      const ta = $("thino-input");
      const alt = file.name.replace(/\.[^.]+$/, "");
      const md = "![" + alt + "](" + mdAsset(res.url) + ")";
      ta.setRangeText(md, ta.selectionStart, ta.selectionEnd, "end");
      ta.focus();
      setStatus("thino-status", "图片已插入，点 NOTE 保存", "ok");
    } catch (err) {
      setStatus("thino-status", "图片处理失败：" + err.message + "（HEIC 请先转 JPEG）", "err");
    } finally {
      $("thino-image-file").value = "";
    }
  }

  function insertImageUrl(url, alt) {
    const md = "![" + (alt || "图片") + "](" + mdAsset(url) + ")";
    if (state.sourceMode) {
      const ta = $("diary-source");
      ta.setRangeText(md, ta.selectionStart, ta.selectionEnd, "end");
      ta.dispatchEvent(new Event("input"));
    } else if (state.vditor) {
      state.vditor.insertValue(md, true);
      state.editVersion++;
      state.dirty = true;
      scheduleSave();
    } else {
      setStatus("editor-status", "编辑器还在加载，请稍后重试", "err");
    }
  }

  async function handleImage(file) {
    if (!file) return;
    try {
      setStatus("editor-status", "压缩图片中…");
      const bitmap = await createImageBitmap(file);
      const max = 2000;
      const scale = Math.min(1, max / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const ctx = canvas.getContext("2d");
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL("image/webp", 0.85);
      const data = dataUrl.split(",")[1];
      const res = await api("/api/diary/assets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: data, ext: "webp" }),
      });
      insertImageUrl(res.url, file.name.replace(/\.[^.]+$/, ""));
      setStatus("editor-status", "图片已插入（已压缩）", "ok");
    } catch (err) {
      setStatus("editor-status", "图片处理失败：" + err.message + "（HEIC 请先转 JPEG）", "err");
    } finally {
      $("diary-image-file").value = "";
    }
  }

  // ---------- 导入 ----------

  async function importZip(file) {
    if (!file) return;
    setStatus("diary-status", "导入中…");
    try {
      const resp = await fetch("/api/diary/import?overwrite=0", {
        method: "POST",
        headers: { "Content-Type": "application/zip" },
        body: file,
      });
      const data = await resp.json();
      if (!resp.ok || data.ok === false) throw new Error(data.error || "导入失败");
      setStatus("diary-status", "导入 " + data.imported + "，跳过 " + data.skipped +
        "，冲突 " + data.conflict + "，附件 " + data.assets, "ok");
      refreshCalendar(); refreshRecent(); refreshTodayMemos();
      if (state.diaryLoaded) loadEntry();
    } catch (err) {
      setStatus("diary-status", "导入失败：" + err.message, "err");
    } finally {
      $("diary-import-file").value = "";
    }
  }

  // ---------- 事件 ----------

  function applyThinoCommand(cmd) {
    const ta = $("thino-input");
    if (cmd === "image") { $("thino-image-file").click(); return; }
    if (cmd === "clear") { ta.value = ""; ta.focus(); return; }
    if (cmd === "ai") { setStatus("thino-status", "AI 工具栏 P1", "warn"); return; }
    const wrap = { bold: ["**", "**"], italic: ["*", "*"], strike: ["~~", "~~"], code: ["`", "`"] };
    const prefix = { h2: "## ", h3: "### ", ul: "- ", ol: "1. ", quote: "> " };
    const start = ta.selectionStart, end = ta.selectionEnd;
    const sel = ta.value.slice(start, end);
    if (wrap[cmd]) {
      const pair = wrap[cmd];
      ta.setRangeText(pair[0] + (sel || "文字") + pair[1], start, end, "end");
    } else if (prefix[cmd]) {
      ta.setRangeText(prefix[cmd] + sel, start, start, "end");
    } else if (cmd === "link") {
      ta.setRangeText("[" + (sel || "文字") + "](https://)", start, end, "end");
    }
    ta.focus();
  }

  async function loadTemplate(gran) {
    state.templateGran = gran;
    document.querySelectorAll("#template-gran .seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.tgran === gran);
    });
    try {
      const key = keyFor(gran, state.date);
      const data = await api("/api/diary/templates/" + encodeURIComponent(gran) + "?key=" + encodeURIComponent(key));
      state.templateRaw = data.raw || "";
      state.templateContent = data.content || "";
      $("template-path").textContent = data.path + (data.exists ? "" : "（不存在，保存后创建）");
      $("template-preview").innerHTML = mdToHtml(state.templateContent);
      $("template-source").value = state.templateRaw;
      setStatus("template-status", "");
    } catch (err) {
      setStatus("template-status", "加载失败：" + err.message, "err");
    }
  }

  function openTemplateModal() {
    $("diary-template-modal").hidden = false;
    state.templateEdit = false;
    $("template-source").hidden = true;
    $("template-preview").hidden = false;
    $("btn-template-save").hidden = true;
    $("btn-template-edit").textContent = "编辑模板";
    $("btn-template-insert").disabled = false;
    $("btn-template-apply").disabled = false;
    loadTemplate(state.gran);
  }

  function closeTemplateModal() {
    if (state.templateEdit && !confirm("模板修改未保存，确定关闭？")) return;
    $("diary-template-modal").hidden = true;
  }

  function stripFrontmatter(content) {
    return String(content || "").replace(/^---\n[\s\S]*?\n---\n?/, "");
  }

  function stripMemos(content) {
    const lines = String(content || "").split("\n");
    let idx = -1;
    lines.forEach((l, i) => { if (/^\s*#{0,6}\s*Memos\s*$/.test(l)) idx = i; });
    if (idx < 0) return content;
    let end = lines.length;
    for (let i = idx + 1; i < lines.length; i++) {
      if (/^#{1,6}\s+\S/.test(lines[i])) { end = i; break; }
    }
    return lines.slice(0, idx).join("\n") + (end < lines.length ? "\n" + lines.slice(end).join("\n") : "");
  }

  function insertTemplate() {
    if (state.templateGran !== state.gran) {
      alert("模板是「" + state.templateGran + "」粒度，当前日记是「" + state.gran + "」，请先在日记页切换粒度。");
      return;
    }
    const content = stripMemos(stripFrontmatter(state.templateContent));
    if (!content.trim()) { setStatus("template-status", "模板是空的", "warn"); return; }
    if (state.sourceMode) {
      const ta = $("diary-source");
      const base = ta.value && !ta.value.endsWith("\n") ? "\n\n" : "";
      ta.setRangeText(base + content, ta.selectionStart, ta.selectionEnd, "end");
      ta.dispatchEvent(new Event("input"));
    } else if (state.vditor && state.vditorReady) {
      state.vditor.insertValue(content, true);
      state.editVersion++;
      state.dirty = true;
      scheduleSave();
    } else {
      setStatus("template-status", "编辑器还在加载，请稍后重试", "err");
      return;
    }
    $("diary-template-modal").hidden = true;
    setStatus("editor-status", "模板已插入，自动保存…", "warn");
  }

  async function applyTemplate() {
    if (!state.entry) { alert("日记还在加载，请稍后再试"); return; }
    if (state.templateGran !== state.gran) {
      alert("模板是「" + state.templateGran + "」粒度，当前日记是「" + state.gran + "」，请先在日记页切换粒度。");
      return;
    }
    if (!confirm("用模板覆盖当前正文？Memos 会保留。")) return;
    const content = state.templateContent;
    if (!content.trim()) { setStatus("template-status", "模板是空的", "warn"); return; }
    const parts = splitNote(content);
    state.parts = parts;
    state.complex = isComplex(parts);
    state.sourceMode = state.complex;
    if (state.complex) state.entry.content = content;
    const ready = await renderDoc();
    if (!ready) {
      setStatus("editor-status", "编辑器尚未就绪，已取消覆盖", "err");
      return;
    }
    state.editVersion++;
    state.dirty = true;
    await saveEntry();
    $("diary-template-modal").hidden = true;
  }

  function prevSummaryKey(gran, d) {
    const x = new Date(d);
    if (gran === "week") { x.setDate(x.getDate() - 7); return isoWeek(x); }
    if (gran === "month") { x.setDate(1); x.setMonth(x.getMonth() - 1); return x.getFullYear() + "-" + pad(x.getMonth() + 1); }
    if (gran === "quarter") { x.setDate(1); x.setMonth(x.getMonth() - 3); return x.getFullYear() + "-Q" + (Math.floor(x.getMonth() / 3) + 1); }
    return String(x.getFullYear() - 1);
  }

  function nextSummaryKey(gran, key) {
    if (gran === "week") { const d = weekStart(key); d.setDate(d.getDate() + 7); return isoWeek(d); }
    if (gran === "month") {
      const p = key.split("-").map(Number);
      if (p.length < 2) return "";
      const d = new Date(p[0], p[1], 1);
      return d.getFullYear() + "-" + pad(d.getMonth() + 1);
    }
    if (gran === "quarter") {
      const m = /^(\d{4})-Q([1-4])$/.exec(key);
      if (!m) return "";
      let y = Number(m[1]), q = Number(m[2]) + 1;
      if (q > 4) { q = 1; y += 1; }
      return y + "-Q" + q;
    }
    if (gran === "year") return key ? String(Number(key) + 1) : "";
    return "";
  }

  function updateSummaryLabel() {
    const key = $("summary-source-key").value.trim();
    const next = nextSummaryKey(state.summaryGran, key);
    $("summary-target-label").textContent = next ? "→ " + next + "（下期）" : "";
  }

  function setSummaryGran(gran) {
    state.summaryGran = gran;
    state.summaryData = null;
    document.querySelectorAll("#summary-gran .seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.sgran === gran);
    });
    $("summary-source-key").value = prevSummaryKey(gran, state.date);
    $("summary-text").value = "";
    setStatus("summary-status", "");
    updateSummaryLabel();
  }

  function openSummaryModal() {
    $("summary-modal").hidden = false;
    const current = ["week", "month", "quarter", "year"].includes(state.gran) ? state.gran : "week";
    setSummaryGran(current);
  }

  async function generateSummary() {
    const key = $("summary-source-key").value.trim();
    if (!key) { setStatus("summary-status", "请填写总结周期", "err"); return; }
    setStatus("summary-status", "AI 总结中…（可能需要 30–60 秒）");
    try {
      const data = await api("/api/diary/summarize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gran: state.summaryGran, key: key }),
      });
      state.summaryData = data;
      $("summary-text").value = data.summary || "";
      $("summary-target-label").textContent = "→ " + data.target_key + " · " + data.target_path;
      const via = data.model ? "（" + data.model + "）" : "";
      setStatus("summary-status", "已生成 " + data.source_count + " 篇笔记的总结" + via + "，可编辑后写入", "ok");
    } catch (err) {
      setStatus("summary-status", "生成失败：" + err.message, "err");
    }
  }

  async function applySummary() {
    if (!state.summaryData) {
      setStatus("summary-status", "请先生成总结", "warn");
      return;
    }
    const summary = $("summary-text").value.trim();
    if (!summary) {
      setStatus("summary-status", "总结内容不能为空", "err");
      return;
    }
    setStatus("summary-status", "写入中…");
    try {
      const data = await api("/api/diary/summarize/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          gran: state.summaryGran,
          key: $("summary-source-key").value.trim(),
          summary: summary,
          title: state.summaryData.title,
        }),
      });
      $("summary-modal").hidden = true;
      setStatus("diary-status", "总结已写入 " + data.target_path, "ok");
      refreshCalendar();
      refreshRecent();
      if (state.entry && state.entry.key === data.target_key && state.gran === state.summaryGran) loadEntry();
    } catch (err) {
      setStatus("summary-status", "写入失败：" + err.message, "err");
    }
  }

  function bind() {
    window.addEventListener("tab:shown", (e) => {
      if (e.detail.tab === "thino") loadThino();
      if (e.detail.tab === "diary") loadDiary();
    });

    $("btn-thino-note").addEventListener("click", addMemo);
    document.querySelectorAll("#tab-thino [data-tcmd]").forEach((b) => {
      b.addEventListener("click", () => applyThinoCommand(b.dataset.tcmd));
    });
    $("thino-input").addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); addMemo(); }
    });
    $("thino-search").addEventListener("input", filterThino);
    $("btn-thino-paste").addEventListener("click", () => setStatus("thino-status", "直接 Ctrl+V 粘贴即可", "ok"));

    $("diary-today").addEventListener("click", () => {
      state.date = new Date();
      state.calYear = state.date.getFullYear();
      state.calMonth = state.date.getMonth();
      state.gran = "day";
      document.querySelectorAll("#diary-gran .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.gran === "day"));
      populateSelects(); loadEntry(); refreshCalendar();
    });
    document.querySelectorAll("#diary-gran .seg-btn").forEach((b) => {
      b.addEventListener("click", () => setGran(b.dataset.gran));
    });
    $("cal-prev").addEventListener("click", () => shiftPeriod(-1));
    $("cal-next").addEventListener("click", () => shiftPeriod(1));
    $("cal-year").addEventListener("change", (e) => {
      state.calYear = Number(e.target.value);
      state.date = new Date(state.calYear, state.calMonth, 1);
      refreshCalendar();
    });
    $("cal-month").addEventListener("change", (e) => {
      state.calMonth = Number(e.target.value) - 1;
      state.date = new Date(state.calYear, state.calMonth, 1);
      refreshCalendar();
    });
    $("btn-diary-thino").addEventListener("click", () => {
      const tab = document.querySelector('.tab[data-tab="thino"]');
      if (tab) tab.click();
    });
    $("btn-diary-template").addEventListener("click", openTemplateModal);
    $("btn-diary-summary").addEventListener("click", openSummaryModal);
    $("btn-summary-close").addEventListener("click", () => { $("summary-modal").hidden = true; });
    $("summary-modal").addEventListener("click", (e) => {
      if (e.target.id === "summary-modal") $("summary-modal").hidden = true;
    });
    document.querySelectorAll("#summary-gran .seg-btn").forEach((b) => {
      b.addEventListener("click", () => setSummaryGran(b.dataset.sgran));
    });
    $("summary-source-key").addEventListener("input", () => {
      state.summaryData = null;
      $("summary-text").value = "";
      updateSummaryLabel();
    });
    $("btn-summary-generate").addEventListener("click", generateSummary);
    $("btn-summary-apply").addEventListener("click", applySummary);
    $("btn-summary-settings").addEventListener("click", () => {
      window.dispatchEvent(new CustomEvent("settings:open"));
    });
    $("btn-template-close").addEventListener("click", closeTemplateModal);
    $("diary-template-modal").addEventListener("click", (e) => {
      if (e.target.id === "diary-template-modal") closeTemplateModal();
    });
    document.querySelectorAll("#template-gran .seg-btn").forEach((b) => {
      b.addEventListener("click", () => {
        if (state.templateEdit && !confirm("放弃未保存的模板修改？")) return;
        state.templateEdit = false;
        $("template-source").hidden = true;
        $("template-preview").hidden = false;
        $("btn-template-save").hidden = true;
        $("btn-template-edit").textContent = "编辑模板";
        $("btn-template-insert").disabled = false;
        $("btn-template-apply").disabled = false;
        loadTemplate(b.dataset.tgran);
      });
    });
    $("btn-template-edit").addEventListener("click", () => {
      state.templateEdit = !state.templateEdit;
      $("template-source").hidden = !state.templateEdit;
      $("template-preview").hidden = state.templateEdit;
      $("btn-template-save").hidden = !state.templateEdit;
      $("btn-template-insert").disabled = state.templateEdit;
      $("btn-template-apply").disabled = state.templateEdit;
      $("btn-template-edit").textContent = state.templateEdit ? "取消编辑" : "编辑模板";
      if (state.templateEdit) $("template-source").value = state.templateRaw;
      else loadTemplate(state.templateGran);
    });
    $("btn-template-save").addEventListener("click", async () => {
      try {
        const content = $("template-source").value;
        const data = await api("/api/diary/templates/" + encodeURIComponent(state.templateGran), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: content }),
        });
        state.templateRaw = data.raw || content;
        state.templateEdit = false;
        $("template-source").hidden = true;
        $("template-preview").hidden = false;
        $("btn-template-save").hidden = true;
        $("btn-template-edit").textContent = "编辑模板";
        $("btn-template-insert").disabled = false;
        $("btn-template-apply").disabled = false;
        await loadTemplate(state.templateGran);
        setStatus("template-status", "模板已保存", "ok");
      } catch (err) {
        setStatus("template-status", "保存失败：" + err.message, "err");
      }
    });
    $("btn-template-insert").addEventListener("click", insertTemplate);
    $("btn-template-apply").addEventListener("click", applyTemplate);

    $("diary-source").addEventListener("input", () => {
      state.editVersion++;
      state.dirty = true;
      scheduleSave();
    });
    document.querySelectorAll("#doc-toolbar button[data-cmd]").forEach((b) => {
      b.addEventListener("click", () => applyCommand(b.dataset.cmd));
    });
    $("btn-diary-image").addEventListener("click", () => $("diary-image-file").click());
    $("btn-diary-source").addEventListener("click", () => {
      if (!state.entry || state.complex) return;
      if (state.sourceMode) {
        state.sourceMode = false;
        state.parts = splitNote($("diary-source").value);
        state.entry.content = $("diary-source").value;
        renderDoc();
      } else {
        state.sourceMode = true;
        $("diary-source").value = state.vditor ? state.vditor.getValue() : state.entry.content;
        renderDoc();
      }
    });
    $("diary-image-file").addEventListener("change", (e) => handleImage(e.target.files[0]));
    $("thino-image-file").addEventListener("change", (e) => handleThinoImage(e.target.files[0]));
    document.addEventListener("click", () => {
      document.querySelectorAll("#thino-list .memo-menu").forEach((m) => { m.hidden = true; });
    });
    $("btn-diary-import").addEventListener("click", () => $("diary-import-file").click());
    $("diary-import-file").addEventListener("change", (e) => importZip(e.target.files[0]));
    $("btn-diary-export").addEventListener("click", () => setStatus("diary-status", "导出待接入；当前可备份 ~/文档/portal-diary", "warn"));
    window.addEventListener("beforeunload", (e) => {
      if (state.dirty) { e.preventDefault(); e.returnValue = ""; }
    });
  }

  bind();
})();
