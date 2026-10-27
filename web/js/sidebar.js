/* 侧边栏：主标签可拖动排序，使用说明固定底部 */
(function () {
  "use strict";

  const ORDER_KEY = "dsh_sidebar_order_v1";
  const nav = document.querySelector(".tabs");
  if (!nav) return;

  const getTabs = () => Array.from(nav.querySelectorAll(".tab"));
  const isMobile = () => window.matchMedia("(max-width: 760px)").matches;

  function saveOrder() {
    try {
      localStorage.setItem(ORDER_KEY, JSON.stringify(getTabs().map((t) => t.dataset.tab)));
    } catch (err) { /* 隐私模式忽略 */ }
  }

  function restoreOrder() {
    let saved = [];
    try {
      saved = JSON.parse(localStorage.getItem(ORDER_KEY) || "[]");
    } catch (err) { saved = []; }
    if (!Array.isArray(saved) || !saved.length) return;
    const current = getTabs();
    const byId = new Map(current.map((t) => [t.dataset.tab, t]));
    const ordered = [];
    saved.forEach((id) => {
      const el = byId.get(id);
      if (el && !ordered.includes(el)) ordered.push(el);
    });
    current.forEach((el) => { if (!ordered.includes(el)) ordered.push(el); });
    ordered.forEach((el) => nav.appendChild(el));
  }

  restoreOrder();

  const tabs = getTabs();
  let dragTab = null;
  let press = null;
  let touchDrag = null;
  let suppressClick = false;

  function clearIndicators() {
    nav.querySelectorAll(".tab.drag-over").forEach((el) => el.classList.remove("drag-over"));
  }

  function place(target, clientX, clientY) {
    if (!target || target === dragTab || target === touchDrag?.tab) return;
    clearIndicators();
    target.classList.add("drag-over");
    const rect = target.getBoundingClientRect();
    const before = isMobile()
      ? clientX < rect.left + rect.width / 2
      : clientY < rect.top + rect.height / 2;
    const moving = dragTab || (touchDrag && touchDrag.tab);
    if (!moving) return;
    nav.insertBefore(moving, before ? target : target.nextSibling);
  }

  function endDrag() {
    if (dragTab) {
      dragTab.classList.remove("dragging");
      dragTab.setAttribute("aria-grabbed", "false");
      dragTab = null;
    }
    if (touchDrag) {
      touchDrag.tab.classList.remove("dragging");
      touchDrag = null;
    }
    press = null;
    clearIndicators();
    document.body.classList.remove("tab-dragging");
    saveOrder();
  }

  tabs.forEach((tab) => {
    if (window.matchMedia("(pointer: fine)").matches) tab.draggable = true;
    tab.setAttribute("aria-grabbed", "false");

    tab.addEventListener("dragstart", (e) => {
      dragTab = tab;
      tab.classList.add("dragging");
      tab.setAttribute("aria-grabbed", "true");
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", tab.dataset.tab); } catch (err) { /* ignore */ }
      }
    });

    tab.addEventListener("dragend", endDrag);

    tab.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "mouse") return;
      press = {
        tab: tab,
        x: e.clientX,
        y: e.clientY,
        id: e.pointerId,
        timer: setTimeout(() => {
          if (!press) return;
          touchDrag = press;
          suppressClick = true;
          touchDrag.tab.classList.add("dragging");
          document.body.classList.add("tab-dragging");
          try { touchDrag.tab.setPointerCapture(touchDrag.id); } catch (err) { /* ignore */ }
        }, 320),
      };
    });

    tab.addEventListener("pointermove", (e) => {
      if (e.pointerType === "mouse") return;
      if (touchDrag) {
        e.preventDefault();
        place(document.elementFromPoint(e.clientX, e.clientY)?.closest(".tabs .tab"), e.clientX, e.clientY);
        return;
      }
      if (!press) return;
      if (Math.abs(e.clientX - press.x) > 8 || Math.abs(e.clientY - press.y) > 8) {
        clearTimeout(press.timer);
        press = null;
      }
    });

    tab.addEventListener("pointerup", () => {
      if (press) clearTimeout(press.timer);
      if (touchDrag) {
        endDrag();
        setTimeout(() => { suppressClick = false; }, 500);
      } else {
        press = null;
      }
    });

    tab.addEventListener("pointercancel", () => {
      if (press) clearTimeout(press.timer);
      if (touchDrag) endDrag();
      else press = null;
    });

    tab.addEventListener("contextmenu", (e) => {
      if (press || touchDrag) e.preventDefault();
    });
  });

  nav.addEventListener("dragover", (e) => {
    if (!dragTab) return;
    e.preventDefault();
    place(e.target.closest(".tabs .tab"), e.clientX, e.clientY);
  });

  nav.addEventListener("drop", (e) => {
    if (!dragTab) return;
    e.preventDefault();
    saveOrder();
  });

  nav.addEventListener("click", (e) => {
    if (suppressClick) {
      e.preventDefault();
      e.stopPropagation();
      suppressClick = false;
    }
  }, true);
})();
