/* =========================================================
   lobby.js — 大厅页交互
   ========================================================= */

(function () {
  const $ = (sel) => document.querySelector(sel);

  const btnCreate = $("#btn-create");
  const btnJoin = $("#btn-join");
  const stName = $("#st-name");
  const joinCode = $("#join-code");
  const joinName = $("#join-name");

  // ---- 房间号自动转大写 ----
  if (joinCode) {
    joinCode.addEventListener("input", (e) => {
      e.target.value = e.target.value.toUpperCase().replace(/[^A-Z]/g, "");
    });
  }

  // ---- 回车快捷键 ----
  if (joinName) {
    joinName.addEventListener("keydown", (e) => {
      if (e.key === "Enter") btnJoin && btnJoin.click();
    });
  }
  if (joinCode) {
    joinCode.addEventListener("keydown", (e) => {
      if (e.key === "Enter") joinName && joinName.focus();
    });
  }

  // ---- 防重复点击 ----
  function setBusy(btn) {
    if (!btn) return () => {};
    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = "处理中...";
    return () => { btn.disabled = false; btn.textContent = orig; };
  }

  if (btnCreate) {
    btnCreate.addEventListener("click", () => {
      const release = setBusy(btnCreate);
      const name = (stName.value || "说书人").trim();
      window.StSocket.emit("create_room", { name });
      setTimeout(release, 1500);
    });
  }
  if (btnJoin) {
    btnJoin.addEventListener("click", () => {
      const code = (joinCode.value || "").trim().toUpperCase();
      const name = (joinName.value || "").trim();
      if (!code || !name) {
        window.StStore.showToast("请填写房间号与名字");
        return;
      }
      const release = setBusy(btnJoin);
      window.StSocket.emit("join_room", { room_code: code, name });
      setTimeout(release, 1500);
    });
  }

  // ---- 最近关闭的房间快捷重入 ----
  let ss;
  try { ss = sessionStorage; } catch (e) { ss = null; }
  const lastRoomCard = document.getElementById("last-room-card");
  const lastRoomCode = document.getElementById("last-room-code");
  const btnRejoinSt = document.getElementById("btn-rejoin-st");
  const btnClearLast = document.getElementById("btn-clear-last-room");
  // 我们在关闭/踢出时把 room_code 暂存到 ss(不去清,留给玩家后续看到)
  const lastRoom = ss && ss.getItem("st_last_room_code");
  if (lastRoomCard && lastRoom) {
    if (lastRoomCode) lastRoomCode.textContent = lastRoom;
    lastRoomCard.style.display = "block";
  }
  if (btnRejoinSt) {
    btnRejoinSt.addEventListener("click", () => {
      const code = ss && ss.getItem("st_last_room_code");
      if (!code) return;
      // 优先 localStorage(关浏览器后还在),其次 sessionStorage
      const tok = (typeof localStorage !== "undefined" && localStorage.getItem("st_token"))
                  || (ss && ss.getItem("st_token"));
      const url = tok ? `/st/${code}?t=${encodeURIComponent(tok)}` : `/st/${code}`;
      window.location.href = url;
    });
  }
  if (btnClearLast) {
    btnClearLast.addEventListener("click", () => {
      if (ss) ss.removeItem("st_last_room_code");
      if (lastRoomCard) lastRoomCard.style.display = "none";
      window.StStore.showToast("已清除");
    });
  }

  // ---- 事件:说书人创建房间成功 -> 跳转说书人控制台 ----
  window.StSocket.on("room_created", (data) => {
    if (!data || !data.room_code) return;
    window.StStore.showToast(`房间已创建: ${data.room_code}`);
    // 用 localStorage 存 st_token(同浏览器任意 tab 都能复用,跨浏览器/跨设备仍需 URL)
    try {
      sessionStorage.setItem("st_player_id", data.player_id);
      sessionStorage.setItem("st_room_code", data.room_code);
      if (data.st_token) {
        localStorage.setItem("st_token", data.st_token);
        sessionStorage.setItem("st_token", data.st_token);  // 备份
      }
    } catch (e) {}
    setTimeout(() => {
      // 必须带 ?t=<token>,否则 routes.py 会渲染"无权访问"页
      const tok = data.st_token || localStorage.getItem("st_token") || sessionStorage.getItem("st_token") || "";
      window.location.href = `/st/${data.room_code}?t=${encodeURIComponent(tok)}`;
    }, 400);
  });

  // ---- 事件:玩家加入房间成功 -> 跳转玩家页(带 name 参数)----
  window.StSocket.on("joined", (data) => {
    if (!data || !data.room_code) return;
    if (data.is_storyteller) return;  // 走 room_created 分支
    const name = (joinName && joinName.value || "").trim();
    try {
      sessionStorage.setItem("p_player_id", data.player_id);
      sessionStorage.setItem("p_room_code", data.room_code);
      if (data.player_token) sessionStorage.setItem("p_player_token", data.player_token);
      if (name) sessionStorage.setItem("p_player_name", name);
    } catch (e) {}
    // 把名字 + 玩家令牌 放在 URL query,玩家页可直接读取并自动加入
    const nameParam = encodeURIComponent(name);
    const tok = data.player_token || "";
    const tParam = tok ? `&t=${encodeURIComponent(tok)}` : "";
    window.location.href = `/p/${data.room_code}?name=${nameParam}${tParam}`;
  });

  // ---- 事件:错误提示 ----
  window.StSocket.on("error", (data) => {
    const msg = (data && data.message) || "发生未知错误";
    window.StStore.showToast(msg);
  });

  // ---- 连接状态 ----
  window.StSocket.on("__connection_change", (data) => {
    if (data.connected) {
      window.StStore.showToast("已连接", 1200);
    } else {
      window.StStore.showToast("连接断开,正在重连...");
    }
  });
})();
