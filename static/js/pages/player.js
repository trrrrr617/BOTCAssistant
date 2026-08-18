/* =========================================================
   player.js — Player page (Stage 1.5)
   - Multi-nomination: each player can nominate 1 person, be nominated 1 time
   - Each player votes on each open nomination
   ========================================================= */

(function () {
  const $ = (sel) => document.querySelector(sel);

  const connPill = $("#conn-pill");
  const joinCard = $("#join-card");
  const autoJoinCard = $("#auto-joining-card");
  const autoJoinName = $("#auto-join-name");
  const btnJoin = $("#btn-join");
  const btnLeave = $("#btn-leave");
  const joinName = $("#join-name");

  const phaseBanner = $("#phase-banner");
  const phaseLabel = $("#phase-label");
  const dayNightLabel = $("#day-night-label");
  const timerLabel = $("#timer-label");

  const winnerBanner = $("#winner-banner");
  const winnerText = $("#winner-text");

  const roleCard = $("#role-card");
  const roleEmblem = $("#role-emblem");
  const roleName = $("#role-name");
  const roleStatus = $("#role-status");
  const demonDisguisesSection = $("#demon-disguises-section");
  const demonDisguisesList = $("#demon-disguises-list");
  const fabledInPlayCard = $("#fabled-in-play-card");
  const fabledInPlayList = $("#fabled-in-play-list");

  const actionCard = $("#action-card");
  const actionTitle = $("#action-title");
  const actionContent = $("#action-content");

  const votesCard = $("#votes-card");
  const votesContent = $("#votes-content");

  const announcementCard = $("#announcement-card");
  const announcementText = $("#announcement-text");
  const playerList = $("#player-list");

  const roomCode = window.ROOM_CODE;
  const roomExists = window.ROOM_EXISTS;

  const urlParams = new URLSearchParams(window.location.search);
  const nameFromUrl = (urlParams.get("name") || "").trim();

  let ss, ls;
  try { ss = sessionStorage; } catch (e) { ss = null; }
  try { ls = localStorage; } catch (e) { ls = null; }
  // 按房间分键存 player_id / player_token / room_code:关浏览器后还在,跨 tab 也能自动 reconnect 不再报 DUPLICATE_NAME
  // (同时存到 sessionStorage 是为了同 tab 内的快速读取,localStorage 跨 tab/重启)
  const roomKey = roomCode ? ("p_room_code_" + roomCode) : null;
  const pidKey = roomCode ? ("p_player_id_" + roomCode) : null;
  const tokKey = roomCode ? ("p_player_token_" + roomCode) : null;
  const savedRoom = (ls && roomKey && ls.getItem(roomKey)) || (ss && ss.getItem("p_room_code")) || "";
  const savedName = ss && ss.getItem("p_player_name");
  const savedPid = (ls && pidKey && ls.getItem(pidKey)) || (ss && ss.getItem("p_player_id")) || "";
  // 玩家令牌:URL ?t= 优先,再 fallback 到 localStorage(同房间分键,避免跨房间覆盖)
  const urlTok = urlParams.get("t") || "";
  const savedTok = (ls && tokKey && ls.getItem(tokKey)) || "";
  const playerToken = urlTok || savedTok || "";
  if (urlTok && ls && tokKey) {
    try { ls.setItem(tokKey, urlTok); } catch (e) {}
  }

  let myId = null;
  let myRole = null;
  let lastState = null;

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }
  function phaseLabelText(phase) {
    return {
      lobby: "大厅", setup: "准备", first_night: "首夜",
      day_discussion: "白天·讨论", day: "白天·提名",
      nomination: "提名", voting: "投票",
      execution: "处决", night: "夜晚", ended: "结束",
    }[phase] || phase;
  }
  function phaseEmblemClass(phase) {
    return {
      lobby: "emblem--fabled", first_night: "emblem--demon",
      day_discussion: "emblem--townsfolk", day: "emblem--townsfolk",
      nomination: "emblem--townsfolk", voting: "emblem--townsfolk",
      execution: "emblem--minion",
      night: "emblem--demon", ended: "emblem--fabled",
    }[phase] || "emblem--fabled";
  }
  // 用于在 day_discussion / day 阶段控制"现在玩家是否能提名/投票"
  // (DAY_DISCUSSION 只聊天,DAY 才开放提名)
  function isNominationOpen(phase) {
    return phase === "day";
  }
  function roleTeamClass(role) {
    if (!role) return "emblem--fabled";
    if (lastState && lastState.script) {
      const def = (lastState.script.roles || []).find(function (r) { return r.id === role; });
      if (def) {
        return {
          townsfolk: "emblem--townsfolk",
          outsider:  "emblem--outsider",
          minion:    "emblem--minion",
          demon:     "emblem--demon",
        }[def.team] || "emblem--fabled";
      }
    }
    return "emblem--fabled";
  }
  function roleDisplayName(role) {
    if (!role) return "";
    if (lastState && lastState.script) {
      const def = (lastState.script.roles || []).find(function (r) { return r.id === role; });
      if (def) return def.name || def.id;
    }
    return role;
  }

  // ---- 极简主题:JS 动态精简(只在 minimal 主题下生效)----
  // HTML/JS 完全不依赖极简主题,这里是"事后渲染"机制,主题切换时自动重新应用。
  function isMinimalTheme() {
    return document.documentElement.getAttribute("data-theme") === "minimal";
  }

  // 文案精简对照表:key=原文本(完整匹配),value=精简文本(空字符串表示隐藏)
  const MINIMAL_REPLACE = {
    // 卡片标题
    "你的身份": "我",
    "📜 在场传奇": "📜 传奇",
    "进行中的提名 · 投票": "投票",
    "活动日志": "日志",
    "在场玩家": "玩家",
    // 行动卡(actionTitle) — 标题固定精简
    "状态": "状态",
    "提名状态": "状态",
    "可提名玩家": "提名",
    // 行动卡内容(由 renderActionArea 内 innerHTML 写入)
    "选择一名玩家提名,或选择 pass": "提名一名玩家",
    "你已在本阶段提名过 · 等待说书人结束提名阶段": "已提名 · 等待",
    "你已 pass · 等待说书人结束提名阶段": "已 pass",
    "你已死亡,本轮投票已用。等待复活后恢复。": "已死亡 · 等待复活",
    "你已死亡,本轮死亡期间可投 <strong>1 票</strong>(谨慎选择提名)。": "已死亡 · 本轮 1 票",
    "没有可提命的玩家。": "无可提名",
    "pass(本阶段跳过提名)": "pass",
    // 投票按钮
    "投赞成": "✓",
    "投反对": "✗",
    // 状态卡 / 错误页
    "请确认房间号是否正确,或等待说书人创建房间。": "",
    "如果你是该房间的玩家,请使用加入时收到的完整链接(含 ?t=...)。": "",
    "需要玩家令牌(链接含 ?t=...)。": "需要令牌",
    "等待说书人创建房间。": "",
    // 日志 / 玩家列
    "记录私人日志...": "记...",
    "记录": "记",
    "暂无人...": "暂无",
    "暂无活动": "暂无",
    // 离开 / 返回
    "离开房间": "离开",
    "返回大厅": "返回",
    // modal
    "发送给说书人": "发给 ST",
    "仅说书人与你自己可见,适合私下提问或分享思路": "",
    "输入要发送给说书人的消息...": "消息...",
    "发送": "发",
    "可添加多条独立批注,每条都可单独编辑或删除(仅自己可见)": "",
    "输入新批注...": "批注...",
    "＋ 添加批注": "＋",
    // 输入标签
    "你的名字": "名字",
    "输入你的名字": "你的名字",
    // 按钮
    "📨 发给说书人": "📨 ST",
  };

  // 整段隐藏的教学性段落(.card > p 直接子元素,且不在白名单中)
  // minimal 主题下,这些段落通常只是"使用说明",可以直接隐藏
  function _hideMinimalTeachingParagraphs(root) {
    if (!isMinimalTheme()) return;
    const rootEl = root || document;
    // .card 里第一个 p 段落(说明文字)
    rootEl.querySelectorAll && rootEl.querySelectorAll(".card > p").forEach(function (el) {
      // 白名单:不放进教学段落的 p(比如投票提示里的描述)
      const t = el.textContent.trim();
      if (t.length > 8 && !t.startsWith("☠") && !t.startsWith("✓") && !t.startsWith("⏳")) {
        el.style.display = "none";
      }
    });
    // modal 里的说明 p
    rootEl.querySelectorAll && rootEl.querySelectorAll(".player-note-modal > p").forEach(function (el) {
      el.style.display = "none";
    });
  }

  // 应用文案精简:替换 title / 按钮 / placeholder 文本
  function applyMinimalCopy(root) {
    if (!isMinimalTheme()) return;
    const rootEl = root || document;
    // 1) .card__title
    rootEl.querySelectorAll && rootEl.querySelectorAll(".card__title").forEach(function (el) {
      const t = el.textContent.trim();
      if (MINIMAL_REPLACE[t] !== undefined && MINIMAL_REPLACE[t] !== "") {
        el.textContent = MINIMAL_REPLACE[t];
      }
    });
    // 2) button 文本
    rootEl.querySelectorAll && rootEl.querySelectorAll("button, a.btn, .btn").forEach(function (el) {
      const t = el.textContent.trim();
      if (MINIMAL_REPLACE[t] !== undefined && MINIMAL_REPLACE[t] !== "") {
        // 保留子元素(emoji 等),只改直接文本节点
        for (const node of Array.from(el.childNodes)) {
          if (node.nodeType === Node.TEXT_NODE) {
            node.textContent = MINIMAL_REPLACE[t];
            break;
          }
        }
      }
    });
    // 3) placeholder
    rootEl.querySelectorAll && rootEl.querySelectorAll("[placeholder]").forEach(function (el) {
      const p = el.getAttribute("placeholder");
      if (MINIMAL_REPLACE[p] !== undefined && MINIMAL_REPLACE[p] !== "") {
        el.setAttribute("placeholder", MINIMAL_REPLACE[p]);
      }
    });
    // 4) modal 标题
    rootEl.querySelectorAll && rootEl.querySelectorAll(".player-note-modal h3").forEach(function (el) {
      const t = el.textContent.trim();
      if (MINIMAL_REPLACE[t] !== undefined && MINIMAL_REPLACE[t] !== "") {
        el.textContent = MINIMAL_REPLACE[t];
      }
    });
    // 5) field label
    rootEl.querySelectorAll && rootEl.querySelectorAll(".field__label").forEach(function (el) {
      const t = el.textContent.trim();
      if (MINIMAL_REPLACE[t] !== undefined && MINIMAL_REPLACE[t] !== "") {
        el.textContent = MINIMAL_REPLACE[t];
      }
    });
    // 6) banner / 描述性段落
    rootEl.querySelectorAll && rootEl.querySelectorAll(".card > p").forEach(function (el) {
      const t = el.textContent.trim();
      if (MINIMAL_REPLACE[t] === "") {
        el.style.display = "none";
      }
    });
    _hideMinimalTeachingParagraphs(rootEl);
  }

  // 监听主题切换,主题变化时重新应用精简
  function _watchThemeChange() {
    const observer = new MutationObserver(function (mutations) {
      for (const m of mutations) {
        if (m.type === "attributes" && m.attributeName === "data-theme") {
          // 主题切换:先还原(刷新页面会清掉,但切换时已经改过的元素不会自动还原)
          // 这里简化处理:重新加载页面以保证完全正确
          // 实际上:页面级 reload 是最稳妥的方式
          // 但避免 reload,只在 minimal 下重新应用即可
          if (isMinimalTheme()) {
            // 切换到 minimal:重新应用精简
            applyMinimalCopy();
          } else {
            // 切回普通主题:reload 页面以彻底恢复原始文案
            // (因为简化版的文案已经写进 DOM 了,反向恢复很难)
            location.reload();
          }
        }
      }
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }

  // 页面初始化时,如果已经是 minimal 主题,应用精简
  if (isMinimalTheme()) {
    applyMinimalCopy();
  }
  _watchThemeChange();

  function showAutoJoining(name) {
    if (autoJoinCard) autoJoinCard.style.display = "block";
    if (autoJoinName) autoJoinName.textContent = name || "...";
    if (joinCard) joinCard.style.display = "none";
  }
  function showForm() {
    if (autoJoinCard) autoJoinCard.style.display = "none";
    if (joinCard) joinCard.style.display = "block";
    if (joinName) {
      joinName.value = nameFromUrl || savedName || "";
      setTimeout(() => joinName && joinName.focus(), 100);
    }
  }
  function showJoined() {
    if (autoJoinCard) autoJoinCard.style.display = "none";
    if (joinCard) joinCard.style.display = "none";
    if (btnLeave) btnLeave.style.display = "";
  }

  if (roomExists) {
    if (nameFromUrl) showAutoJoining(nameFromUrl);
    else showForm();
  }

  let timerInterval = null;
  function startTicker(state) {
    if (timerInterval) clearInterval(timerInterval);
    // 计时器只在白天讨论阶段运行(进入提名后投票有自己的进度条)
    if (state.phase !== "day_discussion" || !state.chat_started_at) {
      if (timerLabel) timerLabel.style.display = "none";
      return;
    }
    timerInterval = setInterval(() => {
      if (!lastState || lastState.phase !== "day_discussion" || !lastState.chat_started_at) {
        clearInterval(timerInterval);
        timerInterval = null;
        if (timerLabel) timerLabel.style.display = "none";
        return;
      }
      const elapsed = (Date.now() / 1000) - lastState.chat_started_at;
      const remaining = Math.max(0, lastState.chat_duration_sec - elapsed);
      if (timerLabel) {
        const m = Math.floor(remaining / 60);
        const s = Math.floor(remaining % 60);
        timerLabel.textContent = `聊天 ${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
        timerLabel.style.display = "";
        timerLabel.style.color = remaining < 30 ? "var(--rouge)" : "var(--gold-deep)";
      }
    }, 1000);
  }

  function renderList(state) {
    if (!playerList) return;
    const players = state.players || [];
    if (players.length === 0) {
      playerList.innerHTML = '<p style="color: var(--ink-soft);">暂无人...</p>';
      return;
    }
    // 获取当前玩家的私人批注(每个 target 一个数组)
    const myNotes = _playerNotes || {};
    // 只在 lobby / ended 阶段显示"换"小图标(游戏中禁用)
    const showSwap = (state.phase === "lobby" || state.phase === "ended");
    // pending_swap 中涉及我的玩家 ID(申请人或被申请人)— 用于高亮显示
    const pendingSwap = state.pending_swap;
    playerList.innerHTML = players.map((p) => {
      const statusText = p.is_storyteller ? "说书人" : (p.status === "alive" ? "存活" : (p.status === "dead" ? "已死亡" : "鬼魂"));
      const notesForTarget = myNotes[p.id] || [];
      const noteBtn = (!p.is_storyteller && p.id !== myId) ? `<button class="player-note-btn" onclick="window.StPlayerActions.openNoteEditor('${p.id}')" title="批注">📝</button>` : "";
      const noteTags = notesForTarget.length > 0
        ? `<div style="margin-top:4px;">${notesForTarget.map(n => `<span class="player-note-tag" title="${escapeHtml(n.text)}">${escapeHtml(n.text)}</span>`).join(" ")}</div>`
        : "";
      // 交换按钮:仅 lobby + 非 ST + 不是我本人 + 没有 pending_swap(同时只能一个)
      const showSwapBtn = showSwap && !p.is_storyteller && p.id !== myId && !pendingSwap;
      const swapBtn = showSwapBtn
        ? `<button class="player-swap-btn" data-swap-target="${p.id}" title="申请交换座位">⇄</button>`
        : "";
      // pending_swap 涉及此玩家:加高亮边框
      const inSwap = pendingSwap && (pendingSwap.from_id === p.id || pendingSwap.to_id === p.id);
      return `
        <div class="player-tile ${p.id === myId ? 'is-self' : ''} ${inSwap ? 'is-in-swap' : ''}" style="position: relative; ${p.status === 'dead' ? 'opacity: 0.5;' : ''}">
          <span class="player-tile__seat">No.${String(p.seat).padStart(2, "0")}</span>
          <div class="player-tile__name">${escapeHtml(p.name)}${noteBtn}</div>
          <div class="player-tile__status">${statusText}</div>
          ${noteTags}
          ${swapBtn}
        </div>
      `;
    }).join("");

    // 绑定"换"按钮:点击 → 发送 swap_request
    playerList.querySelectorAll(".player-swap-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const targetId = btn.getAttribute("data-swap-target");
        window.StSocket.emit("swap_request", { to_id: targetId });
      });
    });

    // 渲染 pending_swap 横幅(如果存在)
    renderSwapBanner(state);
  }

  // ---- 交换横幅 ----
  function renderSwapBanner(state) {
    const ps = state.pending_swap;
    if (!ps || (state.phase !== "lobby" && state.phase !== "ended")) {
      // 隐藏旧横幅(可能在 game_started 之后存在)
      const old = document.getElementById("swap-banner");
      if (old) old.remove();
      return;
    }
    let banner = document.getElementById("swap-banner");
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "swap-banner";
      banner.className = "banner";
      banner.style.marginBottom = "var(--space-3)";
      // 插到玩家列前
      playerList.parentNode.insertBefore(banner, playerList);
    }
    const isFrom = (ps.from_id === myId);
    const isTo = (ps.to_id === myId);
    let inner = "";
    if (isTo) {
      // 被申请人:接受 / 拒绝
      inner = `
        <span class="banner__icon">⇄</span>
        <span style="flex:1;"><strong>${escapeHtml(ps.from_name)}</strong> 想跟你交换座位</span>
        <button class="btn btn--primary" id="btn-swap-accept" style="padding: 4px 12px;">接受</button>
        <button class="btn btn--ghost" id="btn-swap-decline" style="padding: 4px 12px;">拒绝</button>
      `;
    } else if (isFrom) {
      // 申请人:显示等待 + 取消
      inner = `
        <span class="banner__icon">⇄</span>
        <span style="flex:1;">等待 <strong>${escapeHtml(ps.to_name)}</strong> 回应...</span>
        <button class="btn btn--ghost" id="btn-swap-cancel" style="padding: 4px 12px;">取消</button>
      `;
    } else {
      // 旁观者:看热闹
      inner = `
        <span class="banner__icon">⇄</span>
        <span style="flex:1;"><strong>${escapeHtml(ps.from_name)}</strong> 向 <strong>${escapeHtml(ps.to_name)}</strong> 申请交换座位</span>
      `;
    }
    banner.innerHTML = inner;
    banner.style.display = "flex";
    banner.style.alignItems = "center";
    banner.style.gap = "var(--space-2)";

    // 绑定按钮
    const btnAccept = document.getElementById("btn-swap-accept");
    const btnDecline = document.getElementById("btn-swap-decline");
    const btnCancel = document.getElementById("btn-swap-cancel");
    if (btnAccept) btnAccept.addEventListener("click", () => window.StSocket.emit("swap_accept", {}));
    if (btnDecline) btnDecline.addEventListener("click", () => window.StSocket.emit("swap_decline", {}));
    if (btnCancel) btnCancel.addEventListener("click", () => window.StSocket.emit("swap_cancel", {}));
  }

  function renderPhase(state) {
    if (!state) return;
    lastState = state;
    if (phaseBanner) phaseBanner.style.display = "";
    if (phaseLabel) {
      phaseLabel.textContent = phaseLabelText(state.phase);
      phaseLabel.className = "emblem " + phaseEmblemClass(state.phase);
    }
    if (dayNightLabel) {
      if (state.phase === "night" || state.phase === "first_night") {
        dayNightLabel.textContent = `第 ${state.night} 夜`;
      } else if (state.phase === "ended") {
        dayNightLabel.textContent = "已结束";
      } else if (state.day > 0) {
        dayNightLabel.textContent = `第 ${state.day} 天`;
      } else {
        dayNightLabel.textContent = "未开始";
      }
    }
    startTicker(state);

    if (winnerBanner) {
      if (state.phase === "ended" && state.winner) {
        winnerBanner.style.display = "flex";
        const w = state.winner === "good" ? "善良阵营 获胜" : state.winner === "evil" ? "邪恶阵营 获胜" : "游戏结束";
        winnerText.textContent = `${w} · ${state.win_reason || ""}`;
      } else {
        winnerBanner.style.display = "none";
      }
    }

    renderActionArea(state);
    renderVotesArea(state);
  }

  function renderActionArea(state) {
    if (!actionCard || !actionContent) return;
    const me = (state.players || []).find((p) => p.id === myId);
    if (!me) {
      actionCard.style.display = "none";
      return;
    }
    if (state.phase !== "day") {
      actionCard.style.display = "none";
      return;
    }
    actionCard.style.display = "block";

    if (me.status !== "alive") {
      actionTitle.textContent = "状态";
      // 检测是否已在本轮死亡期间投过票
      const alreadyVotedDead = (state.current_nominations || []).some((n) =>
        (n.votes || []).some((v) => v.voter_id === myId)
      );
      const hint = alreadyVotedDead
        ? `<p style="color: var(--ink-soft);">你已死亡,本轮投票已用。等待复活后恢复。</p>`
        : `<p style="color: var(--gold-deep);">☠ 你已死亡,本轮死亡期间可投 <strong>1 票</strong>(谨慎选择提名)。</p>`;
      actionContent.innerHTML = hint;
      applyMinimalCopy(actionCard);
      return;
    }

    const nominatedSet = new Set(state.nominated_in_phase || []);
    const passedSet = new Set(state.passed_in_phase || []);
    const alreadyNominated = nominatedSet.has(myId);
    const alreadyPassed = passedSet.has(myId);

    if (alreadyNominated) {
      actionTitle.textContent = "提名状态";
      actionContent.innerHTML = `<p style="color: var(--gold-deep);">你已在本阶段提名过 · 等待说书人结束提名阶段</p>`;
      applyMinimalCopy(actionCard);
      return;
    }
    if (alreadyPassed) {
      actionTitle.textContent = "提名状态";
      actionContent.innerHTML = `<p style="color: var(--ink-soft);">你已 pass · 等待说书人结束提名阶段</p>`;
      applyMinimalCopy(actionCard);
      return;
    }

    // 还没提名/没 pass
    const others = (state.players || []).filter(
      (p) => p.id !== myId && p.status === "alive" && !p.is_storyteller
    );
    if (others.length === 0) {
      actionTitle.textContent = "可提名玩家";
      actionContent.innerHTML = `<p style="color: var(--ink-soft);">没有可提命的玩家。</p>`;
      applyMinimalCopy(actionCard);
      return;
    }
    const targetedSet = new Set(state.nominated_as_target || []);
    actionTitle.textContent = "提名 / Pass";
    actionContent.innerHTML = `
      <p style="color: var(--ink-soft); font-size: var(--text-sm); margin-bottom: var(--space-3);">选择一名玩家提名,或选择 pass</p>
      <div class="player-grid" style="gap: var(--space-2);">
        ${others.map((p) => {
          const targeted = targetedSet.has(p.id);
          const disabled = targeted ? "disabled style='opacity: 0.4; cursor: not-allowed;'" : "";
          return `
            <button class="btn btn--ghost nominate-target" data-id="${p.id}" ${disabled}>
              No.${String(p.seat).padStart(2, "0")} · ${escapeHtml(p.name)}${targeted ? " · 已被提名" : ""}
            </button>
          `;
        }).join("")}
        <button class="btn btn--primary" id="btn-pass" style="margin-top: var(--space-2);">pass(本阶段跳过提名)</button>
      </div>
    `;
    document.querySelectorAll(".nominate-target:not([disabled])").forEach((btn) => {
      btn.addEventListener("click", () => {
        const targetId = btn.getAttribute("data-id");
        window.StSocket.emit("nominate", { target_id: targetId });
      });
    });
    const btnPass = document.getElementById("btn-pass");
    if (btnPass) {
      btnPass.addEventListener("click", () => {
        window.StSocket.emit("pass_nomination", {});
      });
    }
    // 极简主题:精简文案(button + p 段)
    applyMinimalCopy(actionCard);
  }

  function renderVotesArea(state) {
    if (!votesCard || !votesContent) return;
    const me = (state.players || []).find((p) => p.id === myId);
    if (!me) {
      votesCard.style.display = "none";
      return;
    }
    // 只有 ST 开放提名阶段(DAY)才显示投票区;
    // 白天讨论(DAY_DISCUSSION)只看聊天和计时,还不能提名/投票
    if (state.phase !== "day") {
      votesCard.style.display = "none";
      return;
    }
    // 死亡玩家始终能看到投票栏(避免投了反对后无法改主意)
    // 但"实质性"投过 YES(当前仍在计入结算)时,YES 按钮禁用;NO 始终可点。
    //
    // "实质性"的判断:以后端 viewer_dead_vote_used 真值为准。
    const isDead = me.status !== "alive";
    const hasActiveYes = isDead && (state.viewer_dead_vote_used === true);
    const openNoms = (state.current_nominations || []).filter((n) => !n.resolved);
    if (openNoms.length === 0) {
      votesCard.style.display = "none";
      return;
    }
    votesCard.style.display = "block";
    const findName = (id) => {
      const p = (state.players || []).find((x) => x.id === id);
      return p ? p.name : "?";
    };
    // 计算 alive 玩家总数(用于阈值标线 / "有资格被处决"高亮)
    const aliveCount = (state.players || []).filter((p) => p.status === "alive" && !p.is_storyteller).length;
    const threshold = aliveCount > 0 ? Math.ceil(aliveCount / 2) : 0;

    votesContent.innerHTML = openNoms.map((nom) => {
      const myVote = nom.votes.find((v) => v.voter_id === myId);
      const yesCount = nom.votes.filter((v) => v.value).length;
      const noCount = nom.votes.filter((v) => !v.value).length;
      // 死亡玩家中的 YES 数(用于进度条颜色区分)
      const deadYesCount = nom.votes.filter((v) => v.value && v.is_dead_vote).length;
      const liveYesCount = yesCount - deadYesCount;
      const metThreshold = yesCount >= threshold && threshold > 0;

      // YES 按钮:死亡玩家若已"实质性"投过 YES 则禁用
      const yesDisabled = hasActiveYes;
      const yesTitle = yesDisabled
        ? "你已在本轮死亡期间投过赞成票,先把原提名的赞成改为反对即可解锁"
        : "";

      // 投票状态徽章(右上角)
      let voteBadge = "";
      if (!myVote) {
        voteBadge = '<span class="vote-badge vote-badge--pending">⏳ 等待投票</span>';
      } else if (myVote.value) {
        voteBadge = '<span class="vote-badge vote-badge--yes">✓ 已投赞成</span>';
      } else {
        voteBadge = '<span class="vote-badge vote-badge--no">✓ 已投反对</span>';
      }

      // 进度条(双条:YES 左, NO 右)
      const totalVotes = yesCount + noCount;
      const yesPct = totalVotes > 0 ? Math.round((yesCount / Math.max(totalVotes, aliveCount)) * 100) : 0;
      const noPct = totalVotes > 0 ? Math.round((noCount / Math.max(totalVotes, aliveCount)) * 100) : 0;
      const thresholdPct = aliveCount > 0 ? Math.round((threshold / Math.max(totalVotes, aliveCount)) * 100) : 0;

      return `
        <div class="vote-card ${metThreshold ? 'vote-card--threshold' : ''}">
          <div class="vote-card__head">
            <div>
              <strong>${escapeHtml(findName(nom.nominator_id))}</strong>
              <span class="vote-card__sep">提名</span>
              <strong>${escapeHtml(findName(nom.nominee_id))}</strong>
            </div>
            ${voteBadge}
          </div>
          <div class="vote-buttons">
            <button class="btn ${myVote && myVote.value ? 'btn--primary' : ''}" data-nom-id="${nom.id}" data-vote="true" ${yesDisabled ? 'disabled title="' + escapeHtml(yesTitle) + '"' : ''}>投赞成</button>
            <button class="btn ${myVote && myVote.value === false ? 'btn--primary' : ''}" data-nom-id="${nom.id}" data-vote="false">投反对</button>
          </div>
          <div class="vote-progress">
            <div class="vote-progress__bar vote-progress__bar--yes ${metThreshold ? 'is-threshold' : ''}" style="width: ${yesPct}%;">
              <span class="vote-progress__num">${yesCount}</span>
              ${deadYesCount > 0 ? `<span class="vote-progress__dead">☠${deadYesCount}</span>` : ""}
            </div>
            <div class="vote-progress__sep">vs</div>
            <div class="vote-progress__bar vote-progress__bar--no" style="width: ${noPct}%;">
              <span class="vote-progress__num">${noCount}</span>
            </div>
          </div>
          ${threshold > 0 ? `<div class="vote-progress__hint">阈值 ${threshold} 票 ${metThreshold ? '· 已达成 ✓' : ''}</div>` : ""}
          ${isDead ? '<div class="vote-progress__hint" style="color: var(--rouge);">☠ 你已死亡 · 投反对不消耗 · 投赞成本轮只算一次</div>' : ""}
        </div>
      `;
    }).join("");
    document.querySelectorAll(".btn[data-nom-id]:not([disabled])").forEach((btn) => {
      btn.addEventListener("click", () => {
        const nomId = btn.getAttribute("data-nom-id");
        const value = btn.getAttribute("data-vote") === "true";
        window.StSocket.emit("vote", { value, nomination_id: nomId });
      });
    });
    // 极简主题:精简文案 + 删除阈值说明等
    applyMinimalCopy(votesCard);
  }

  function renderRoleCard(roleInfo) {
    if (!roleCard || !roleInfo) return;
    roleCard.style.display = "block";
    const role = roleInfo.true_role;
    myRole = role;
    if (roleEmblem) {
      roleEmblem.textContent = roleInfo.apparent_role || role;
      roleEmblem.className = "emblem " + roleTeamClass(roleInfo.apparent_role || role);
    }
    if (roleName) roleName.textContent = roleDisplayName(roleInfo.apparent_role || role);
    // 状态栏:显示玩家自己的名字(中毒/醉酒是隐藏信息,只有 ST 可见)
    if (roleStatus) {
      const me = (lastState && lastState.players || []).find((p) => p.id === myId);
      const myName = me ? me.name : "";
      roleStatus.textContent = myName ? `玩家: ${myName}` : "玩家";
    }
  }

  // ---- 恶魔的伪装(内嵌在身份卡内)----
  // 只对恶魔 / 爪牙玩家渲染;good 玩家 + ST 不显示
  // 数据来自 state_update.demon_disguises(后端仅对 evil 玩家注入)
  function renderDemonDisguises() {
    if (!demonDisguisesSection || !demonDisguisesList) return;
    const list = (lastState && Array.isArray(lastState.demon_disguises)) ? lastState.demon_disguises : [];
    // 只有拿到 demon_disguises(非空数组,后端仅 evil 玩家注入)的玩家才显示
    if (!list || list.length === 0) {
      demonDisguisesSection.style.display = "none";
      demonDisguisesList.innerHTML = "";
      return;
    }
    demonDisguisesSection.style.display = "block";
    demonDisguisesList.innerHTML = list.map(function (rid) {
      const name = roleDisplayName(rid) || rid;
      return "<span class=\"emblem emblem--townsfolk\" style=\"font-size: var(--text-xs); padding: 4px 10px;\">" + escapeHtml(name) + "</span>";
    }).join("");
  }

  // ---- 在场传奇角色(嵌在"我"卡的分段里,所有玩家可见,只要至少一个传奇在场就显示)----
  // 数据来自 state_update.fabled_in_play(后端公开)。从 lastState.script.roles
  // 查找对应 ScriptRole 来拿到名称和 notes。
  function renderFabledInPlay() {
    if (!fabledInPlayCard || !fabledInPlayList) return;
    const inPlay = (lastState && Array.isArray(lastState.fabled_in_play)) ? lastState.fabled_in_play : [];
    if (inPlay.length === 0) {
      fabledInPlayList.innerHTML = "";
      fabledInPlayCard.style.display = "none";
      return;
    }
    const script = lastState && lastState.script;
    const rolesById = {};
    if (script && Array.isArray(script.roles)) {
      script.roles.forEach(function (r) { rolesById[r.id] = r; });
    }
    fabledInPlayList.innerHTML = inPlay.map(function (rid) {
      const def = rolesById[rid];
      const name = (def && def.name) || roleDisplayName(rid) || rid;
      const notes = (def && def.notes) ? def.notes : "";
      const notesHtml = notes.trim()
        ? "<div style=\"margin-top: 4px; font-size: var(--text-sm); color: var(--ink-soft); white-space: pre-wrap;\">" + escapeHtml(notes) + "</div>"
        : "";
      return ""
        + "<li style=\"border: 1px solid var(--gold); border-radius: var(--radius-sm); padding: var(--space-3); background: var(--ivory);\">"
        + "<strong style=\"color: var(--gold-deep);\">" + escapeHtml(name) + "</strong>"
        + " <span style=\"color: var(--ink-soft); font-size: var(--text-xs);\">(" + escapeHtml(rid) + ")</span>"
        + notesHtml
        + "</li>";
    }).join("");
    fabledInPlayCard.style.display = "";

    // 极简主题:把在场传奇"嵌入"到"我"卡内,隐藏独立 section
    if (isMinimalTheme() && roleCard) {
      let slot = document.getElementById("role-fabled-inline");
      if (!slot) {
        slot = document.createElement("div");
        slot.id = "role-fabled-inline";
        slot.className = "role-fabled-inline";
        // 放在 demon-disguises-section 之后
        roleCard.appendChild(slot);
      }
      // 把 li 从 fabledInPlayList 移动到 slot(自动从源移除,避免重复)
      while (fabledInPlayList.firstChild) {
        slot.appendChild(fabledInPlayList.firstChild);
      }
      // 隐藏原 fabledInPlayCard(列表已搬空,但要彻底隐藏)
      fabledInPlayCard.style.display = "none";
    }
    applyMinimalCopy(fabledInPlayCard);
  }

  window.StSocket.on("__connection_change", (data) => {
    if (!connPill) return;
    if (data.connected) {
      connPill.textContent = "已连接";
      connPill.classList.remove("connection-pill--offline");
      if (autoJoinCard && autoJoinCard.style.display !== "none") tryAutoJoin();
    } else {
      connPill.textContent = "已断开 · 重连中";
      connPill.classList.add("connection-pill--offline");
    }
  });
  if (connPill && window.StSocket.isConnected()) connPill.textContent = "已连接";

  function tryAutoJoin() {
    if (!roomExists) return;
    if (savedRoom === roomCode && savedPid) {
      window.StSocket.emit("reconnect_room", {
        room_code: roomCode,
        player_id: savedPid,
        player_token: playerToken,
      });
    } else if (nameFromUrl) {
      window.StSocket.emit("join_room", { room_code: roomCode, name: nameFromUrl });
    }
  }

  window.StSocket.on("joined", (data) => {
    if (!data || data.is_storyteller) return;
    myId = data.player_id;
    if (ss) {
      ss.setItem("p_player_id", data.player_id);
      ss.setItem("p_room_code", data.room_code);
      const me = (data.players || []).find((p) => p.id === data.player_id);
      if (me && me.name) ss.setItem("p_player_name", me.name);
    }
    // 同时按 room_code 分键存到 localStorage,关浏览器/跨 tab 后还在(避免重入时 DUPLICATE_NAME)
    if (data.room_code && ls) {
      try { ls.setItem("p_room_code_" + data.room_code, data.room_code); } catch (e) {}
      try { ls.setItem("p_player_id_" + data.room_code, data.player_id); } catch (e) {}
    }
    if (data.player_token && data.room_code && ls) {
      try { ls.setItem("p_player_token_" + data.room_code, data.player_token); } catch (e) {}
    }
    showJoined();
    window.StStore.showToast(data.reconnected ? "已重连" : "已加入房间");
  });

  window.StSocket.on("state_update", (data) => {
    if (data && data.players) {
      const me = data.players.find((p) => p.id === myId);
      if (me) myId = me.id;
    }
    // 幽冥界面:死亡玩家页面加 data-player-status=dead(CSS overlay + tint)
    // 死后在夜间阶段会被 _public_payload 隐藏 status,所以只看 data 不在 nightly mask 之列
    if (data && data.players) {
      const me = data.players.find((p) => p.id === myId);
      if (me) {
        document.body.setAttribute("data-player-status", me.status);
      }
    }
    renderList(data);
    renderPhase(data);
    renderDemonDisguises();
    renderFabledInPlay();
    // 极简主题:重新应用文案精简(动态生成的 DOM 可能错过初始化)
    applyMinimalCopy();
  });
  window.StSocket.on("player_list", (data) => {
    if (data) renderList(data);
  });

  window.StSocket.on("role_assigned", (data) => {
    if (data) renderRoleCard(data);
    renderDemonDisguises();
  });

  window.StSocket.on("public_announcement", (data) => {
    if (!announcementCard || !announcementText) return;
    announcementText.textContent = data.text || "";
    announcementCard.style.display = "flex";
    setTimeout(() => { announcementCard.style.display = "none"; }, 5000);
  });

  window.StSocket.on("execution", (data) => {
    window.StStore.showToast(`${data.name} 被处决(${data.true_role || "?"})`, 5000);
  });

  window.StSocket.on("death", (data) => {
    window.StStore.showToast(`${data.name} 死亡(${data.cause || "?"})`, 4000);
  });

  window.StSocket.on("revive", (data) => {
    window.StStore.showToast(`${data.name} 被说书人复活了`, 4000);
  });

  window.StSocket.on("game_over", (data) => {
    const w = data.winner === "good" ? "善良阵营 获胜" : data.winner === "evil" ? "邪恶阵营 获胜" : "游戏结束";
    window.StStore.showToast(`${w} · ${data.reason || ""}`, 6000);
  });

  // 被说书人踢出房间 → 清身份 + 跳大厅
  window.StSocket.on("kicked", (data) => {
    if (ss) {
      ss.removeItem("p_player_id");
      ss.removeItem("p_room_code");
      ss.removeItem("p_player_name");
    }
    if (ls && data && data.room_code) {
      try {
        ls.removeItem("p_room_code_" + data.room_code);
        ls.removeItem("p_player_id_" + data.room_code);
        ls.removeItem("p_player_token_" + data.room_code);
      } catch (e) {}
    }
    window.StStore.showToast(`你被说书人踢出了房间:${data && data.reason || "无原因"}`, 2500);
    setTimeout(() => { window.location.href = "/"; }, 800);
  });

  // 房间被说书人关闭 → 清身份 + 跳大厅
  window.StSocket.on("room_closed", (data) => {
    if (ss) {
      ss.removeItem("p_player_id");
      ss.removeItem("p_room_code");
      ss.removeItem("p_player_name");
    }
    if (ls && data && data.room_code) {
      try {
        ls.removeItem("p_room_code_" + data.room_code);
        ls.removeItem("p_player_id_" + data.room_code);
        ls.removeItem("p_player_token_" + data.room_code);
      } catch (e) {}
    }
    window.StStore.showToast(`房间已关闭:${data && data.reason || "说书人关闭了房间"}`, 2500);
    setTimeout(() => { window.location.href = "/"; }, 800);
  });

  // 说书人在游戏结束后重开了游戏 → 提示玩家并清掉旧的私人批注(等新一轮 role_assigned)
  window.StSocket.on("game_reset", (data) => {
    window.StStore.showToast(`游戏已重开 · 第 ${data.day} 天,请等待新身份`, 3500);
    _playerNotes = {};
  });

  if (btnJoin) {
    btnJoin.addEventListener("click", () => {
      const name = (joinName.value || "").trim();
      if (!name) { window.StStore.showToast("请输入你的名字"); return; }
      window.StSocket.emit("join_room", { room_code: roomCode, name });
    });
  }
  if (joinName) {
    joinName.addEventListener("keydown", (e) => {
      if (e.key === "Enter") btnJoin && btnJoin.click();
    });
  }
  if (btnLeave) {
    btnLeave.addEventListener("click", () => {
      window.StSocket.emit("leave_room", { room_code: roomCode });
      if (ss) {
        ss.removeItem("p_player_id");
        ss.removeItem("p_room_code");
        ss.removeItem("p_player_name");
      }
      if (ls) {
        try {
          ls.removeItem("p_room_code_" + roomCode);
          ls.removeItem("p_player_id_" + roomCode);
          ls.removeItem("p_player_token_" + roomCode);
        } catch (e) {}
      }
      setTimeout(() => { window.location.href = "/"; }, 400);
    });
  }

  window.StSocket.on("error", (data) => {
    window.StStore.showToast((data && data.message) || "未知错误");
    if (data && data.code === "ROOM_NOT_FOUND") {
      setTimeout(() => { window.location.href = "/"; }, 1200);
    } else if (data && data.code === "PLAYER_NOT_FOUND") {
      if (ss) {
        ss.removeItem("p_player_id");
        ss.removeItem("p_room_code");
      }
      if (ls) {
        try {
          ls.removeItem("p_room_code_" + roomCode);
          ls.removeItem("p_player_id_" + roomCode);
          ls.removeItem("p_player_token_" + roomCode);
        } catch (e) {}
      }
      showForm();
    }
  });

  if (roomExists && window.StSocket.isConnected()) tryAutoJoin();

  // ---- 玩家私人数据 ----
  let _playerNotes = {};

  // ---- 渲染玩家日志 ----
  function renderPlayerLog(data) {
    const logEl = document.getElementById("player-event-log");
    if (!logEl) return;
    if (data) {
      if (data.player_notes) _playerNotes = data.player_notes;
    }
    const filteredLog = (data && data.filtered_log) || [];
    const privateLog = (data && data.private_log) || [];
    const allEntries = [...filteredLog, ...privateLog].sort((a, b) => (a.ts || 0) - (b.ts || 0));
    if (allEntries.length === 0) {
      logEl.innerHTML = '<p>暂无活动</p>';
      return;
    }
    const reversed = [...allEntries].reverse();
    logEl.innerHTML = reversed.map((entry) => {
      const ts = new Date((entry.ts || 0) * 1000).toLocaleTimeString("zh-CN", { hour12: false });
      const isPrivate = entry.kind === "player_private";
      const kindColor = isPrivate ? "var(--azur-soft)" : ({
        game_start: "var(--gold-deep)", execution: "var(--rouge)",
        nomination_result: "var(--ink)", nomination_failed: "var(--ink-soft)",
        night_start: "var(--azur-soft)", day_start: "var(--azur)",
        game_over: "var(--gold-deep)", nomination_start: "var(--ink)",
        pass: "var(--ink-soft)", st_kill: "var(--rouge)", st_revive: "var(--azur)",
      })[entry.kind] || "var(--ink)";
      const prefix = isPrivate ? "📝 " : "";
      return `<div style="padding: 4px 0; border-bottom: 1px dotted var(--gold); color: ${kindColor};">
        <span style="color: var(--gold-deep); margin-right: 8px; font-family: var(--font-roman);">[${ts}]</span>${prefix}${escapeHtml(entry.text)}
      </div>`;
    }).join("");
  }

  window.StSocket.on("player_state", (data) => {
    if (!data) return;
    renderPlayerLog(data);
    if (lastState) renderList(lastState);
  });

  // ---- 玩家操作模块 ----
  let _pNotesLocal = [];
  let _pNotesEditingIdx = -1;

  function _loadPNotes(targetId) {
    const arr = (_playerNotes && _playerNotes[targetId]) || [];
    return arr.map(function (n) { return { id: n.id, text: n.text }; });
  }

  function _renderPNotesList(targetName) {
    const list = document.getElementById("player-notes-list");
    if (!list) return;
    if (_pNotesLocal.length === 0) {
      list.innerHTML = '<p style="color: var(--ink-soft); font-size: var(--text-sm); padding: var(--space-3); text-align: center;">还没有批注</p>';
      return;
    }
    list.innerHTML = _pNotesLocal.map(function (n, idx) {
      const isEditing = _pNotesEditingIdx === idx;
      let body;
      if (isEditing) {
        body =
          '<input class="input p-note-edit-input" data-idx="' + idx + '" type="text" maxlength="60" value="' +
          escapeHtml(n.text) + '" style="margin-bottom: 6px;">' +
          '<div style="display: flex; gap: 6px;">' +
            '<button class="btn btn--primary btn-p-note-save" data-idx="' + idx + '" style="flex:1; padding: 4px 10px; font-size: var(--text-xs);">保存</button>' +
            '<button class="btn btn--ghost btn-p-note-cancel" data-idx="' + idx + '" style="flex:1; padding: 4px 10px; font-size: var(--text-xs);">取消</button>' +
          '</div>';
      } else {
        body =
          '<div style="display: flex; align-items: center; gap: 6px;">' +
            '<span style="flex:1; padding: 6px 10px; background: var(--ivory); border-radius: var(--radius-sm); border: 1px solid var(--gold); word-break: break-all;">' +
              escapeHtml(n.text) +
            '</span>' +
            '<button class="btn btn--ghost btn-p-note-edit" data-idx="' + idx + '" style="padding: 4px 10px; font-size: var(--text-xs);">编辑</button>' +
            '<button class="btn btn--danger btn-p-note-del" data-idx="' + idx + '" style="padding: 4px 10px; font-size: var(--text-xs);">删除</button>' +
          '</div>';
      }
      return '<div style="padding: 6px 0; border-bottom: 1px dotted var(--gold);">' + body + '</div>';
    }).join("");

    list.querySelectorAll(".btn-p-note-edit").forEach(function (btn) {
      btn.addEventListener("click", function () {
        _pNotesEditingIdx = parseInt(btn.getAttribute("data-idx"), 10);
        _renderPNotesList(targetName);
        const inp = list.querySelector(".p-note-edit-input");
        if (inp) { inp.focus(); inp.select(); }
      });
    });
    list.querySelectorAll(".btn-p-note-del").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const idx = parseInt(btn.getAttribute("data-idx"), 10);
        if (!confirm("删除这条批注?")) return;
        _pNotesLocal.splice(idx, 1);
        _pNotesEditingIdx = -1;
        _renderPNotesList(targetName);
        _syncPNotesToServer();
      });
    });
    list.querySelectorAll(".btn-p-note-cancel").forEach(function (btn) {
      btn.addEventListener("click", function () {
        _pNotesEditingIdx = -1;
        _renderPNotesList(targetName);
      });
    });
    list.querySelectorAll(".btn-p-note-save").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const idx = parseInt(btn.getAttribute("data-idx"), 10);
        const inp = list.querySelector(".p-note-edit-input");
        const text = inp ? inp.value.trim() : "";
        if (!text) { window.StStore.showToast("批注内容不能为空"); return; }
        _pNotesLocal[idx].text = text;
        _pNotesEditingIdx = -1;
        _renderPNotesList(targetName);
        _syncPNotesToServer();
      });
    });
    list.querySelectorAll(".p-note-edit-input").forEach(function (inp) {
      inp.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          e.preventDefault();
          const idx = parseInt(inp.getAttribute("data-idx"), 10);
          const text = inp.value.trim();
          if (!text) return;
          _pNotesLocal[idx].text = text;
          _pNotesEditingIdx = -1;
          _renderPNotesList(targetName);
          _syncPNotesToServer();
        }
      });
    });
  }

  function _syncPNotesToServer() {
    const targetId = window.StPlayerActions._noteTargetId;
    if (!targetId) return;
    const notes = _pNotesLocal.map(function (n) { return { id: n.id, text: n.text }; });
    window.StSocket.emit("player_set_notes", { target_id: targetId, notes: notes });
  }

  function _addPNote() {
    const targetId = window.StPlayerActions._noteTargetId;
    const input = document.getElementById("player-note-input");
    const text = (input && input.value || "").trim();
    if (!targetId) { window.StStore.showToast("未选择目标玩家"); return; }
    if (!text) { window.StStore.showToast("批注内容不能为空"); return; }
    _pNotesLocal.push({ id: "n_" + Date.now() + "_" + Math.random().toString(36).slice(2, 6), text: text });
    if (input) input.value = "";
    _renderPNotesList("");
    _syncPNotesToServer();
  }

  window.StPlayerActions = {
    _noteTargetId: null,
    openNoteEditor: function (targetId) {
      this._noteTargetId = targetId;
      _pNotesLocal = _loadPNotes(targetId);
      _pNotesEditingIdx = -1;
      const input = document.getElementById("player-note-input");
      if (input) input.value = "";
      // 找到目标玩家名字
      const target = (lastState && lastState.players || []).find(function (p) { return p.id === targetId; });
      const targetNameEl = document.getElementById("player-note-target-name");
      if (targetNameEl) targetNameEl.textContent = target ? target.name : "?";
      document.getElementById("player-note-modal").classList.add("is-open");
      _renderPNotesList(target ? target.name : "");
      setTimeout(function () { if (input) input.focus(); }, 100);
    },
    addPNote: _addPNote,
  };

  // ---- 批注编辑器 ----
  const btnClosePlayerNote = document.getElementById("btn-close-player-note");
  if (btnClosePlayerNote) {
    btnClosePlayerNote.addEventListener("click", () => {
      document.getElementById("player-note-modal").classList.remove("is-open");
    });
  }
  const playerNoteModal = document.getElementById("player-note-modal");
  if (playerNoteModal) {
    playerNoteModal.addEventListener("click", function (e) {
      if (e.target === this) this.classList.remove("is-open");
    });
  }
  const btnAddPlayerNote = document.getElementById("btn-add-player-note");
  if (btnAddPlayerNote) {
    btnAddPlayerNote.addEventListener("click", () => {
      window.StPlayerActions.addPNote();
    });
  }
  const playerNoteInput = document.getElementById("player-note-input");
  if (playerNoteInput) {
    playerNoteInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") btnAddPlayerNote && btnAddPlayerNote.click();
    });
  }

  // ---- 快速日志 ----
  const playerLogInput = document.getElementById("player-log-input");
  const btnPlayerAddLog = document.getElementById("btn-player-add-log");
  if (btnPlayerAddLog && playerLogInput) {
    btnPlayerAddLog.addEventListener("click", () => {
      const text = (playerLogInput.value || "").trim();
      if (!text) { window.StStore.showToast("请输入日志内容"); return; }
      window.StSocket.emit("player_add_log", { text: text });
      playerLogInput.value = "";
    });
    playerLogInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") btnPlayerAddLog.click();
    });
  }

  // ---- 发送给说书人 ----
  const btnSendSt = document.getElementById("btn-player-send-st");
  const sendStModal = document.getElementById("player-send-st-modal");
  const sendStText = document.getElementById("player-send-st-text");
  const btnCloseSendSt = document.getElementById("btn-close-send-st");
  const btnSubmitSendSt = document.getElementById("btn-player-send-st-submit");
  const btnCancelSendSt = document.getElementById("btn-player-send-st-cancel");

  function openSendStModal() {
    if (!sendStModal) return;
    if (sendStText) sendStText.value = "";
    sendStModal.classList.add("is-open");
    setTimeout(() => { if (sendStText) sendStText.focus(); }, 80);
  }
  function closeSendStModal() {
    if (sendStModal) sendStModal.classList.remove("is-open");
  }

  if (btnSendSt) {
    btnSendSt.addEventListener("click", openSendStModal);
  }
  if (btnCloseSendSt) {
    btnCloseSendSt.addEventListener("click", closeSendStModal);
  }
  if (sendStModal) {
    sendStModal.addEventListener("click", (e) => {
      if (e.target === sendStModal) closeSendStModal();
    });
  }
  if (btnCancelSendSt) {
    btnCancelSendSt.addEventListener("click", closeSendStModal);
  }
  if (btnSubmitSendSt) {
    btnSubmitSendSt.addEventListener("click", () => {
      const text = (sendStText && sendStText.value || "").trim();
      if (!text) { window.StStore.showToast("请输入消息内容"); return; }
      window.StSocket.emit("player_send_to_st", { text: text });
      window.StStore.showToast("已发送给说书人", 2000);
      closeSendStModal();
    });
  }
  if (sendStText) {
    sendStText.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        btnSubmitSendSt && btnSubmitSendSt.click();
      }
    });
  }
})();
