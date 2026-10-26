"use strict";

// 小故事页：列表 / 详情 / 导入 / 批注。首屏不请求，切到页签后再加载。
const ST = { list: [], current: null, loaded: false, busy: false, pendingQuote: "", quoteCaptured: false };

const STORY_META_FIELDS = [
  ["seed_id", "seed"],
  ["template", "模板"],
  ["chars", "字数"],
  ["dialogue_ratio", "对白占比"],
  ["rubric_total", "自评"],
  ["ngram_max_overlap", "ngram重叠"],
];

function stEsc(value) {
  return DSH.escape(value == null ? "" : value);
}

function escBr(value) {
  return stEsc(value).replace(/\n/g, "<br>");
}

function statusLabel(status) {
  if (status === "published") return "已发布";
  if (status === "draft") return "草稿";
  return status ? String(status) : "";
}

function sourceLabel(source) {
  if (source === "manual") return "手工";
  if (source === "scheduled") return "定时";
  return source ? String(source) : "";
}

function storiesSetStatus(text, kind) {
  const el = document.getElementById("stories-status");
  if (!el) return;
  el.textContent = text || "";
  el.className = "save-status" + (kind ? " " + kind : "");
}

function setImportStatus(text, kind) {
  const el = document.getElementById("story-import-status");
  if (!el) return;
  el.textContent = text || "";
  el.className = "save-status" + (kind ? " " + kind : "");
}

function on(id, event, fn) {
  const el = document.getElementById(id);
  if (el) el.addEventListener(event, fn);
}

async function api(url, options) {
  const opts = Object.assign({ cache: "no-store" }, options || {});
  if (opts.body) {
    opts.headers = Object.assign(
      { "Content-Type": "application/json" },
      opts.headers || {}
    );
  }
  const resp = await fetch(url, opts);
  let data = null;
  try {
    data = await resp.json();
  } catch (err) {
    data = null;
  }
  if (!resp.ok || !data || data.ok === false) {
    throw new Error((data && data.error) || ("请求失败（" + resp.status + "）"));
  }
  return data;
}

function applyInline(text) {
  return String(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function renderBlock(block) {
  const lines = block.split("\n");
  let html = "";
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") {
      i += 1;
      continue;
    }
    if (line.startsWith("## ")) {
      html += "<h3>" + applyInline(line.slice(3)) + "</h3>";
      i += 1;
      continue;
    }
    if (line.startsWith("&gt; ")) {
      const parts = [];
      while (i < lines.length && lines[i].startsWith("&gt; ")) {
        parts.push(applyInline(lines[i].slice(5)));
        i += 1;
      }
      html += "<blockquote>" + parts.join("<br>") + "</blockquote>";
      continue;
    }
    if (line.startsWith("- ")) {
      const parts = [];
      while (i < lines.length && lines[i].startsWith("- ")) {
        parts.push("<li>" + applyInline(lines[i].slice(2)) + "</li>");
        i += 1;
      }
      html += "<ul>" + parts.join("") + "</ul>";
      continue;
    }
    const parts = [];
    while (i < lines.length) {
      const cur = lines[i];
      if (cur.startsWith("## ") || cur.startsWith("&gt; ") || cur.startsWith("- ")) break;
      parts.push(applyInline(cur));
      i += 1;
    }
    html += "<p>" + parts.join("<br>") + "</p>";
  }
  return html;
}

function renderMarkdownLite(text) {
  const escaped = DSH.escape(text == null ? "" : String(text));
  const blocks = escaped.split(/\n{2,}/);
  let html = "";
  for (let i = 0; i < blocks.length; i++) {
    if (blocks[i].split("\n").every((line) => line.trim() === "")) continue;
    html += renderBlock(blocks[i]);
  }
  return html;
}

function renderList() {
  const root = document.getElementById("story-list");
  if (!root) return;
  const items = ST.list || [];
  if (!items.length) {
    root.innerHTML = '<div class="story-empty">还没有故事，点『导入文稿』粘贴今天的 markdown</div>';
    return;
  }
  const currentId = ST.current ? String(ST.current.id) : "";
  root.innerHTML = items.map((story) => {
    const active = String(story.id) === currentId ? " active" : "";
    const badge = story.status === "draft" ? "draft" : "published";
    const count = Number(story.annotation_count || 0);
    return (
      '<div class="story-item' + active + '" data-id="' + stEsc(story.id) + '" role="button" tabindex="0">' +
        '<div class="story-item-date">' + stEsc(story.story_date) + "</div>" +
        '<div class="story-item-title">' + stEsc(story.title || "未命名故事") + "</div>" +
        '<div class="story-item-meta">' +
          '<span class="story-badge ' + badge + '">' + stEsc(statusLabel(story.status)) + "</span>" +
          "<span>批注 " + stEsc(isFinite(count) ? count : 0) + "</span>" +
        "</div>" +
      "</div>"
    );
  }).join("");
}

