/* 设置：AI 模型配置 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const modal = $("settings-modal");
  if (!modal) return;

  async function api(path, opts) {
    const resp = await fetch(path, Object.assign({ cache: "no-store" }, opts || {}));
    const data = await resp.json().catch(() => ({ ok: false, error: "响应不是 JSON" }));
    if (!resp.ok || data.ok === false) throw new Error(data.error || ("HTTP " + resp.status));
    return data;
  }

  function setStatus(text, kind) {
    const el = $("settings-status");
    el.textContent = text || "";
    el.className = "diary-toast" + (kind ? " " + kind : "");
  }

  function showTab(tab) {
    document.querySelectorAll("#settings-tabs .seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.stab === tab);
    });
    $("settings-pane-ai").hidden = tab !== "ai";
    $("settings-pane-usage").hidden = tab !== "usage";
    $("settings-pane-about").hidden = tab !== "about";
  }

  async function loadConfig() {
    setStatus("读取中…");
    try {
      const data = await api("/api/ai/status");
      $("ai-base-url").value = data.base_url || "";
      $("ai-model").value = data.model || "";
      $("ai-api-key").value = "";
      $("ai-key-hint").textContent = data.configured
        ? "已配置：" + (data.key_hint || "已保存") + "（来源：" + (data.source || "本机") + "）"
        : "还没有配置 API Key。";
      setStatus("");
    } catch (err) {
      setStatus("读取失败：" + err.message, "err");
    }
  }

  function openSettings() {
    modal.hidden = false;
    showTab("ai");
    loadConfig();
  }

  function closeSettings() {
    modal.hidden = true;
  }

  $("btn-settings").addEventListener("click", openSettings);
  $("btn-settings-close").addEventListener("click", closeSettings);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeSettings(); });
  document.querySelectorAll("#settings-tabs .seg-btn").forEach((b) => {
    b.addEventListener("click", () => showTab(b.dataset.stab));
  });

  $("btn-ai-save").addEventListener("click", async () => {
    setStatus("保存中…");
    try {
      const data = await api("/api/ai/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: $("ai-base-url").value.trim(),
          model: $("ai-model").value.trim(),
          api_key: $("ai-api-key").value.trim(),
        }),
      });
      $("ai-api-key").value = "";
      $("ai-key-hint").textContent = data.configured
        ? "已配置：" + (data.key_hint || "已保存")
        : "还没有配置 API Key。";
      setStatus("已保存", "ok");
    } catch (err) {
      setStatus("保存失败：" + err.message, "err");
    }
  });

  window.addEventListener("settings:open", openSettings);
})();
