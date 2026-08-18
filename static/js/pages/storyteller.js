/* =========================================================
   storyteller.js — Storyteller console (Stage 1.5)
   - Multi-nomination per day phase
   - ST manually clicks "结束提名阶段 · 结算" to resolve
   ========================================================= */

(function () {
  const $ = (sel) => document.querySelector(sel);

  const connPill = $("#conn-pill");
  const phaseLabel = $("#phase-label");
  const dayNightLabel = $("#day-night-label");
  const playerCountLabel = $("#player-count-label");
  const stPlayerList = $("#st-player-list");

  const btnStartGame = $("#btn-start-game");
  const btnEndDay = $("#btn-end-day");
  const btnBeginDay = $("#btn-begin-day");
  const btnBeginNom = $("#btn-begin-nomination");
  const btnEndNom = $("#btn-end-nomination");
  const btnEndGame = $("#btn-end-game");
  const btnRestartGame = $("#btn-restart-game");
  const btnCloseRoom = $("#btn-close-room");
  const btnSetTimer = $("#btn-set-timer");

  const scriptBar = $("#script-bar");
  const scriptStatus = $("#script-status");
  const btnManageScripts = $("#btn-manage-scripts");
  const scriptModal = $("#script-modal");
  const btnCloseScriptModal = $("#btn-close-script-modal");
  const scriptEditId = $("#script-edit-id");
  const scriptEditName = $("#script-edit-name");
  const scriptEditNotes = $("#script-edit-notes");
  const scriptRolesTbody = $("#script-roles-tbody");
  const btnScriptAddRole = $("#btn-script-add-role");
  const btnScriptImport = $("#btn-script-import");
  const btnScriptExport = $("#btn-script-export");
  const btnScriptClear = $("#btn-script-clear");
  const scriptImportArea = $("#script-import-area");
  const scriptImportInput = $("#script-import-input");
  const btnScriptImportApply = $("#btn-script-import-apply");
  const btnScriptImportCancel = $("#btn-script-import-cancel");
  const scriptExportArea = $("#script-export-area");
  const scriptExportOutput = $("#script-export-output");
  const btnScriptExportCopy = $("#btn-script-export-copy");
  const btnScriptExportClose = $("#btn-script-export-close");
  const btnScriptApply = $("#btn-script-apply");
  const btnScriptClose = $("#btn-script-close");

  const nightOrderCard = $("#night-order-card");
  const nightOrderTitle = $("#night-order-title");
  const nightOrderList = $("#night-order-list");
  const nightOrderEmpty = $("#night-order-empty");

  const dayActionCard = $("#day-action-card");
  const dayActionList = $("#day-action-list");
  const dayActionEmpty = $("#day-action-empty");
  const roleNotesCard = $("#role-notes-card");
  const roleNotesList = $("#role-notes-list");
  const roleNotesEmpty = $("#role-notes-empty");
  const demonDisguisesCard = $("#demon-disguises-card");
  const demonDisguisesCount = $("#demon-disguises-count");
  const demonDisguisesList = $("#demon-disguises-list");
  const demonDisguisesEmpty = $("#demon-disguises-empty");
  const fabledCard = $("#fabled-card");
  const fabledList = $("#fabled-list");
  const fabledEmpty = $("#fabled-empty");
  const fabledNoScript = $("#fabled-no-script");

  const timerRow = $("#timer-row");
  const timerDisplay = $("#timer-display");

  const nominationsCard = $("#nominations-card");
  const nominationsCount = $("#nominations-count");
  const nominationsContent = $("#nominations-content");
  const announcementCard = $("#announcement-card");
  const announcementText = $("#announcement-text");
  const winnerBanner = $("#winner-banner");
  const winnerText = $("#winner-text");
  const eventLog = $("#event-log");

  const roomCode = window.ROOM_CODE;

  let ss, ls;
  try { ss = sessionStorage; } catch (e) { ss = null; }
  try { ls = localStorage; } catch (e) { ls = null; }
  // 按房间分键存 ST 的 room_code + player_id:关浏览器/跨 tab 重开同 URL 时能直接走 reconnect_room,
  // 不至于出现「路由放行 → 但 socket 没连 → 显示空房间」的情况。
  // 同时也保留 sessionStorage 备份(同 tab 内快速读取)。
  const stRoomKey = "st_room_code_" + (roomCode || "");
  const stPidKey  = "st_player_id_"  + (roomCode || "");
  const savedRoom = (ls && ls.getItem(stRoomKey)) || (ss && ss.getItem("st_room_code")) || "";
  const savedPid  = (ls && ls.getItem(stPidKey))  || (ss && ss.getItem("st_player_id"))  || "";
  // ST 令牌:URL ?t= 优先,再 fallback 到 localStorage(同浏览器任意 tab/重启都还在)。
  // 注意:用 localStorage 而不是 sessionStorage,否则关 tab 再开新 tab 就丢了,
  // ST 需要翻历史记录找带 ?t= 的 URL,体验很差。
  // 跨浏览器/跨设备仍然需要带 ?t= 的完整 URL(token 不共享)。
  const urlToken = new URLSearchParams(window.location.search).get("t") || "";
  const savedToken = ls && ls.getItem("st_token");
  const stToken = urlToken || savedToken || "";
  if (urlToken && ls) {
    try { ls.setItem("st_token", urlToken); } catch (e) {}
  }
  let lastState = null;

  // ---- 日志 ----
  function logEvent(text) {
    if (!eventLog) return;
    if (eventLog.querySelector("p")) eventLog.innerHTML = "";
    const ts = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    const line = document.createElement("div");
    line.style.padding = "4px 0";
    line.style.borderBottom = "1px dotted var(--gold)";
    line.innerHTML = `<span style="color: var(--gold-deep); margin-right: 8px;">[${ts}]</span>${escapeHtml(text)}`;
    eventLog.prepend(line);
  }

  function renderLog(log) {
    if (!eventLog) return;
    if (!log || log.length === 0) {
      eventLog.innerHTML = '<p>暂无活动</p>';
      return;
    }
    const reversed = [...log].reverse();
    eventLog.innerHTML = reversed.map((entry) => {
      const ts = new Date(entry.ts * 1000).toLocaleTimeString("zh-CN", { hour12: false });
      const kindColor = ({
        game_start: "var(--gold-deep)",
        execution: "var(--rouge)",
        nomination_failed: "var(--ink-soft)",
        night_start: "var(--azur-soft)",
        day_start: "var(--azur)",
        game_over: "var(--gold-deep)",
        nomination_start: "var(--ink)",
        pass: "var(--ink-soft)",
      })[entry.kind] || "var(--ink)";
      return `<div style="padding: 4px 0; border-bottom: 1px dotted var(--gold); color: ${kindColor};">
        <span style="color: var(--gold-deep); margin-right: 8px; font-family: var(--font-roman);">[${ts}]</span>${escapeHtml(entry.text)}
      </div>`;
    }).join("");
  }

  // ---- 工具 ----
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }
  function phaseLabelText(phase) {
    return {
      lobby: "大厅", setup: "准备", first_night: "首夜",
      day: "白天", nomination: "提名", voting: "投票",
      execution: "处决", night: "夜晚", ended: "结束",
    }[phase] || phase;
  }
  function phaseEmblemClass(phase) {
    return {
      lobby: "emblem--fabled", first_night: "emblem--demon",
      day: "emblem--townsfolk", nomination: "emblem--townsfolk",
      voting: "emblem--townsfolk", execution: "emblem--minion",
      night: "emblem--demon", ended: "emblem--fabled",
    }[phase] || "emblem--fabled";
  }
  function _roleNameOf(role) {
    if (!role) return "";
    if (!lastState || !lastState.script) return role;
    const def = (lastState.script.roles || []).find(function (r) { return r.id === role; });
    return def ? (def.name || def.id) : role;
  }

  function _roleTeamOf(role) {
    if (!lastState || !lastState.script) return "fabled";
    const def = (lastState.script.roles || []).find(function (r) { return r.id === role; });
    return def ? def.team : "fabled";
  }

  function _roleTeamClassLocal(role) {
    const t = _roleTeamOf(role);
    return {
      townsfolk: "emblem--townsfolk",
      outsider:  "emblem--outsider",
      minion:    "emblem--minion",
      demon:     "emblem--demon",
    }[t] || "emblem--fabled";
  }

  function _activeRoleIds() {
    if (!lastState || !lastState.players || !lastState.script) return new Set();
    const ids = new Set();
    for (const p of lastState.players) {
      if (p.is_storyteller) continue;
      // 用 apparent_role(假身份)以包含酒鬼等被 replace 的角色假身份;
      // 没有 apparent_role 时回退到 true_role。
      const displayRole = p.apparent_role || p.true_role;
      if (displayRole) ids.add(displayRole);
    }
    return ids;
  }

  // 向后兼容旧代码:用 script 查表
  function roleDisplayName(role) { return _roleNameOf(role) || role; }
  function roleTeamClass(role) { return _roleTeamClassLocal(role); }

  // ---- 玩家渲染 ----
  // ST 选中的待交换玩家 ID(用于点选交换)
  let _stSwapSelected = null;
  function renderStList(players) {
    if (!stPlayerList) return;
    if (playerCountLabel) playerCountLabel.textContent = `${players.length} 人`;
    if (players.length === 0) {
      stPlayerList.innerHTML = '<p style="color: var(--ink-soft);">等待玩家加入...</p>';
      return;
    }
    // 仅 lobby / ended 阶段显示"换"图标 + 点选交换
    const showSwap = lastState && (lastState.phase === "lobby" || lastState.phase === "ended");
    const pendingSwap = lastState && lastState.pending_swap;
    // pending_swap 涉及的玩家退出/被踢 → 清掉选中
    if (_stSwapSelected && !players.some((p) => p.id === _stSwapSelected)) {
      _stSwapSelected = null;
    }
    stPlayerList.innerHTML = players.map((p) => {
      const seat = p.seat;
      const isST = p.is_storyteller;
      // 交换图标:仅 lobby + 非 ST
      const inSwap = pendingSwap && (pendingSwap.from_id === p.id || pendingSwap.to_id === p.id);
      const swapSelected = _stSwapSelected === p.id;
      const swapBtn = (showSwap && !isST)
        ? `<button class="player-swap-btn ${swapSelected ? 'is-selected' : ''}" data-swap-target="${p.id}" title="点选交换:第一个点高亮,第二个点确认">⇄</button>`
        : "";
      const swapExtraClass = swapSelected ? 'is-swap-selected' : (inSwap ? 'is-in-swap' : '');
      const roleBadge = p.true_role
        ? `<span class="emblem ${roleTeamClass(p.apparent_role || p.true_role)}" style="margin-top:6px;">${roleDisplayName(p.apparent_role || p.true_role)}</span>`
        : "";
      // 真实身份 vs 显示身份不同时(被 replace_with 替换),ST 备注
      const actualNote = p.is_replaced && p.true_role
        ? `<div style="margin-top:4px; font-size: var(--text-xs); color: var(--rouge); letter-spacing: 0.05em;">实际为 · ${escapeHtml(roleDisplayName(p.true_role))}</div>`
        : "";
      // 角色备注(ScriptRole.notes):只在说书人界面可见,普通角色(T/O/M/D)的备注
      // 按"玩家眼前的身份"取(apparent_role,与徽章一致);fabled 永不分配给玩家,天然不会进入这里。
      const apparentRole = p.apparent_role || p.true_role;
      const roleDef = (apparentRole && lastState && lastState.script && Array.isArray(lastState.script.roles))
        ? lastState.script.roles.find(function (r) { return r.id === apparentRole; })
        : null;
      const roleNoteHtml = (roleDef && roleDef.notes && roleDef.notes.trim())
        ? `<div class="st-tag--role-note" title="角色备注(仅 ST 可见)">${escapeHtml(roleDef.notes.trim())}</div>`
        : "";
      const statusText = isST ? "说书人" : (p.status === "alive" ? "存活" : (p.status === "dead" ? "已死亡" : "鬼魂"));
      const poisonedMark = p.is_poisoned ? `<span class="st-tag st-tag--poisoned">☠ 中毒</span>` : "";
      const drunkMark = p.is_drunk ? `<span class="st-tag st-tag--drunk">🍷 醉酒</span>` : "";
      const noteList = p.st_notes || [];
      const noteMarks = noteList.map(function (n) {
        return `<span class="st-tag st-tag--note" title="${escapeHtml(n.text)}">${escapeHtml(n.text)}</span>`;
      }).join("");
      const offlineMark = p.connected === false ? `<span style="color: var(--ink-soft); font-size: var(--text-xs);">· 离线</span>` : "";
      const hasAnnotations = p.is_poisoned || p.is_drunk || noteList.length > 0;
      const menuBtn = !isST ? `
        <div class="player-menu-wrap">
          <button class="player-menu-btn" onclick="event.stopPropagation(); window.StStorytellerActions.openMenu('${p.id}', event)" title="操作">⋮</button>
          <div class="player-menu-dropdown" id="menu-${p.id}">
            <button onclick="window.StStorytellerActions.stKill('${p.id}')">✝ 杀死</button>
            <button onclick="window.StStorytellerActions.stRevive('${p.id}')">✦ 复活</button>
            <div class="player-menu-divider"></div>
            <button onclick="window.StStorytellerActions.stSetDrunk('${p.id}', true)">🍷 设为醉酒</button>
            <button onclick="window.StStorytellerActions.stSetDrunk('${p.id}', false)">🍷 解除醉酒</button>
            <div class="player-menu-divider"></div>
            <button onclick="window.StStorytellerActions.stSetPoisoned('${p.id}', true)">☠ 设为中毒</button>
            <button onclick="window.StStorytellerActions.stSetPoisoned('${p.id}', false)">☠ 解除中毒</button>
            <div class="player-menu-divider"></div>
            <button onclick="window.StStorytellerActions.stClearStatus('${p.id}')">🔄 清除异常状态</button>
            <div class="player-menu-divider"></div>
            <button onclick="window.StStorytellerActions.showRolePicker('${p.id}')">🃏 变更身份</button>
            <button onclick="window.StStorytellerActions.showNoteEditor('${p.id}')">📝 编辑批注</button>
            <div class="player-menu-divider"></div>
            <button class="danger" onclick="window.StStorytellerActions.stKick('${p.id}')">🚪 踢出房间</button>
          </div>
        </div>` : "";
      return `
        <div class="player-tile ${isST ? "player-tile--storyteller" : ""} ${p.status === 'dead' ? 'is-dead' : ''} ${swapExtraClass}" style="${p.status === 'dead' ? 'opacity: 0.5;' : ''} position: relative;">
          ${menuBtn}
          ${swapBtn}
          <span class="player-tile__seat">No.${String(seat).padStart(2, "0")}</span>
          <div class="player-tile__name">${escapeHtml(p.name)}</div>
          <div class="player-tile__status">${statusText}</div>
          ${roleBadge}
          ${actualNote}
          ${roleNoteHtml}
          <div style="margin-top: 6px;">${offlineMark}</div>
          ${hasAnnotations ? `<div class="st-annotations">${drunkMark}${poisonedMark}${noteMarks}</div>` : ""}
        </div>
      `;
    }).join("");

    // 绑定 swap 按钮:点选交换
    stPlayerList.querySelectorAll(".player-swap-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const targetId = btn.getAttribute("data-swap-target");
        if (_stSwapSelected === null) {
          // 第一个点:选中
          _stSwapSelected = targetId;
          renderStList(players); // 重渲染以更新高亮
        } else if (_stSwapSelected === targetId) {
          // 点同一个:取消选中
          _stSwapSelected = null;
          renderStList(players);
        } else {
          // 第二个点:确认交换
          const a = _stSwapSelected;
          const b = targetId;
          _stSwapSelected = null;
          window.StSocket.emit("st_swap_players", { a_id: a, b_id: b });
        }
      });
    });
  }

  // ---- 阶段控制条 ----
  function renderPhase(state) {
    if (!state) return;
    const phase = state.phase;
    if (phaseLabel) {
      phaseLabel.textContent = phaseLabelText(phase);
      phaseLabel.className = "emblem " + phaseEmblemClass(phase);
    }
    if (dayNightLabel) {
      if (phase === "lobby") dayNightLabel.textContent = "未开始";
      else if (phase === "first_night") dayNightLabel.textContent = "首夜";
      else if (phase === "night") dayNightLabel.textContent = `第 ${state.night} 夜`;
      else if (phase === "day_discussion") dayNightLabel.textContent = `第 ${state.day} 天 · 讨论`;
      else if (phase === "ended") dayNightLabel.textContent = "已结束";
      else dayNightLabel.textContent = `第 ${state.day} 天 · 提名`;
    }

    if (btnStartGame) btnStartGame.style.display = (phase === "lobby") ? "" : "none";
    if (btnEndDay) btnEndDay.style.display = (phase === "day_discussion" || phase === "day") ? "" : "none";
    if (btnBeginDay) btnBeginDay.style.display = (phase === "night" || phase === "first_night") ? "" : "none";
    // 开放提名按钮:DAY_DISCUSSION 阶段显示(让 ST 切换到提名阶段)
    if (btnBeginNom) btnBeginNom.style.display = (phase === "day_discussion") ? "" : "none";
    // 结束提名按钮:DAY 阶段且有进行中的提名(未结算)
    const hasOpenNom = (state.current_nominations || []).some((n) => !n.resolved);
    if (btnEndNom) btnEndNom.style.display = (phase === "day" && hasOpenNom) ? "" : "none";
    if (btnEndGame) btnEndGame.style.display = (phase !== "ended") ? "" : "none";
    if (btnRestartGame) btnRestartGame.style.display = (phase === "ended") ? "" : "none";
    if (btnCloseRoom) btnCloseRoom.style.display = ""; // 关闭房间按钮始终可用
    if (scriptBar) scriptBar.style.display = (phase === "lobby") ? "flex" : "none";
    // 白天需注意角色侧栏:仅在白天提名阶段显示
    if (dayActionCard) {
      const showDay = (phase === "day_discussion" || phase === "day");
      dayActionCard.style.display = showDay ? "" : "none";
      if (showDay) _renderDayAction();
    }
    // 夜晚顺序侧栏:仅在夜间阶段显示
    if (nightOrderCard) {
      const showNight = (phase === "night" || phase === "first_night");
      nightOrderCard.style.display = showNight ? "" : "none";
      if (showNight) _renderNightOrder(phase);
    }
    // 在场角色备注:白天/夜晚/已结束阶段都可显示
    if (phase === "day_discussion" || phase === "day" || phase === "night" || phase === "first_night" || phase === "ended") {
      _renderRoleNotes();
      _renderDemonDisguises();
    } else {
      // lobby/setup 阶段隐藏
      if (roleNotesCard) roleNotesCard.style.display = "none";
      if (demonDisguisesCard) demonDisguisesCard.style.display = "none";
    }
    // 传奇角色控制:任何阶段都能切换(说书人可以提前布置),只要 script 存在就显示
    _renderFabledList();

    if (timerRow) {
      // 计时器只在白天讨论阶段显示(进入提名阶段后投票有自己的进度条)
      const showTimer = (phase === "day_discussion") && state.chat_started_at;
      timerRow.style.display = showTimer ? "flex" : "none";
    }

    if (winnerBanner) {
      if (phase === "ended" && state.winner) {
        winnerBanner.style.display = "flex";
        const w = state.winner === "good" ? "善良阵营 获胜" : state.winner === "evil" ? "邪恶阵营 获胜" : "游戏结束";
        winnerText.textContent = `${w} · ${state.win_reason || ""}`;
      } else {
        winnerBanner.style.display = "none";
      }
    }

    renderNominations(state);
  }

  function renderNominations(state) {
    if (!nominationsCard || !nominationsContent) return;
    const noms = state.current_nominations || [];
    if (noms.length === 0 && state.phase !== "day") {
      nominationsCard.style.display = "none";
      return;
    }
    nominationsCard.style.display = "block";
    const openCount = noms.filter((n) => !n.resolved).length;
    nominationsCount.textContent = openCount > 0 ? `进行中 ${openCount} · 共 ${noms.length}` : `共 ${noms.length} (已结算)`;

    const findName = (id) => {
      const p = (state.players || []).find((x) => x.id === id);
      return p ? p.name : "?";
    };

    const aliveCount = (state.players || []).filter((p) => p.status === "alive").length;
    const threshold = aliveCount / 2;

    nominationsContent.innerHTML = noms.map((nom) => {
      const nominator = findName(nom.nominator_id);
      const nominee = findName(nom.nominee_id);
      const yesCount = nom.yes_count || nom.votes.filter((v) => v.value).length;
      const noCount = nom.no_count || nom.votes.filter((v) => !v.value).length;
      let status;
      if (!nom.resolved) {
        status = `<span class="emblem emblem--fabled" style="font-size: var(--text-xs);">进行中</span>`;
      } else if (nom.executed) {
        status = `<span class="emblem emblem--demon" style="font-size: var(--text-xs);">已处决</span>`;
      } else if (nom.met_threshold) {
        status = `<span class="emblem" style="background: var(--azur); color: var(--ivory); font-size: var(--text-xs);">达门槛 · 未中选</span>`;
      } else {
        status = `<span class="emblem emblem--townsfolk" style="font-size: var(--text-xs);">未达门槛</span>`;
      }
      return `
        <div style="padding: var(--space-3); border: 1px solid var(--gold); border-radius: var(--radius-sm); margin-bottom: var(--space-2); background: var(--ivory);">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
            <span><strong>${escapeHtml(nominator)}</strong> <span style="color: var(--ink-soft);">提名</span> <strong>${escapeHtml(nominee)}</strong></span>
            ${status}
          </div>
          <div style="font-size: var(--text-sm); color: var(--ink-soft);">
            赞成 <span style="color: var(--azur); font-weight: 700;">${yesCount}</span> ·
            反对 <span style="color: var(--rouge); font-weight: 700;">${noCount}</span> ·
            门槛 <span style="color: var(--gold-deep);">${threshold}</span>
            ${nom.reason ? ` · <span style="color: var(--ink-soft);">${escapeHtml(nom.reason)}</span>` : ""}
          </div>
        </div>
      `;
    }).join("") || '<p style="color: var(--ink-soft);">本阶段还没有提名</p>';

    // 提示信息
    const passedNoms = (state.passed_in_phase || []);
    const nominatedAsTarget = (state.nominated_as_target || []);
    const allAlive = (state.players || []).filter((p) => p.status === "alive").length;
    if (noms.length === 0) {
      nominationsContent.innerHTML += `<p style="color: var(--ink-soft); font-size: var(--text-sm); margin-top: var(--space-3);">
        等待玩家提名,或点击「结束白天」跳过本阶段。
      </p>`;
    } else {
      nominationsContent.innerHTML += `<p style="color: var(--ink-soft); font-size: var(--text-sm); margin-top: var(--space-3);">
        ${noms.length} 个有效提名 · 门槛为 ${allAlive}/2 = ${threshold} 票赞成 · 结算时取达到门槛的提名中 yes 最多者处决(平局先提名的赢)
      </p>`;
    }
  }

  // ---- 计时器 ----
  let timerInterval = null;
  function startTicker(state) {
    if (timerInterval) clearInterval(timerInterval);
    // 计时器只在白天讨论阶段运行(进入提名后投票有自己的进度条)
    if (state.phase !== "day_discussion" || !state.chat_started_at) return;
    timerInterval = setInterval(() => {
      if (!lastState || lastState.phase !== "day_discussion" || !lastState.chat_started_at) {
        clearInterval(timerInterval);
        timerInterval = null;
        return;
      }
      const elapsed = (Date.now() / 1000) - lastState.chat_started_at;
      const remaining = Math.max(0, lastState.chat_duration_sec - elapsed);
      if (timerDisplay) {
        const m = Math.floor(remaining / 60);
        const s = Math.floor(remaining % 60);
        timerDisplay.textContent = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
        timerDisplay.style.color = remaining < 30 ? "var(--rouge)" : "var(--ink)";
      }
    }, 1000);
  }

  // ---- 事件 ----
  window.StSocket.on("__connection_change", (data) => {
    if (!connPill) return;
    if (data.connected) {
      connPill.textContent = "已连接";
      connPill.classList.remove("connection-pill--offline");
      if (roomCode && savedRoom === roomCode && savedPid) {
        window.StSocket.emit("reconnect_room", { room_code: roomCode, player_id: savedPid, st_token: stToken });
      }
    } else {
      connPill.textContent = "已断开 · 重连中";
      connPill.classList.add("connection-pill--offline");
    }
  });
  if (connPill && window.StSocket.isConnected()) {
    connPill.textContent = "已连接";
    if (roomCode && savedRoom === roomCode && savedPid) {
      window.StSocket.emit("reconnect_room", { room_code: roomCode, player_id: savedPid, st_token: stToken });
    }
    // 拉取板子列表(填充下拉与 modal)
    window.StSocket.emit("list_scripts", {});
  }

  window.StSocket.on("room_created", (data) => {
    if (!data || !data.is_storyteller) return;
    if (ss) {
      ss.setItem("st_player_id", data.player_id);
      ss.setItem("st_room_code", data.room_code);
      if (data.st_token) ss.setItem("st_token", data.st_token);
    }
    // 同时按房间分键存到 localStorage,关浏览器/跨 tab 后还在,便于 reconnect_room 走通
    if (data.room_code && data.player_id && ls) {
      try { ls.setItem("st_room_code_" + data.room_code, data.room_code); } catch (e) {}
      try { ls.setItem("st_player_id_"  + data.room_code, data.player_id);  } catch (e) {}
    }
    if (data.reconnected) window.StStore.showToast("已重新连入房间");
  });

  window.StSocket.on("st_state_update", (data) => {
    lastState = data;
    if (data.players) renderStList(data.players);
    if (data.log) renderLog(data.log);
    renderPhase(data);
    startTicker(data);
    // 更新板子状态显示
    if (scriptStatus) {
      if (data.script) {
        const roleCount = (data.script.roles || []).length;
        scriptStatus.textContent = data.script.name
          ? `${data.script.name}(${roleCount} 角色)`
          : `${roleCount} 角色`;
        scriptStatus.style.color = "var(--ink)";
      } else {
        scriptStatus.textContent = "尚未录入";
        scriptStatus.style.color = "var(--rouge)";
      }
    }
  });

  window.StSocket.on("st_player_list", (data) => {
    if (data && data.players) renderStList(data.players);
  });
  window.StSocket.on("player_list", (data) => {
    if (data && data.players) renderStList(data.players);
  });

  window.StSocket.on("public_announcement", (data) => {
    if (!announcementCard || !announcementText) return;
    announcementText.textContent = data.text || "";
    announcementCard.style.display = "flex";
    logEvent(data.text || "");
    setTimeout(() => { announcementCard.style.display = "none"; }, 5000);
  });

  window.StSocket.on("execution", (data) => {
    logEvent(`处决 ${data.name} (${data.true_role || "?"}) · ${data.reason || ""}`);
  });

  window.StSocket.on("game_over", (data) => {
    const w = data.winner === "good" ? "善良阵营 获胜" : data.winner === "evil" ? "邪恶阵营 获胜" : "游戏结束";
    window.StStore.showToast(`${w} · ${data.reason || ""}`, 6000);
    logEvent(`[GAME OVER] ${w} · ${data.reason || ""}`);
  });

  window.StSocket.on("game_reset", (data) => {
    window.StStore.showToast(`游戏已重开 · 第 ${data.day} 天`, 4000);
    logEvent(`[RESTART] 游戏已重开,身份已重新分发`);
  });

  // 房间被关闭(说书人或玩家都会收到此事件)
  function _redirectToLobby(reason) {
    // 保留房间号到 ss,大厅页可提示「最近房间」;跳转后由用户手动清除或重连时被覆盖
    if (ss && roomCode) {
      try { ss.setItem("st_last_room_code", roomCode); } catch (e) {}
    }
    if (ss) { ss.removeItem("st_player_id"); ss.removeItem("st_room_code"); }
    // 同步清掉按房间分键的 localStorage,避免下次拿到同名房间的 stale id
    if (ls && roomCode) {
      try { ls.removeItem("st_room_code_" + roomCode); } catch (e) {}
      try { ls.removeItem("st_player_id_"  + roomCode); } catch (e) {}
    }
    window.StStore.showToast(reason || "房间已关闭", 2500);
    // 略延迟让 toast 可见
    setTimeout(() => { window.location.href = "/st/"; }, 800);
  }
  window.StSocket.on("room_closed", (data) => {
    _redirectToLobby(`房间 ${data && data.room_code || ""} 已关闭:${data && data.reason || ""}`);
  });
  // 说书人触发 close_room 后,服务端额外回执(也走相同跳转)
  window.StSocket.on("room_closed_ack", (data) => {
    _redirectToLobby(`房间已关闭:${data && data.reason || ""}`);
  });

  // ---- 按钮 ----
  if (btnStartGame) btnStartGame.addEventListener("click", () => {
    if (!confirm("确认开始游戏?身份将随机分发。")) return;
    window.StSocket.emit("start_game", {});
  });
  if (btnEndDay) btnEndDay.addEventListener("click", () => {
    if (!confirm("确认结束白天?将进入夜晚。")) return;
    window.StSocket.emit("end_day", {});
  });
  if (btnBeginDay) btnBeginDay.addEventListener("click", () => {
    window.StSocket.emit("begin_day", {});
  });
  if (btnBeginNom) btnBeginNom.addEventListener("click", () => {
    if (!confirm("开放提名?玩家可以开始提名和投票。")) return;
    window.StSocket.emit("st_begin_nomination", {});
  });
  if (btnEndNom) btnEndNom.addEventListener("click", () => {
    if (!confirm("确认结束提名阶段并结算?此操作不可撤销。")) return;
    window.StSocket.emit("end_nomination_phase", {});
  });
  if (btnEndGame) btnEndGame.addEventListener("click", () => {
    if (!confirm("确认强制结束游戏?")) return;
    window.StSocket.emit("end_game", { reason: "说书人手动结束" });
  });
  if (btnRestartGame) btnRestartGame.addEventListener("click", () => {
    const aliveCount = (lastState && lastState.players || []).filter((p) => p.status === "alive" && !p.is_storyteller).length;
    const reasonText = aliveCount < 5
      ? `存活玩家不足 5 人(${aliveCount}),重开将保留所有人但会重新分配角色。`
      : "将保留所有玩家,重新分配角色。";
    if (!confirm(`确认重新开始游戏?\n${reasonText}\n(投票记录、批注、私人日志将清空)`)) return;
    window.StSocket.emit("reset_game", {});
  });
  if (btnCloseRoom) btnCloseRoom.addEventListener("click", () => {
    if (!confirm("确认关闭房间?\n所有玩家将被踢出,房间将销毁(此操作不可撤销)。")) return;
    window.StSocket.emit("close_room", { reason: "说书人关闭了房间" });
  });
  if (btnSetTimer) btnSetTimer.addEventListener("click", () => {
    const cur = lastState ? lastState.chat_duration_sec : 300;
    const input = prompt("聊天时长(秒,30-1800):", String(cur));
    if (!input) return;
    const n = parseInt(input, 10);
    if (isNaN(n) || n < 30 || n > 1800) {
      window.StStore.showToast("请输入 30-1800 之间的整数");
      return;
    }
    window.StSocket.emit("set_timer", { seconds: n });
  });

  window.StSocket.on("error", (data) => {
    window.StStore.showToast((data && data.message) || "未知错误");
    if (data && data.code === "ROOM_NOT_FOUND") {
      if (ss) { ss.removeItem("st_player_id"); ss.removeItem("st_room_code"); }
      setTimeout(() => { window.location.href = "/st/"; }, 1500);
    } else if (data && data.code === "PLAYER_NOT_FOUND") {
      if (ss) { ss.removeItem("st_player_id"); ss.removeItem("st_room_code"); }
      window.StStore.showToast("说书人身份已失效,请重新创建房间");
    }
  });

  // ---- 说书人操作模块 ----
  // 注:role picker 不再用写死列表,改为从 lastState.script.roles 动态读取
  // (老逻辑是写死的 ROLE_LIST,导致选了脚本里没有的角色后,玩家角色显示成 ID)
  window.StStorytellerActions = (function () {
    let _rolePickerPlayerId = null;

    function openMenu(playerId, event) {
      // 关闭其他已打开的菜单(如果存在)
      document.querySelectorAll(".player-menu-dropdown.is-open").forEach(function (el) {
        el.classList.remove("is-open");
        // 移回原 wrap
        if (el.dataset && el.dataset.originalParent) {
          var orig = document.getElementById(el.dataset.originalParent);
          if (orig) orig.appendChild(el);
        }
      });
      document.querySelectorAll(".player-menu-wrap.is-open").forEach(function (el) {
        el.classList.remove("is-open");
      });

      var menu = document.getElementById("menu-" + playerId);
      var wrap = menu && menu.parentElement;
      if (menu && wrap) {
        var willOpen = !menu.classList.contains("is-open");
        if (willOpen) {
          // === Portal 化:把 dropdown 移到 body 下,脱离 grid/tile 上下文 ===
          // 这样:
          //  1) state_update 重渲染 tile 时,dropdown 不会跟着被销毁
          //  2) 不受 grid / position:relative 父级的层叠陷阱
          //  3) z-index 在 document 顶级生效
          if (menu.parentElement !== document.body) {
            menu.dataset.originalParent = wrap.id || ("wrap-" + playerId);
            if (!wrap.id) wrap.id = "wrap-" + playerId;
            document.body.appendChild(menu);
          }
          // === 用 fixed 定位 + JS 算按钮位置 ===
          var btn = wrap.querySelector(".player-menu-btn");
          if (btn) {
            var rect = btn.getBoundingClientRect();
            // 临时显示以测真实高度(menu 默认 display:none,getBoundingClientRect 拿不到高)
            var prevDisplay = menu.style.display;
            menu.style.display = "block";
            var menuHeight = menu.offsetHeight;
            var menuWidth = menu.offsetWidth;
            menu.style.display = prevDisplay || "";  // 恢复
            // 默认右对齐到按钮右边
            var left = rect.right - menuWidth;
            var top = rect.bottom + 4;
            // 超出左边界:改成左对齐
            if (left < 8) left = rect.left;
            // 超出底部:向上弹(否则最下面几项被裁掉点不到)
            if (top + menuHeight > window.innerHeight - 8) {
              top = rect.top - menuHeight - 4;
            }
            menu.style.position = "fixed";
            menu.style.left = left + "px";
            menu.style.top = top + "px";
            menu.style.right = "auto";
            menu.style.zIndex = "9999";
          }
          menu.classList.add("is-open");
          wrap.classList.add("is-open");
        } else {
          // 关闭:移回原 wrap(下次开能再次定位)
          menu.classList.remove("is-open");
          wrap.classList.remove("is-open");
          menu.style.position = "";
          menu.style.left = "";
          menu.style.top = "";
          menu.style.right = "";
          menu.style.zIndex = "";
          if (menu.parentElement !== wrap) {
            wrap.appendChild(menu);
          }
        }
        event.stopPropagation();
      }
    }

    function stKill(playerId) {
      closeAllMenus();
      if (!confirm("确认杀死该玩家?白天会立即公开,夜间将在白天开始时公开。")) return;
      window.StSocket.emit("st_kill", { player_id: playerId });
    }

    function stRevive(playerId) {
      closeAllMenus();
      if (!confirm("确认复活该玩家?")) return;
      window.StSocket.emit("st_revive", { player_id: playerId });
    }

    function stSetDrunk(playerId, value) {
      closeAllMenus();
      window.StSocket.emit("st_set_drunk", { player_id: playerId, value: value });
    }

    function stSetPoisoned(playerId, value) {
      closeAllMenus();
      window.StSocket.emit("st_set_poisoned", { player_id: playerId, value: value });
    }

    function stClearStatus(playerId) {
      closeAllMenus();
      window.StSocket.emit("st_clear_status", { player_id: playerId });
    }

    function showRolePicker(playerId) {
      closeAllMenus();
      _rolePickerPlayerId = playerId;
      var grid = document.getElementById("role-picker-grid");
      if (!grid) return;
      // 关键:从 lastState.script 动态读,不要用写死的 ROLE_LIST
      // (写死列表里有 engineer/fisherman 等用户脚本里没有的角色,
      //  选了之后玩家角色就变成"engineer",脚本里查不到 → 显示成 ID)
      var script = (lastState && lastState.script) || null;
      var groups = [
        { key: "townsfolk", label: "镇民" },
        { key: "outsider",  label: "外来者" },
        { key: "minion",    label: "爪牙" },
        { key: "demon",     label: "恶魔" },
      ];
      var html = "";
      if (script && script.roles && script.roles.length > 0) {
        for (var i = 0; i < groups.length; i++) {
          var g = groups[i];
          var roles = (script.roles || []).filter(function (r) { return r.team === g.key; });
          if (roles.length === 0) continue;
          html += '<div class="role-section-title">' + g.label + '</div>';
          for (var j = 0; j < roles.length; j++) {
            var r = roles[j];
            var display = r.name || r.id;
            var idHint = r.name ? r.id : "";
            html += '<button class="role-option" data-role="' + escapeHtml(r.id) + '">'
                 + escapeHtml(display)
                 + (idHint ? ' <span style="color:var(--ink-soft);font-size:10px;">' + escapeHtml(idHint) + '</span>' : '')
                 + '</button>';
          }
        }
      } else {
        html = '<p style="color:var(--ink-soft);">当前没有可用的脚本,请先录入/导入板子</p>';
      }
      grid.innerHTML = html;
      grid.querySelectorAll(".role-option").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var roleId = btn.getAttribute("data-role");
          window.StSocket.emit("st_change_role", { player_id: _rolePickerPlayerId, new_role: roleId });
          document.getElementById("role-picker-modal").classList.remove("is-open");
          _rolePickerPlayerId = null;
        });
      });
      document.getElementById("role-picker-modal").classList.add("is-open");
    }

    // ---- 批注编辑(多条)----
    var _stNotesLocal = [];
    var _stNotesEditingIdx = -1;

    function _loadStNotesFromState(playerId) {
      var p = (lastState && lastState.players || []).find(function (x) { return x.id === playerId; });
      return p && p.st_notes ? p.st_notes.slice() : [];
    }

    function _renderStNotesList() {
      var list = document.getElementById("st-notes-list");
      if (!list) return;
      if (_stNotesLocal.length === 0) {
        list.innerHTML = '<p style="color: var(--ink-soft); font-size: var(--text-sm); padding: var(--space-3); text-align: center;">还没有批注</p>';
        return;
      }
      list.innerHTML = _stNotesLocal.map(function (n, idx) {
        var isEditing = _stNotesEditingIdx === idx;
        var body;
        if (isEditing) {
          body =
            '<input class="input st-note-edit-input" data-idx="' + idx + '" type="text" maxlength="60" value="' +
            escapeHtml(n.text) + '" style="margin-bottom: 6px;">' +
            '<div style="display: flex; gap: 6px;">' +
              '<button class="btn btn--primary btn-st-note-save" data-idx="' + idx + '" style="flex:1; padding: 4px 10px; font-size: var(--text-xs);">保存</button>' +
              '<button class="btn btn--ghost btn-st-note-cancel" data-idx="' + idx + '" style="flex:1; padding: 4px 10px; font-size: var(--text-xs);">取消</button>' +
            '</div>';
        } else {
          body =
            '<div style="display: flex; align-items: center; gap: 6px;">' +
              '<span style="flex:1; padding: 6px 10px; background: var(--ivory); border-radius: var(--radius-sm); border: 1px solid var(--gold); word-break: break-all;">' +
                escapeHtml(n.text) +
              '</span>' +
              '<button class="btn btn--ghost btn-st-note-edit" data-idx="' + idx + '" style="padding: 4px 10px; font-size: var(--text-xs);">编辑</button>' +
              '<button class="btn btn--danger btn-st-note-del" data-idx="' + idx + '" style="padding: 4px 10px; font-size: var(--text-xs);">删除</button>' +
            '</div>';
        }
        return '<div style="padding: 6px 0; border-bottom: 1px dotted var(--gold);">' + body + '</div>';
      }).join("");

      list.querySelectorAll(".btn-st-note-edit").forEach(function (btn) {
        btn.addEventListener("click", function () {
          _stNotesEditingIdx = parseInt(btn.getAttribute("data-idx"), 10);
          _renderStNotesList();
          var inp = list.querySelector(".st-note-edit-input");
          if (inp) { inp.focus(); inp.select(); }
        });
      });
      list.querySelectorAll(".btn-st-note-del").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var idx = parseInt(btn.getAttribute("data-idx"), 10);
          if (!confirm("删除这条批注?")) return;
          _stNotesLocal.splice(idx, 1);
          _stNotesEditingIdx = -1;
          _renderStNotesList();
          _syncStNotesToServer(window.StStorytellerActions._notePlayerId);
        });
      });
      list.querySelectorAll(".btn-st-note-cancel").forEach(function (btn) {
        btn.addEventListener("click", function () {
          _stNotesEditingIdx = -1;
          _renderStNotesList();
        });
      });
      list.querySelectorAll(".btn-st-note-save").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var idx = parseInt(btn.getAttribute("data-idx"), 10);
          var inp = list.querySelector(".st-note-edit-input");
          var text = inp ? inp.value.trim() : "";
          if (!text) { window.StStore.showToast("批注内容不能为空"); return; }
          _stNotesLocal[idx].text = text;
          _stNotesEditingIdx = -1;
          _renderStNotesList();
          _syncStNotesToServer(window.StStorytellerActions._notePlayerId);
        });
      });
      list.querySelectorAll(".st-note-edit-input").forEach(function (inp) {
        inp.addEventListener("keydown", function (e) {
          if (e.key === "Enter") {
            e.preventDefault();
            var idx = parseInt(inp.getAttribute("data-idx"), 10);
            var text = inp.value.trim();
            if (!text) return;
            _stNotesLocal[idx].text = text;
            _stNotesEditingIdx = -1;
            _renderStNotesList();
            _syncStNotesToServer(window.StStorytellerActions._notePlayerId);
          }
        });
      });
    }

    function _syncStNotesToServer(playerId) {
      if (!playerId) return;
      var notes = _stNotesLocal.map(function (n) { return { id: n.id, text: n.text }; });
      window.StSocket.emit("st_set_notes", { player_id: playerId, notes: notes });
    }

    function _addStNote() {
      var playerId = window.StStorytellerActions._notePlayerId;
      var input = document.getElementById("note-input");
      var text = (input && input.value || "").trim();
      if (!playerId) { window.StStore.showToast("请先选择玩家"); return; }
      if (!text) { window.StStore.showToast("批注内容不能为空"); return; }
      _stNotesLocal.push({ id: "n_" + Date.now() + "_" + Math.random().toString(36).slice(2, 6), text: text });
      if (input) input.value = "";
      _renderStNotesList();
      _syncStNotesToServer(playerId);
    }

    function showNoteEditor(playerId) {
      closeAllMenus();
      window.StStorytellerActions._notePlayerId = playerId;
      _stNotesLocal = _loadStNotesFromState(playerId);
      _stNotesEditingIdx = -1;
      var input = document.getElementById("note-input");
      if (input) input.value = "";
      var title = document.getElementById("note-modal-title");
      var p = (lastState && lastState.players || []).find(function (x) { return x.id === playerId; });
      if (title && p) title.textContent = "关于「" + p.name + "」的批注";
      document.getElementById("note-modal").classList.add("is-open");
      _renderStNotesList();
      setTimeout(function () { if (input) input.focus(); }, 100);
    }

    function stKick(playerId) {
      closeAllMenus();
      var p = (lastState && lastState.players || []).find(function (x) { return x.id === playerId; });
      var name = p ? p.name : playerId;
      if (!confirm("确认将玩家「" + name + "」踢出房间?\n该玩家将被移除,且无法再以同名加入。")) return;
      window.StSocket.emit("st_kick", { player_id: playerId, reason: "说书人踢出" });
    }

    function closeAllMenus() {
      document.querySelectorAll(".player-menu-dropdown.is-open").forEach(function (el) {
        el.classList.remove("is-open");
      });
      document.querySelectorAll(".player-menu-wrap.is-open").forEach(function (el) {
        el.classList.remove("is-open");
      });
    }

    return {
      openMenu: openMenu,
      stKill: stKill,
      stRevive: stRevive,
      stSetDrunk: stSetDrunk,
      stSetPoisoned: stSetPoisoned,
      stClearStatus: stClearStatus,
      stKick: stKick,
      showRolePicker: showRolePicker,
      showNoteEditor: showNoteEditor,
      addStNote: _addStNote,
      closeAllMenus: closeAllMenus,
      _notePlayerId: null,
    };
  })();

  // ---- 关闭菜单(点击外部) ----
  document.addEventListener("click", function () {
    window.StStorytellerActions.closeAllMenus();
  });

  // ---- 角色选择器关闭按钮 ----
  var btnCloseRolePicker = document.getElementById("btn-close-role-picker");
  if (btnCloseRolePicker) {
    btnCloseRolePicker.addEventListener("click", function () {
      document.getElementById("role-picker-modal").classList.remove("is-open");
    });
  }
  var rolePickerModal = document.getElementById("role-picker-modal");
  if (rolePickerModal) {
    rolePickerModal.addEventListener("click", function (e) {
      if (e.target === this) this.classList.remove("is-open");
    });
  }

  // ---- 批注编辑器(多条) ----
  var btnCloseNote = document.getElementById("btn-close-note");
  if (btnCloseNote) {
    btnCloseNote.addEventListener("click", function () {
      document.getElementById("note-modal").classList.remove("is-open");
    });
  }
  var noteModal = document.getElementById("note-modal");
  if (noteModal) {
    noteModal.addEventListener("click", function (e) {
      if (e.target === this) this.classList.remove("is-open");
    });
  }
  var btnAddNote = document.getElementById("btn-add-note");
  if (btnAddNote) {
    btnAddNote.addEventListener("click", function () {
      window.StStorytellerActions.addStNote();
    });
  }
  var noteInput = document.getElementById("note-input");
  if (noteInput) {
    noteInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        btnAddNote && btnAddNote.click();
      }
    });
  }
  var noteInput = document.getElementById("note-input");
  if (noteInput) {
    noteInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") btnSaveNote && btnSaveNote.click();
    });
  }

  // ---- 白天需注意角色侧栏(只显示场上 day_action=True 的角色)----
  function _renderDayAction() {
    if (!dayActionCard || !dayActionList) return;
    const script = lastState && lastState.script;
    if (!script) {
      dayActionList.innerHTML = "";
      if (dayActionEmpty) dayActionEmpty.style.display = "";
      return;
    }
    const activeRoles = _activeRoleIds();
    const order = script.roles
      .filter(function (r) { return r.day_action; })
      .filter(function (r) { return activeRoles.has(r.id); })
      .map(function (r) { return r.id; });
    if (!order || order.length === 0) {
      dayActionList.innerHTML = "";
      if (dayActionEmpty) dayActionEmpty.style.display = "";
      return;
    }
    if (dayActionEmpty) dayActionEmpty.style.display = "none";
    dayActionList.innerHTML = order.map(function (rid) {
      const role = script.roles.find(function (r) { return r.id === rid; });
      const name = role ? (role.name || role.id) : rid;
      return "<li>" + escapeHtml(name) + "</li>";
    }).join("");
  }

  // ---- 传奇角色控制侧栏 ----
  // 列出当前 script 中 team=fabled 的所有角色,ST 可点击切换在场/离场。
  // 在场状态来自 lastState.fabled_in_play(后端 state.fabled_in_play)。
  function _renderFabledList() {
    if (!fabledCard || !fabledList) return;
    const script = lastState && lastState.script;
    if (!script || !Array.isArray(script.roles)) {
      fabledList.innerHTML = "";
      if (fabledEmpty) fabledEmpty.style.display = "none";
      if (fabledNoScript) fabledNoScript.style.display = "";
      fabledCard.style.display = "";
      return;
    }
    const fabledRoles = script.roles.filter(function (r) { return r.team === "fabled"; });
    if (fabledRoles.length === 0) {
      fabledList.innerHTML = "";
      if (fabledEmpty) fabledEmpty.style.display = "";
      if (fabledNoScript) fabledNoScript.style.display = "none";
      fabledCard.style.display = "";
      return;
    }
    if (fabledEmpty) fabledEmpty.style.display = "none";
    if (fabledNoScript) fabledNoScript.style.display = "none";
    fabledCard.style.display = "";

    const inPlay = new Set((lastState && Array.isArray(lastState.fabled_in_play))
      ? lastState.fabled_in_play : []);
    fabledList.innerHTML = fabledRoles.map(function (r) {
      const on = inPlay.has(r.id);
      const name = r.name || r.id;
      const notesHtml = (r.notes && r.notes.trim())
        ? "<div style=\"margin-top: 4px; font-size: var(--text-sm); color: var(--ink-soft); white-space: pre-wrap;\">" + escapeHtml(r.notes) + "</div>"
        : "";
      const toggleLabel = on ? "在场 · 点击下场" : "离场 · 点击上场";
      const toggleClass = on ? "btn btn--danger" : "btn";
      return ""
        + "<li style=\"border: 1px solid var(--gold); border-radius: var(--radius-sm); padding: var(--space-3); background: var(--ivory);\">"
        + "<div style=\"display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); flex-wrap: wrap;\">"
        + "<div>"
        + "<strong style=\"color: var(--gold-deep);\">" + escapeHtml(name) + "</strong>"
        + " <span style=\"color: var(--ink-soft); font-size: var(--text-xs);\">(" + escapeHtml(r.id) + ")</span>"
        + "</div>"
        + "<button class=\"" + toggleClass + "\" data-fabled-toggle=\"" + escapeHtml(r.id) + "\" data-fabled-on=\"" + (on ? "true" : "false") + "\" style=\"padding: 4px 12px; font-size: var(--text-xs);\">" + toggleLabel + "</button>"
        + "</div>"
        + notesHtml
        + "</li>";
    }).join("");

    // 绑定按钮:事件代理,避免重渲染时反复 add/remove listener
    fabledList.querySelectorAll("[data-fabled-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const rid = btn.getAttribute("data-fabled-toggle");
        const currentlyOn = btn.getAttribute("data-fabled-on") === "true";
        window.StSocket.emit("st_toggle_fabled", { role_id: rid, on: !currentlyOn });
      });
    });
  }

  // ---- 在场角色备注侧栏 ----
  // 列出当前在场角色中 ScriptRole.notes 非空的所有角色
  // 显示格式: 「角色名: 备注」
  function _renderRoleNotes() {
    if (!roleNotesCard || !roleNotesList) return;
    const script = lastState && lastState.script;
    if (!script || !Array.isArray(script.roles)) {
      roleNotesList.innerHTML = "";
      if (roleNotesEmpty) roleNotesEmpty.style.display = "";
      roleNotesCard.style.display = "none";
      return;
    }
    const activeRoles = _activeRoleIds();
    const items = script.roles
      .filter(function (r) { return r.notes && r.notes.trim() && activeRoles.has(r.id); })
      .map(function (r) {
        const name = r.name || r.id;
        return { name: name, notes: r.notes };
      });
    if (items.length === 0) {
      roleNotesList.innerHTML = "";
      if (roleNotesEmpty) roleNotesEmpty.style.display = "";
      roleNotesCard.style.display = "none";
      return;
    }
    if (roleNotesEmpty) roleNotesEmpty.style.display = "none";
    roleNotesCard.style.display = "";
    roleNotesList.innerHTML = items.map(function (it) {
      return "<li><strong style=\"color: var(--gold-deep);\">" + escapeHtml(it.name) + "</strong>: " + escapeHtml(it.notes) + "</li>";
    }).join("");
  }

  // ---- 恶魔的伪装侧栏 ----
  // 显示 lastState.demon_disguises 中的角色(开局后由后端填入,恶魔/爪牙共享同一份)
  function _renderDemonDisguises() {
    if (!demonDisguisesCard || !demonDisguisesList) return;
    const list = (lastState && Array.isArray(lastState.demon_disguises)) ? lastState.demon_disguises : [];
    if (!list || list.length === 0) {
      demonDisguisesList.innerHTML = "";
      if (demonDisguisesEmpty) demonDisguisesEmpty.style.display = "";
      if (demonDisguisesCount) demonDisguisesCount.textContent = "";
      demonDisguisesCard.style.display = "none";
      return;
    }
    if (demonDisguisesEmpty) demonDisguisesEmpty.style.display = "none";
    demonDisguisesCard.style.display = "";
    if (demonDisguisesCount) demonDisguisesCount.textContent = `· ${list.length} 个`;
    demonDisguisesList.innerHTML = list.map(function (rid) {
      return "<li><strong style=\"color: var(--rouge);\">" + escapeHtml(_roleNameOf(rid) || rid) + "</strong> <span style=\"color: var(--ink-soft); font-size: var(--text-xs);\">(" + escapeHtml(rid) + ")</span></li>";
    }).join("");
  }

  // ---- 夜晚顺序侧栏(只显示场上实际分配到的角色)----
  function _renderNightOrder(phase) {
    if (!nightOrderCard || !nightOrderList) return;
    const isFirst = (phase === "first_night");
    if (nightOrderTitle) {
      nightOrderTitle.textContent = isFirst ? "🌙 首夜行动顺序" : "🌙 后续夜晚行动顺序";
    }
    const script = lastState && lastState.script;
    if (!script) {
      nightOrderList.innerHTML = "";
      if (nightOrderEmpty) nightOrderEmpty.style.display = "";
      return;
    }
    // 只保留「实际在场」的角色:从 state.players 的 true_role 去重
    const activeRoles = _activeRoleIds();
    const order = script.roles
      .filter(function (r) { return isFirst ? r.first_night : r.other_night; })
      .filter(function (r) { return activeRoles.has(r.id); })
      .map(function (r) { return r.id; });
    if (!order || order.length === 0) {
      nightOrderList.innerHTML = "";
      if (nightOrderEmpty) nightOrderEmpty.style.display = "";
      return;
    }
    if (nightOrderEmpty) nightOrderEmpty.style.display = "none";
    nightOrderList.innerHTML = order.map(function (rid) {
      const role = script.roles.find(function (r) { return r.id === rid; });
      const name = role ? (role.name || role.id) : rid;
      return "<li>" + escapeHtml(name) + "</li>";
    }).join("");
  }

  // ---- 板子编辑(可填充表格 + 导入/导出)----
  // 当前正在编辑的板子(纯客户端,直到 ST 点击「应用」才发到服务端)
  var _editingScript = null;

  function _ensureEditingScript() {
    if (!_editingScript) {
      _editingScript = { id: "", name: "", roles: [], notes: "" };
    }
    return _editingScript;
  }

  function _renderRolesTable() {
    if (!scriptRolesTbody) return;
    var script = _ensureEditingScript();
    scriptRolesTbody.innerHTML = script.roles.map(function (r, idx) {
      var teams = ["townsfolk", "outsider", "minion", "demon", "fabled"];
      var teamLabel = { townsfolk: "镇民", outsider: "外来者", minion: "爪牙", demon: "恶魔", fabled: "传奇" };
      return "<tr data-idx='" + idx + "' draggable='true'>" +
        "<td class='drag-handle' title='拖动以重新排序'>☰</td>" +
        "<td style='padding: 4px; text-align: center; color: var(--ink-soft);'>" + (idx + 1) + "</td>" +
        "<td style='padding: 4px;'><input class='input sc-id' value='" + escapeHtml(r.id || "") + "' placeholder='role_id' style='padding: 4px 6px; font-size: var(--text-xs); width: 100%;'></td>" +
        "<td style='padding: 4px;'><input class='input sc-name' value='" + escapeHtml(r.name || "") + "' placeholder='名称' style='padding: 4px 6px; font-size: var(--text-xs); width: 100%;'></td>" +
        "<td style='padding: 4px;'><select class='input sc-team' style='padding: 4px 6px; font-size: var(--text-xs);'>" +
          teams.map(function (t) { return "<option value='" + t + "'" + (r.team === t ? " selected" : "") + ">" + teamLabel[t] + "</option>"; }).join("") +
        "</select></td>" +
        "<td style='padding: 4px; text-align: center;'><input class='input sc-minion-mod' type='number' value='" + (r.minion_mod || 0) + "' title='T↔M 调整' style='width: 50px; padding: 2px; text-align: center;'></td>" +
        "<td style='padding: 4px; text-align: center;'><input class='input sc-outsider-mod' type='number' value='" + (r.outsider_mod || 0) + "' title='T↔O 调整' style='width: 50px; padding: 2px; text-align: center;'></td>" +
        "<td style='padding: 4px; text-align: center;'><input class='input sc-demon-mod' type='number' value='" + (r.demon_mod || 0) + "' title='T↔D 调整' style='width: 50px; padding: 2px; text-align: center;'></td>" +
        "<td style='padding: 4px;'><input class='input sc-requires' value=\"" + escapeHtml((r.requires || []).join(",")) + "\" placeholder='id1,id2' style='padding: 4px 6px; font-size: var(--text-xs); width: 100%;'></td>" +
        "<td style='padding: 4px;'><input class='input sc-replace' value=\"" + escapeHtml((r.replace_with || []).join(",")) + "\" placeholder='id1,id2' style='padding: 4px 6px; font-size: var(--text-xs); width: 100%;'></td>" +
        "<td style='padding: 4px;'><input class='input sc-notes' value=\"" + escapeHtml(r.notes || "") + "\" placeholder='角色备注' style='padding: 4px 6px; font-size: var(--text-xs); width: 100%;'></td>" +
        "<td style='padding: 4px; text-align: center;'><input type='checkbox' class='sc-first'" + (r.first_night ? " checked" : "") + "></td>" +
        "<td style='padding: 4px; text-align: center;'><input type='checkbox' class='sc-other'" + (r.other_night ? " checked" : "") + "></td>" +
        "<td style='padding: 4px; text-align: center;'><input type='checkbox' class='sc-day'" + (r.day_action ? " checked" : "") + "></td>" +
        "<td style='padding: 4px;'><button class='btn btn--ghost sc-del' style='padding: 2px 8px; font-size: var(--text-xs);'>✕</button></td>" +
      "</tr>";
    }).join("");
    // 绑定变更事件(每次重渲染后)
    scriptRolesTbody.querySelectorAll("tr").forEach(function (tr) {
      var idx = parseInt(tr.getAttribute("data-idx"), 10);
      function syncField() {
        var r = script.roles[idx];
        if (!r) return;
        tr.querySelector(".sc-id").addEventListener("input", function (e) { r.id = e.target.value; });
        tr.querySelector(".sc-name").addEventListener("input", function (e) { r.name = e.target.value; });
        tr.querySelector(".sc-team").addEventListener("change", function (e) { r.team = e.target.value; });
        tr.querySelector(".sc-minion-mod").addEventListener("input", function (e) { r.minion_mod = parseInt(e.target.value || "0", 10) || 0; });
        tr.querySelector(".sc-outsider-mod").addEventListener("input", function (e) { r.outsider_mod = parseInt(e.target.value || "0", 10) || 0; });
        tr.querySelector(".sc-demon-mod").addEventListener("input", function (e) { r.demon_mod = parseInt(e.target.value || "0", 10) || 0; });
        tr.querySelector(".sc-requires").addEventListener("input", function (e) {
          r.requires = e.target.value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
        });
        tr.querySelector(".sc-replace").addEventListener("input", function (e) {
          r.replace_with = e.target.value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
        });
        tr.querySelector(".sc-notes").addEventListener("input", function (e) {
          r.notes = e.target.value;
        });
        tr.querySelector(".sc-first").addEventListener("change", function (e) { r.first_night = e.target.checked; });
        tr.querySelector(".sc-other").addEventListener("change", function (e) { r.other_night = e.target.checked; });
        tr.querySelector(".sc-day").addEventListener("change", function (e) { r.day_action = e.target.checked; });
        tr.querySelector(".sc-del").addEventListener("click", function () {
          script.roles.splice(idx, 1);
          _renderRolesTable();
        });
      }
      syncField();
    });
    // 拖拽事件
    _bindDragEvents();
  }

  // 行拖拽:从 drag-handle 单元格(或行任意位置)开始,拖到目标行
  function _bindDragEvents() {
    if (!scriptRolesTbody) return;
    var rows = scriptRolesTbody.querySelectorAll("tr");
    rows.forEach(function (tr) {
      tr.addEventListener("dragstart", _onRowDragStart);
      tr.addEventListener("dragover", _onRowDragOver);
      tr.addEventListener("dragleave", _onRowDragLeave);
      tr.addEventListener("drop", _onRowDrop);
      tr.addEventListener("dragend", _onRowDragEnd);
    });
  }
  function _onRowDragStart(e) {
    var tr = e.currentTarget;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", tr.getAttribute("data-idx"));
    tr.classList.add("dragging");
  }
  function _onRowDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    var tr = e.currentTarget;
    if (tr.classList.contains("dragging")) return;
    // 清除其他行的 drag-over 样式
    scriptRolesTbody.querySelectorAll("tr.drag-over").forEach(function (el) { el.classList.remove("drag-over"); });
    tr.classList.add("drag-over");
  }
  function _onRowDragLeave(e) {
    e.currentTarget.classList.remove("drag-over");
  }
  function _onRowDrop(e) {
    e.preventDefault();
    var tr = e.currentTarget;
    tr.classList.remove("drag-over");
    var fromIdx = parseInt(e.dataTransfer.getData("text/plain"), 10);
    var toIdx = parseInt(tr.getAttribute("data-idx"), 10);
    if (isNaN(fromIdx) || isNaN(toIdx) || fromIdx === toIdx) return;
    var script = _ensureEditingScript();
    var moved = script.roles.splice(fromIdx, 1)[0];
    script.roles.splice(toIdx, 0, moved);
    _renderRolesTable();
  }
  function _onRowDragEnd(e) {
    scriptRolesTbody.querySelectorAll("tr.dragging, tr.drag-over").forEach(function (el) {
      el.classList.remove("dragging");
      el.classList.remove("drag-over");
    });
  }

  function _openScriptModal() {
    if (!scriptModal) return;
    // 用服务端当前板子初始化(若有);否则空
    if (lastState && lastState.script) {
      _editingScript = JSON.parse(JSON.stringify(lastState.script));
    } else {
      _editingScript = { id: "", name: "", roles: [], notes: "" };
    }
    if (scriptEditId) scriptEditId.value = _editingScript.id || "";
    if (scriptEditName) scriptEditName.value = _editingScript.name || "";
    if (scriptEditNotes) scriptEditNotes.value = _editingScript.notes || "";
    if (scriptImportArea) scriptImportArea.style.display = "none";
    if (scriptExportArea) scriptExportArea.style.display = "none";
    _renderRolesTable();
    scriptModal.classList.add("is-open");
  }
  function _closeScriptModal() { if (scriptModal) scriptModal.classList.remove("is-open"); }

  if (btnManageScripts) btnManageScripts.addEventListener("click", _openScriptModal);
  if (btnCloseScriptModal) btnCloseScriptModal.addEventListener("click", _closeScriptModal);
  if (scriptModal) {
    scriptModal.addEventListener("click", function (e) { if (e.target === scriptModal) _closeScriptModal(); });
  }

  // 添加角色行
  if (btnScriptAddRole) {
    btnScriptAddRole.addEventListener("click", function () {
      var script = _ensureEditingScript();
      script.roles.push({ id: "", name: "", team: "townsfolk", outsider_mod: 0, minion_mod: 0, requires: [], first_night: false, other_night: false, notes: "" });
      _renderRolesTable();
    });
  }

  // 清空
  if (btnScriptClear) {
    btnScriptClear.addEventListener("click", function () {
      if (!confirm("清空当前正在编辑的板子?")) return;
      _editingScript = { id: "", name: "", roles: [], notes: "" };
      if (scriptEditId) scriptEditId.value = "";
      if (scriptEditName) scriptEditName.value = "";
      if (scriptEditNotes) scriptEditNotes.value = "";
      _renderRolesTable();
    });
  }

  // 导入 UI
  if (btnScriptImport) {
    btnScriptImport.addEventListener("click", function () {
      if (scriptImportArea) scriptImportArea.style.display = "";
      if (scriptImportInput) { scriptImportInput.focus(); scriptImportInput.select(); }
    });
  }
  if (btnScriptImportCancel) {
    btnScriptImportCancel.addEventListener("click", function () {
      if (scriptImportArea) scriptImportArea.style.display = "none";
    });
  }
  if (btnScriptImportApply) {
    btnScriptImportApply.addEventListener("click", function () {
      var code = scriptImportInput && scriptImportInput.value || "";
      code = code.trim();
      if (!code) { window.StStore.showToast("请粘贴代码"); return; }
      // 客户端预校验:用服务端解析
      window.StSocket.emit("parse_script_code", { code: code });
    });
  }

  // 导出 UI(纯本地 JSON+base64,不与服务端交互)
  if (btnScriptExport) {
    btnScriptExport.addEventListener("click", function () {
      var script = _collectScriptFromForm();
      if (!script.roles.length) { window.StStore.showToast("请先添加至少一个角色"); return; }
      var payload = { v: 1, id: script.id, name: script.name, roles: script.roles, notes: script.notes };
      var jsonStr = JSON.stringify(payload);
      var b64 = btoa(unescape(encodeURIComponent(jsonStr)));
      var code = "BOTC-SCRIPT-V1:" + b64;
      if (scriptExportOutput) scriptExportOutput.value = code;
      if (scriptExportArea) scriptExportArea.style.display = "";
      if (scriptExportOutput) { scriptExportOutput.focus(); scriptExportOutput.select(); }
    });
  }
  if (btnScriptExportCopy) {
    btnScriptExportCopy.addEventListener("click", function () {
      var code = scriptExportOutput && scriptExportOutput.value || "";
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(code).then(function () {
          window.StStore.showToast("已复制到剪贴板", 1500);
        });
      } else if (scriptExportOutput) {
        scriptExportOutput.select();
        document.execCommand("copy");
        window.StStore.showToast("已复制", 1500);
      }
    });
  }
  if (btnScriptExportClose) {
    btnScriptExportClose.addEventListener("click", function () {
      if (scriptExportArea) scriptExportArea.style.display = "none";
    });
  }

  function _collectScriptFromForm() {
    var roles = (scriptRolesTbody ? Array.from(scriptRolesTbody.querySelectorAll("tr")) : []).map(function (tr) {
      var id = tr.querySelector(".sc-id").value.trim();
      var name = tr.querySelector(".sc-name").value.trim();
      var team = tr.querySelector(".sc-team").value;
      var mm = parseInt(tr.querySelector(".sc-minion-mod").value || "0", 10) || 0;
      var om = parseInt(tr.querySelector(".sc-outsider-mod").value || "0", 10) || 0;
      var dm = parseInt((tr.querySelector(".sc-demon-mod") || {}).value || "0", 10) || 0;
      var req = tr.querySelector(".sc-requires").value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      var rpl = tr.querySelector(".sc-replace").value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      var notes = (tr.querySelector(".sc-notes") || {}).value || "";
      var first = tr.querySelector(".sc-first").checked;
      var dayAct = tr.querySelector(".sc-day").checked;
      var other = tr.querySelector(".sc-other").checked;
      return { id: id, name: name, team: team, outsider_mod: om, minion_mod: mm, demon_mod: dm, requires: req, replace_with: rpl, notes: notes, first_night: first, other_night: other, day_action: dayAct };
    });
    return {
      id: (scriptEditId && scriptEditId.value || "").trim() || "_unnamed",
      name: (scriptEditName && scriptEditName.value || "").trim() || "(未命名)",
      roles: roles,
      notes: (scriptEditNotes && scriptEditNotes.value || ""),
    };
  }

  // 应用到本房间
  if (btnScriptApply) {
    btnScriptApply.addEventListener("click", function () {
      var script = _collectScriptFromForm();
      if (!script.roles.length) { window.StStore.showToast("请先添加至少一个角色"); return; }
      // 校验每个 role 有 id
      for (var i = 0; i < script.roles.length; i++) {
        if (!script.roles[i].id) { window.StStore.showToast("第 " + (i + 1) + " 行缺少角色 ID"); return; }
      }
      window.StSocket.emit("set_script", { script: script });
    });
  }
  if (btnScriptClose) btnScriptClose.addEventListener("click", _closeScriptModal);

  // 服务端解析结果回包
  window.StSocket.on("script_parsed", function (data) {
    if (data && data.script) {
      _editingScript = data.script;
      if (scriptEditId) scriptEditId.value = data.script.id || "";
      if (scriptEditName) scriptEditName.value = data.script.name || "";
      if (scriptEditNotes) scriptEditNotes.value = data.script.notes || "";
      if (scriptImportArea) scriptImportArea.style.display = "none";
      _renderRolesTable();
      window.StStore.showToast("代码解析成功", 1500);
    }
  });
  window.StSocket.on("script_applied", function (data) {
    window.StStore.showToast("板子已应用到本房间", 2000);
    _closeScriptModal();
  });

  // ---- ST 快速日志 ----
  var stLogInput = document.getElementById("st-log-input");
  var btnStAddLog = document.getElementById("btn-st-add-log");
  if (btnStAddLog && stLogInput) {
    btnStAddLog.addEventListener("click", function () {
      var text = (stLogInput.value || "").trim();
      if (!text) { window.StStore.showToast("请输入日志内容"); return; }
      // 快速记录默认仅 ST 可见
      window.StSocket.emit("st_add_log", { text: text, visibility: "st_only" });
      stLogInput.value = "";
    });
    stLogInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") btnStAddLog.click();
    });
  }

  // ---- ST 高级日志(可见范围) ----
  var btnStAddLogAdv = document.getElementById("btn-st-add-log-advanced");
  var stLogModal = document.getElementById("st-log-modal");
  var btnCloseStLog = document.getElementById("btn-close-st-log");
  var stLogInputAdv = document.getElementById("st-log-input-adv");
  var stLogTargetSelect = document.getElementById("st-log-target-select");
  var btnStLogSubmit = document.getElementById("btn-st-log-submit");
  var btnStLogCancel = document.getElementById("btn-st-log-cancel");

  function _populateStLogTargets() {
    if (!stLogTargetSelect) return;
    stLogTargetSelect.innerHTML = "";
    (lastState && lastState.players || []).forEach(function (p) {
      if (p.is_storyteller) return;
      var opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name;
      stLogTargetSelect.appendChild(opt);
    });
  }

  function _refreshLogTargetVisibility() {
    if (!stLogTargetSelect) return;
    var val = (document.querySelector('input[name="log-visibility"]:checked') || {}).value || "st_only";
    stLogTargetSelect.style.display = (val === "private_to_player") ? "" : "none";
  }

  function openStLogModal() {
    if (!stLogModal) return;
    _populateStLogTargets();
    _refreshLogTargetVisibility();
    if (stLogInputAdv) stLogInputAdv.value = "";
    stLogModal.classList.add("is-open");
    setTimeout(function () { if (stLogInputAdv) stLogInputAdv.focus(); }, 80);
  }

  if (btnStAddLogAdv) {
    btnStAddLogAdv.addEventListener("click", openStLogModal);
  }
  if (btnCloseStLog) {
    btnCloseStLog.addEventListener("click", function () {
      stLogModal.classList.remove("is-open");
    });
  }
  if (stLogModal) {
    stLogModal.addEventListener("click", function (e) {
      if (e.target === stLogModal) stLogModal.classList.remove("is-open");
    });
  }
  document.querySelectorAll('input[name="log-visibility"]').forEach(function (r) {
    r.addEventListener("change", _refreshLogTargetVisibility);
  });
  if (btnStLogSubmit) {
    btnStLogSubmit.addEventListener("click", function () {
      var text = (stLogInputAdv && stLogInputAdv.value || "").trim();
      if (!text) { window.StStore.showToast("请输入日志内容"); return; }
      var visibility = (document.querySelector('input[name="log-visibility"]:checked') || {}).value || "st_only";
      var data = { text: text, visibility: visibility };
      if (visibility === "private_to_player") {
        if (!stLogTargetSelect.value) {
          window.StStore.showToast("请选择目标玩家");
          return;
        }
        data.target_id = stLogTargetSelect.value;
      }
      window.StSocket.emit("st_add_log", data);
      stLogModal.classList.remove("is-open");
      if (stLogInputAdv) stLogInputAdv.value = "";
    });
  }
  if (btnStLogCancel) {
    btnStLogCancel.addEventListener("click", function () {
      stLogModal.classList.remove("is-open");
    });
  }
  if (stLogInputAdv) {
    stLogInputAdv.addEventListener("keydown", function (e) {
      if (e.key === "Enter") btnStLogSubmit && btnStLogSubmit.click();
    });
  }

  // ---- 说书人也监听 role_assigned(身份变更后提示) ----
  window.StSocket.on("role_assigned", function (data) {
    if (!data || !data.true_role) return;
    window.StStore.showToast("身份卡已推送给当事玩家: " + (roleDisplayName(data.true_role) || data.true_role));
  });
})();