function metaTags(meta) {
  const source = meta && typeof meta === "object" ? meta : {};
  const tags = [];
  STORY_META_FIELDS.forEach((pair) => {
    const value = source[pair[0]];
    if (value == null || value === "") return;
    const text = typeof value === "object" ? JSON.stringify(value) : String(value);
    tags.push('<span>' + stEsc(pair[1]) + "：" + stEsc(text) + "</span>");
  });
  if (!tags.length) return "";
  return '<div class="story-meta">' + tags.join("") + "</div>";
}

function renderAnnotations(story) {
  const notes = story.annotations || [];
  const items = notes.map((note) => {
    const quote = note.quote ? '<div class="annotation-quote">' + escBr(note.quote) + "</div>" : "";
    return (
      '<div class="annotation-item">' +
        quote +
        '<div class="annotation-comment">' + escBr(note.comment) + "</div>" +
        '<button type="button" class="btn-del btn-annotation-delete" data-id="' + stEsc(note.id) + '">删除</button>' +
      "</div>"
    );
  }).join("");
  const empty = notes.length ? "" : '<div class="story-empty">还没有批注。选中正文后再点「添加批注」，可以带上引用。</div>';
  return (
    '<div class="story-annotations">' +
      '<div class="card-title">批注</div>' +
      items +
      empty +
      '<div class="story-actions">' +
        '<button type="button" class="btn btn-outline" id="btn-annotation-add">添加批注</button>' +
      "</div>" +
      '<div class="annotation-form" id="annotation-form" hidden>' +
        '<div class="annotation-quote" id="annotation-quote-preview"></div>' +
        '<textarea id="annotation-input" rows="3" placeholder="写下批注"></textarea>' +
        '<div class="story-actions">' +
          '<button type="button" class="btn btn-primary" id="btn-annotation-save">保存批注</button>' +
          '<button type="button" class="btn btn-outline" id="btn-annotation-cancel">取消</button>' +
        "</div>" +
      "</div>" +
    "</div>"
  );
}

function renderDetail() {
  const root = document.getElementById("story-detail");
  if (!root) return;
  const story = ST.current;
  if (!story) {
    const message = (ST.list && ST.list.length)
      ? "在左侧选择一篇故事"
      : "还没有故事，点『导入文稿』粘贴今天的 markdown";
    root.innerHTML = '<div class="story-empty">' + message + "</div>";
    return;
  }
  const published = story.status === "published";
  const statusBtn = published ? "转草稿" : "发布";
  root.innerHTML =
    '<div class="story-header">' +
      "<div>" +
        '<div class="story-title">' + stEsc(story.title || "未命名故事") + "</div>" +
        '<div class="story-item-meta">' +
          "<span>" + stEsc(story.story_date) + "</span>" +
          "<span>来源 " + stEsc(sourceLabel(story.source)) + "</span>" +
          '<span class="story-badge ' + (published ? "published" : "draft") + '">' +
            stEsc(statusLabel(story.status)) +
          "</span>" +
        "</div>" +
      "</div>" +
      '<div class="story-actions">' +
        '<button type="button" class="btn btn-outline" id="btn-story-status">' + statusBtn + "</button>" +
        '<button type="button" class="btn-del" id="btn-story-delete">删除</button>' +
      "</div>" +
    "</div>" +
    metaTags(story.meta) +
    '<div class="story-body">' + renderMarkdownLite(story.body || "") + "</div>" +
    renderAnnotations(story);
}

function quoteFromSelection() {
  const sel = window.getSelection ? window.getSelection() : null;
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return "";
  const text = String(sel.toString() || "").replace(/^\s+|\s+$/g, "");
  if (!text) return "";
  const body = document.querySelector("#story-detail .story-body");
  if (!body) return "";
  function inside(node) {
    if (!node) return false;
    const el = node.nodeType === 1 ? node : node.parentNode;
    return !!(el && body.contains(el));
  }
  if (!inside(sel.anchorNode) || !inside(sel.focusNode)) return "";
  return text;
}

