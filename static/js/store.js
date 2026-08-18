/* =========================================================
   store.js — 极简发布订阅 store
   ========================================================= */

window.StStore = (function () {
  const state = {};
  const subs = new Map();

  function get(key) { return state[key]; }
  function set(key, value) {
    state[key] = value;
    const set = subs.get(key);
    if (set) set.forEach((fn) => fn(value));
  }
  function subscribe(key, fn) {
    if (!subs.has(key)) subs.set(key, new Set());
    subs.get(key).add(fn);
    return () => subs.get(key).delete(fn);
  }

  /* ---- Toast 服务 ---- */
  function showToast(text, ms = 2500) {
    let el = document.getElementById("global-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "global-toast";
      el.className = "toast";
      document.body.appendChild(el);
    }
    el.textContent = text;
    requestAnimationFrame(() => el.classList.add("is-visible"));
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove("is-visible"), ms);
  }

  return { get, set, subscribe, showToast };
})();
