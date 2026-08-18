/* =========================================================
   socket.js — Socket.IO 封装,提供自动重连与事件总线
   ========================================================= */

window.StSocket = (function () {
  let socket = null;
  const listeners = new Map();  // event -> Set<fn>
  let connected = false;

  function init() {
    if (socket) return socket;
    socket = io({
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      timeout: 20000,
    });

    socket.on("connect", () => {
      connected = true;
      fire("__connection_change", { connected: true });
      console.log("[socket] connected:", socket.id);
    });

    socket.on("disconnect", (reason) => {
      connected = false;
      fire("__connection_change", { connected: false, reason });
      console.log("[socket] disconnected:", reason);
    });

    socket.on("connect_error", (err) => {
      console.warn("[socket] connect_error:", err.message);
    });

    // 通用的服务端 -> 客户端事件分发
    [
      "connected", "joined", "room_created", "player_list", "st_player_list",
      "st_state_update",
      "error", "public_announcement", "state_update", "wake_up", "sleep",
      "private_info", "nomination_open", "nomination_closed", "execution",
      "death", "timer", "game_over", "llm_thinking", "role_assigned",
      "player_state",
      "room_closed", "room_closed_ack", "game_reset", "kicked",
"script_parsed", "script_applied",
    ].forEach((evt) => {
      socket.on(evt, (data) => fire(evt, data));
    });

    return socket;
  }

  function emit(event, payload) {
    if (!socket) init();
    socket.emit(event, payload || {});
  }

  function on(event, fn) {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event).add(fn);
    return () => listeners.get(event).delete(fn);
  }

  function fire(event, data) {
    const set = listeners.get(event);
    if (!set) return;
    set.forEach((fn) => {
      try { fn(data); } catch (e) { console.error(`[socket] listener for ${event} threw:`, e); }
    });
  }

  function isConnected() { return connected; }
  function getId() { return socket ? socket.id : null; }

  return { init, emit, on, isConnected, getId };
})();

// 自动初始化
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => window.StSocket.init());
} else {
  window.StSocket.init();
}