function openAnnotationForm() {
  if (!ST.quoteCaptured) ST.pendingQuote = quoteFromSelection();
  ST.quoteCaptured = false;
  const form = document.getElementById("annotation-form");
  const preview = document.getElementById("annotation-quote-preview");
  const input = document.getElementById("annotation-input");
  if (!form || !preview || !input) return;
  preview.textContent = ST.pendingQuote
    ? ("引用：" + ST.pendingQuote)
    : "未选中正文，这条批注不附引用";
  input.value = "";
  form.hidden = false;
  input.focus();
}

function closeAnnotationForm() {
  const form = document.getElementById("annotation-form");
  if (form) form.hidden = true;
  ST.pendingQuote = "";
  ST.quoteCaptured = false;
}

async function selectStory(id) {
  if (id == null || id === "") return false;
  try {
    const data = await api("/api/stories/" + encodeURIComponent(id));
    ST.current = data.story;
    const row = (ST.list || []).find((item) => String(item.id) === String(ST.current.id));
    if (row) {
      row.status = ST.current.status;
      row.title = ST.current.title;
      row.story_date = ST.current.story_date;
      row.annotation_count = (ST.current.annotations || []).length;
    }
    renderList();
    renderDetail();
    return true;
  } catch (err) {
    storiesSetStatus(err.message || String(err), "err");
    const detail = document.getElementById("story-detail");
    if (detail) detail.innerHTML = '<div class="story-empty">' + stEsc(err.message || err) + "</div>";
    return false;
  }
}

async function loadStories(preferId) {
  storiesSetStatus("加载中…");
  try {
    const data = await api("/api/stories");
    ST.list = data.stories || [];
    ST.loaded = true;
    let nextId = preferId;
    if (nextId == null && ST.current) nextId = ST.current.id;
    const exists = nextId != null && ST.list.some((item) => String(item.id) === String(nextId));
    if (!exists) {
      ST.current = ST.list.length ? { id: ST.list[0].id } : null;
      nextId = ST.current ? ST.current.id : null;
    }
    renderList();
    if (nextId != null) {
      const ok = await selectStory(nextId);
      if (!ok) return false;
    } else {
      ST.current = null;
      renderDetail();
    }
    storiesSetStatus(ST.list.length ? ("共 " + ST.list.length + " 篇") : "还没有故事");
    return true;
  } catch (err) {
    ST.loaded = false;
    storiesSetStatus(err.message || String(err), "err");
    const detail = document.getElementById("story-detail");
    if (detail) detail.innerHTML = '<div class="story-empty">' + stEsc(err.message || err) + "</div>";
    return false;
  }
}

function openImport() {
  const modal = document.getElementById("story-import-modal");
  if (modal) modal.hidden = false;
  setImportStatus("");
  const area = document.getElementById("story-import-text");
  if (area) area.focus();
}

function closeImport() {
  const modal = document.getElementById("story-import-modal");
  if (modal) modal.hidden = true;
}

async function confirmImport() {
  if (ST.busy) return;
  const area = document.getElementById("story-import-text");
  const text = area ? area.value : "";
  if (!String(text).trim()) {
    setImportStatus("请先粘贴 markdown 文稿", "err");
    return;
  }
  ST.busy = true;
  setImportStatus("导入中…");
  try {
    const data = await api("/api/stories/import", {
      method: "POST",
      body: JSON.stringify({ markdown: text }),
    });
    if (area) area.value = "";
    closeImport();
    ST.loaded = false;
    const importedId = data.story && data.story.id;
    ST.busy = false;
    const loaded = await loadStories(importedId);
    if (loaded) storiesSetStatus("已导入", "ok");
  } catch (err) {
    setImportStatus(err.message || String(err), "err");
  } finally {
    ST.busy = false;
  }
}

async function setStatus(status) {
  if (!ST.current || ST.busy) return;
  ST.busy = true;
  try {
    const data = await api("/api/stories/" + encodeURIComponent(ST.current.id), {
      method: "PATCH",
      body: JSON.stringify({ status: status }),
    });
    ST.current = data.story;
    const row = (ST.list || []).find((item) => String(item.id) === String(ST.current.id));
    if (row) row.status = ST.current.status;
    renderList();
    renderDetail();
    storiesSetStatus(status === "published" ? "已发布" : "已转为草稿", "ok");
  } catch (err) {
    storiesSetStatus(err.message || String(err), "err");
  } finally {
    ST.busy = false;
  }
}

async function deleteStory() {
  if (!ST.current || ST.busy) return;
  const story = ST.current;
  const title = story.title || "未命名故事";
  if (!window.confirm("删除《" + title + "》及其全部批注？")) return;
  ST.busy = true;
  try {
    await api("/api/stories/" + encodeURIComponent(story.id), {
      method: "DELETE",
      cache: "no-store",
    });
    ST.current = null;
    ST.busy = false;
    const loaded = await loadStories();
    if (loaded) storiesSetStatus("已删除", "ok");
  } catch (err) {
    storiesSetStatus(err.message || String(err), "err");
  } finally {
    ST.busy = false;
  }
}

async function addAnnotation() {
  if (!ST.current || ST.busy) return;
  const input = document.getElementById("annotation-input");
  const comment = input ? input.value.trim() : "";
  if (!comment) {
    storiesSetStatus("批注内容不能为空", "err");
    return;
  }
  const storyId = ST.current.id;
  const quote = ST.pendingQuote || "";
  ST.busy = true;
  try {
    await api("/api/stories/" + encodeURIComponent(storyId) + "/annotations", {
      method: "POST",
      body: JSON.stringify({ quote: quote, comment: comment }),
    });
    ST.busy = false;
    const ok = await selectStory(storyId);
    if (ok) storiesSetStatus("批注已保存", "ok");
  } catch (err) {
    storiesSetStatus(err.message || String(err), "err");
  } finally {
    ST.busy = false;
  }
}

async function deleteAnnotation(annotationId) {
  if (!ST.current || ST.busy || annotationId == null || annotationId === "") return;
  if (!window.confirm("删除这条批注？")) return;
  const storyId = ST.current.id;
  ST.busy = true;
  try {
    await api(
      "/api/stories/" + encodeURIComponent(storyId) + "/annotations/" + encodeURIComponent(annotationId),
      { method: "DELETE", cache: "no-store" }
    );
    ST.busy = false;
    const ok = await selectStory(storyId);
    if (ok) storiesSetStatus("批注已删除", "ok");
  } catch (err) {
    storiesSetStatus(err.message || String(err), "err");
  } finally {
    ST.busy = false;
  }
}

function onListClick(e) {
  const item = e.target.closest(".story-item");
  if (!item || ST.busy) return;
  selectStory(item.getAttribute("data-id"));
}

function onListKey(e) {
  if (e.key !== "Enter" && e.key !== " ") return;
  const item = e.target.closest(".story-item");
  if (!item || ST.busy) return;
  e.preventDefault();
  selectStory(item.getAttribute("data-id"));
}

function onDetailMouseDown(e) {
  if (!e.target.closest("#btn-annotation-add")) return;
  ST.pendingQuote = quoteFromSelection();
  ST.quoteCaptured = true;
  e.preventDefault();
}

function onDetailClick(e) {
  if (e.target.closest("#btn-story-status")) {
    if (!ST.current) return;
    setStatus(ST.current.status === "published" ? "draft" : "published");
    return;
  }
  if (e.target.closest("#btn-story-delete")) {
    deleteStory();
    return;
  }
  if (e.target.closest("#btn-annotation-add")) {
    openAnnotationForm();
    return;
  }
  if (e.target.closest("#btn-annotation-cancel")) {
    closeAnnotationForm();
    return;
  }
  if (e.target.closest("#btn-annotation-save")) {
    addAnnotation();
    return;
  }
  const del = e.target.closest(".btn-annotation-delete");
  if (del) deleteAnnotation(del.getAttribute("data-id"));
}

function initStories() {
  on("btn-stories-refresh", "click", () => loadStories());
  on("btn-stories-import", "click", openImport);
  on("btn-story-import-cancel", "click", closeImport);
  on("btn-story-import-close", "click", closeImport);
  on("btn-story-import-confirm", "click", confirmImport);
  on("story-list", "click", onListClick);
  on("story-list", "keydown", onListKey);
  on("story-detail", "mousedown", onDetailMouseDown);
  on("story-detail", "click", onDetailClick);
  on("story-import-modal", "click", (e) => {
    if (e.target.id === "story-import-modal") closeImport();
  });
  window.addEventListener("tab:shown", (e) => {
    if (e.detail && e.detail.tab === "stories" && !ST.loaded) loadStories();
  });
}

document.addEventListener("DOMContentLoaded", initStories);
