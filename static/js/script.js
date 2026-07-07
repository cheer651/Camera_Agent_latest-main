const CHAT_STORAGE_KEY = "camera_agent_chat_sessions_v2";
const DEFAULT_CHAT_GREETING = {
    role: "assistant",
    text: "您好，我可以帮您按日期、时段、摄像头和人物特征查询历史监控记录。您可以直接提问，例如：帮我查一下今天下午 2 号摄像头有没有拍到穿黑衣服的人？",
    references: [],
};

const state = {
    activeTab: "tab-live",
    cameras: [],
    task: {},
    events: [],
    summary: null,
    currentEventsDate: "",
    currentSummaryDate: "",
    chatSessions: [],
    currentChatId: "",
    chatBusy: false,
    voiceBusy: false,
    voiceRecording: false,
    voiceRecorder: null,
    currentAudio: null,
};

function el(id) {
    return document.getElementById(id);
}

function todayString() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
        ? await response.json()
        : { message: await response.text() };

    if (!response.ok) {
        throw new Error(payload.message || "请求失败，请稍后重试。");
    }
    return payload;
}

function taskStatusMeta(status) {
    const mapping = {
        idle: { label: "暂无任务", badge: "bg-gray-100 text-gray-500" },
        running: { label: "运行中", badge: "bg-amber-100 text-amber-700" },
        completed: { label: "已完成", badge: "bg-emerald-100 text-emerald-700" },
        partial_failed: { label: "部分失败", badge: "bg-orange-100 text-orange-700" },
        failed: { label: "执行失败", badge: "bg-rose-100 text-rose-700" },
        success: { label: "已启动", badge: "bg-emerald-100 text-emerald-700" },
        error: { label: "启动失败", badge: "bg-rose-100 text-rose-700" },
    };
    return mapping[status] || { label: status || "未知", badge: "bg-gray-100 text-gray-500" };
}

function riskMeta(level) {
    const key = String(level || "").trim();
    if (key === "High" || key === "高风险") {
        return {
            label: "高风险",
            badge: "bg-rose-100 text-rose-700",
            dot: "bg-rose-500",
        };
    }
    if (key === "Medium" || key === "中风险") {
        return {
            label: "中风险",
            badge: "bg-amber-100 text-amber-700",
            dot: "bg-amber-500",
        };
    }
    return {
        label: "低风险",
        badge: "bg-emerald-100 text-emerald-700",
        dot: "bg-emerald-500",
    };
}

function anomalyLabel(type) {
    const mapping = {
        fire: "火情",
        fall: "跌倒",
        fight: "打斗",
        intrusion: "闯入",
        crowd: "聚集",
        normal: "正常",
        unknown: "未知",
        model_unavailable: "模型未加载成功",
        llm_unavailable: "模型未加载成功",
        "模型未加载成功": "模型未加载成功",
    };
    return mapping[String(type || "").trim()] || String(type || "未知");
}

function formatTime(value) {
    if (!value) return "--:--:--";
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) {
        return date.toLocaleTimeString("zh-CN", { hour12: false });
    }
    const text = String(value);
    return text.length >= 8 ? text.slice(-8) : text;
}

function formatDateTime(value) {
    if (!value) return "--";
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        const hour = String(date.getHours()).padStart(2, "0");
        const minute = String(date.getMinutes()).padStart(2, "0");
        const second = String(date.getSeconds()).padStart(2, "0");
        return `${year}/${month}/${day} ${hour}:${minute}:${second}`;
    }
    return String(value).replace("T", " ").slice(0, 19);
}

function currentClock() {
    return new Date().toLocaleTimeString("zh-CN", { hour12: false });
}

function createChatId() {
    return `chat_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}

function createMessageId() {
    return `msg_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}

function createSessionTitle(seed = "") {
    const clean = String(seed || "").trim().replaceAll(/\s+/g, " ");
    if (!clean) return "新对话";
    return clean.length > 22 ? `${clean.slice(0, 22)}...` : clean;
}

function createChatSession(seedTitle = "") {
    const now = new Date().toISOString();
    return {
        id: createChatId(),
        title: createSessionTitle(seedTitle),
        createdAt: now,
        updatedAt: now,
        messages: [{
            id: createMessageId(),
            ...DEFAULT_CHAT_GREETING,
            createdAt: now,
            loading: false,
            streaming: false,
        }],
    };
}

function normalizeChatMessage(message) {
    return {
        id: String(message?.id || createMessageId()),
        role: message?.role === "user" ? "user" : "assistant",
        text: String(message?.text || ""),
        references: Array.isArray(message?.references) ? message.references : [],
        audioUrl: String(message?.audioUrl || ""),
        createdAt: String(message?.createdAt || new Date().toISOString()),
        loading: false,
        streaming: false,
    };
}

function normalizeChatSession(session) {
    const normalizedMessages = Array.isArray(session?.messages) && session.messages.length
        ? session.messages
            .map(normalizeChatMessage)
            .filter((message) => {
                const text = String(message.text || "").trim();
                if (text) return true;
                if (Array.isArray(message.references) && message.references.length > 0) return true;
                return Boolean(message.audioUrl);
            })
        : [];
    const safeMessages = normalizedMessages.length
        ? normalizedMessages
        : [{
            id: createMessageId(),
            ...DEFAULT_CHAT_GREETING,
            createdAt: new Date().toISOString(),
            loading: false,
            streaming: false,
        }];
    return {
        id: String(session?.id || createChatId()),
        title: createSessionTitle(session?.title || safeMessages.find((item) => item.role === "user")?.text || ""),
        createdAt: String(session?.createdAt || new Date().toISOString()),
        updatedAt: String(session?.updatedAt || session?.createdAt || new Date().toISOString()),
        messages: safeMessages,
    };
}

function persistChatSessions() {
    try {
        localStorage.setItem(
            CHAT_STORAGE_KEY,
            JSON.stringify({
                currentChatId: state.currentChatId,
                sessions: state.chatSessions,
            })
        );
    } catch (error) {
        console.warn("保存聊天记录失败", error);
    }
}

function loadChatSessions() {
    try {
        const raw = localStorage.getItem(CHAT_STORAGE_KEY);
        if (!raw) {
            const session = createChatSession();
            state.chatSessions = [session];
            state.currentChatId = session.id;
            persistChatSessions();
            return;
        }

        const parsed = JSON.parse(raw);
        const sessions = Array.isArray(parsed?.sessions)
            ? parsed.sessions.map(normalizeChatSession).sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt))
            : [];
        if (!sessions.length) {
            const session = createChatSession();
            state.chatSessions = [session];
            state.currentChatId = session.id;
            persistChatSessions();
            return;
        }

        state.chatSessions = sessions;
        state.currentChatId = sessions.some((item) => item.id === parsed?.currentChatId)
            ? parsed.currentChatId
            : sessions[0].id;
    } catch (error) {
        console.warn("读取聊天记录失败，已重置本地会话。", error);
        const session = createChatSession();
        state.chatSessions = [session];
        state.currentChatId = session.id;
        persistChatSessions();
    }
}

function getCurrentChatSession() {
    return state.chatSessions.find((session) => session.id === state.currentChatId) || null;
}

function getChatSessionById(sessionId) {
    return state.chatSessions.find((session) => session.id === sessionId) || null;
}

function buildChatHistoryPayload(session) {
    if (!session || !Array.isArray(session.messages)) {
        return [];
    }

    return session.messages
        .filter((message) => {
            const text = String(message?.text || "").trim();
            if (!text) return false;
            if (message.role !== "user" && text === DEFAULT_CHAT_GREETING.text) return false;
            return true;
        })
        .slice(-8)
        .map((message) => ({
            role: message.role === "user" ? "user" : "assistant",
            text: String(message.text || ""),
        }));
}

function updateSessionMetadata(session) {
    const firstUserMessage = session.messages.find((item) => item.role === "user" && item.text.trim());
    session.title = firstUserMessage ? createSessionTitle(firstUserMessage.text) : "新对话";
    session.updatedAt = new Date().toISOString();
}

function startNewChatSession() {
    const session = createChatSession();
    state.chatSessions.unshift(session);
    state.currentChatId = session.id;
    persistChatSessions();
    renderChatSessions();
    renderChatMessages();
    const input = el("question-input");
    if (input) {
        input.focus();
    }
}

function selectChatSession(sessionId) {
    if (!state.chatSessions.some((session) => session.id === sessionId)) return;
    state.currentChatId = sessionId;
    persistChatSessions();
    renderChatSessions();
    renderChatMessages();
}

function deleteChatSession(sessionId) {
    if (!sessionId) return;
    if (state.chatBusy && state.currentChatId === sessionId) {
        return;
    }

    const nextSessions = state.chatSessions.filter((session) => session.id !== sessionId);
    if (!nextSessions.length) {
        const fallback = createChatSession();
        state.chatSessions = [fallback];
        state.currentChatId = fallback.id;
    } else {
        state.chatSessions = nextSessions;
        if (state.currentChatId === sessionId) {
            state.currentChatId = nextSessions[0].id;
        } else if (!nextSessions.some((session) => session.id === state.currentChatId)) {
            state.currentChatId = nextSessions[0].id;
        }
    }

    persistChatSessions();
    renderChatSessions();
    renderChatMessages();
}

function sessionGroupLabel(updatedAt) {
    const today = todayString();
    const yesterdayDate = new Date();
    yesterdayDate.setDate(yesterdayDate.getDate() - 1);
    const yesterday = `${yesterdayDate.getFullYear()}-${String(yesterdayDate.getMonth() + 1).padStart(2, "0")}-${String(yesterdayDate.getDate()).padStart(2, "0")}`;
    const dateText = String(updatedAt || "").slice(0, 10);
    if (dateText === today) return "今天";
    if (dateText === yesterday) return "昨天";
    return "更早";
}

function formatSessionMeta(value) {
    if (!value) return "--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    const hour = String(date.getHours()).padStart(2, "0");
    const minute = String(date.getMinutes()).padStart(2, "0");
    return `${month}/${day} ${hour}:${minute}`;
}

function renderChatSessions() {
    const container = el("chat-session-list");
    const titleNode = el("chat-session-title");
    if (!container) return;

    const session = getCurrentChatSession();
    if (titleNode) {
        titleNode.textContent = session?.title || "新对话";
    }

    const grouped = new Map();
    state.chatSessions.forEach((item) => {
        const key = sessionGroupLabel(item.updatedAt);
        if (!grouped.has(key)) {
            grouped.set(key, []);
        }
        grouped.get(key).push(item);
    });

    const order = ["今天", "昨天", "更早"];
    container.innerHTML = order
        .filter((key) => grouped.has(key))
        .map((key) => {
            const items = grouped.get(key) || [];
            return `
                <section class="space-y-2">
                    <div class="px-3 text-xs font-semibold tracking-wide text-gray-400">${escapeHtml(key)}</div>
                    <div class="space-y-2">
                        ${items
                            .map((item) => {
                                const preview = item.messages.find((message) => message.role === "user")?.text
                                    || item.messages[0]?.text
                                    || "暂无消息";
                                const active = item.id === state.currentChatId;
                                return `
                                    <div
                                        data-chat-id="${escapeHtml(item.id)}"
                                        class="chat-session-item w-full text-left rounded-2xl border pl-3 pr-12 pt-3 pb-5 ${active ? "bg-white border-primary/30 shadow-sm" : "bg-white/70 border-transparent hover:border-gray-200"}"
                                    >
                                        <div class="flex items-start justify-between gap-3">
                                            <div class="min-w-0 flex-1">
                                                <div class="truncate text-sm font-medium ${active ? "text-primary" : "text-gray-700"}">${escapeHtml(item.title)}</div>
                                                <div class="mt-1 text-xs text-gray-400 overflow-hidden text-ellipsis whitespace-nowrap">${escapeHtml(preview)}</div>
                                            </div>
                                            <div class="shrink-0 text-[11px] text-gray-400">${escapeHtml(formatSessionMeta(item.updatedAt))}</div>
                                        </div>
                                        <button
                                            type="button"
                                            data-delete-chat-id="${escapeHtml(item.id)}"
                                            class="chat-delete-btn absolute bottom-2 right-2 inline-flex h-7 w-7 items-center justify-center rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                                            title="删除该对话"
                                            aria-label="删除该对话"
                                        >
                                            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M9 7V4a1 1 0 011-1h4a1 1 0 011 1v3m-7 0h8"></path>
                                            </svg>
                                        </button>
                                    </div>
                                `;
                            })
                            .join("")}
                    </div>
                </section>
            `;
        })
        .join("");

    container.querySelectorAll("[data-chat-id]").forEach((itemNode) => {
        itemNode.addEventListener("click", () => {
            selectChatSession(itemNode.getAttribute("data-chat-id") || "");
        });
    });

    container.querySelectorAll("[data-delete-chat-id]").forEach((deleteButton) => {
        deleteButton.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            deleteChatSession(deleteButton.getAttribute("data-delete-chat-id") || "");
        });
    });
}

function switchTab(tabId) {
    state.activeTab = tabId;

    document.querySelectorAll(".tab-content").forEach((content) => {
        const active = content.id === tabId;
        content.classList.toggle("hidden", !active);
        content.classList.toggle("block", active);
    });

    document.querySelectorAll(".tab-btn").forEach((button) => {
        const active = button.id === `btn-${tabId.replace("tab-", "")}`;
        button.classList.toggle("bg-white", active);
        button.classList.toggle("text-primary", active);
        button.classList.toggle("shadow-sm", active);
        button.classList.toggle("text-gray-500", !active);
    });
}

window.switchTab = switchTab;

function updateCameraClocks() {
    const time = currentClock();
    document.querySelectorAll(".js-camera-clock").forEach((node) => {
        node.textContent = time;
    });
}

function renderTaskStatus(task) {
    state.task = task || {};
    const container = el("task-status");
    const pill = el("task-status-pill");
    if (!container || !pill) return;

    const meta = taskStatusMeta(state.task.status || "idle");
    pill.textContent = meta.label;
    pill.className = `inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${meta.badge}`;

    const cards = [
        { label: "任务编号", value: state.task.task_id || "--" },
        { label: "任务状态", value: meta.label },
        { label: "采集时长", value: `${state.task.duration_seconds || 0} 秒` },
        { label: "摄像头", value: (state.task.camera_ids || []).join(" / ") || "--" },
        { label: "关键帧事件数", value: String(state.task.event_count || 0) },
        { label: "开始时间", value: formatDateTime(state.task.started_at) },
        { label: "完成时间", value: state.task.finished_at ? formatDateTime(state.task.finished_at) : "--" },
        { label: "任务说明", value: state.task.message || "等待执行新的分析任务。" },
    ];

    container.innerHTML = cards
        .map(
            (item) => `
                <div class="bg-gray-50 border border-gray-100 rounded-xl p-4">
                    <div class="text-xs text-gray-400 mb-2">${escapeHtml(item.label)}</div>
                    <div class="text-sm font-medium text-gray-800 leading-relaxed">${escapeHtml(item.value)}</div>
                </div>
            `
        )
        .join("");
}

function cameraStatusBadge(camera) {
    if (camera.available) {
        return {
            dot: "bg-green-500 animate-pulse",
            text: "在线",
        };
    }
    return {
        dot: "bg-gray-300",
        text: "离线",
    };
}

function renderCameras(cameras) {
    state.cameras = Array.isArray(cameras) ? cameras : [];
    const container = el("live-camera-grid");
    if (!container) return;

    if (!state.cameras.length) {
        container.innerHTML = `
            <div class="md:col-span-2 bg-surface rounded-xl shadow-soft border border-dashed border-gray-200 p-10 text-center text-sm text-gray-500">
                当前没有可用的摄像头配置，请先检查配置文件或 RTSP 地址。
            </div>
        `;
        return;
    }

    container.innerHTML = state.cameras
        .map((camera, index) => {
            const badge = cameraStatusBadge(camera);
            const title = camera.name || `摄像头 ${index + 1}`;
            const description = camera.description || "未填写摄像头说明";
            return `
                <div class="bg-surface rounded-xl shadow-soft border border-gray-100 overflow-hidden">
                    <div class="px-4 py-3 border-b border-gray-50 flex justify-between items-center bg-gray-50">
                        <span class="font-semibold text-gray-700 flex items-center gap-2">
                            <span class="w-2 h-2 rounded-full ${badge.dot}"></span>
                            ${escapeHtml(title)}
                        </span>
                        <span class="text-xs text-gray-400 font-mono js-camera-clock">${currentClock()}</span>
                    </div>
                    <div class="aspect-video bg-gray-900 relative flex justify-center items-center overflow-hidden">
                        <img
                            src="${escapeHtml(camera.video_feed_url || "")}"
                            alt="${escapeHtml(title)}"
                            class="camera-stream absolute inset-0 hidden h-full w-full object-cover"
                        >
                        <span class="camera-placeholder text-gray-500 text-sm">RTSP 视频流加载中...</span>
                        <div class="absolute left-4 bottom-4 bg-black/55 text-white text-xs px-2 py-1 rounded backdrop-blur-sm">${escapeHtml(camera.camera_id || `Cam-0${index + 1}`)}</div>
                        <div class="absolute right-4 bottom-4 bg-white/10 text-white text-xs px-2 py-1 rounded backdrop-blur-sm">${escapeHtml(badge.text)}</div>
                    </div>
                    <div class="px-4 py-4 bg-white space-y-2">
                        <div class="text-sm text-gray-700 font-medium">${escapeHtml(description)}</div>
                        <div class="text-xs text-gray-400">视频源：${escapeHtml(camera.source_preview || "--")}</div>
                    </div>
                </div>
            `;
        })
        .join("");

    bindStreamPlaceholders();
}

function bindStreamPlaceholders() {
    document.querySelectorAll(".camera-stream").forEach((image) => {
        if (image.dataset.bound === "1") return;
        image.dataset.bound = "1";

        image.addEventListener("load", () => {
            image.classList.remove("hidden");
            const placeholder = image.parentElement?.querySelector(".camera-placeholder");
            if (placeholder) {
                placeholder.classList.add("hidden");
            }
        });

        image.addEventListener("error", () => {
            image.classList.add("hidden");
            const placeholder = image.parentElement?.querySelector(".camera-placeholder");
            if (placeholder) {
                placeholder.textContent = "视频流暂不可用";
                placeholder.classList.remove("hidden");
            }
        });
    });
}

function sortEventsByTime(events) {
    return [...events].sort((a, b) => {
        const timeA = new Date(a.timestamp || a.event_time || 0).getTime();
        const timeB = new Date(b.timestamp || b.event_time || 0).getTime();
        return timeA - timeB;
    });
}

function cameraGroupAccent(index) {
    const accents = [
        "bg-green-100 border-green-300",
        "bg-blue-100 border-blue-300",
        "bg-emerald-100 border-emerald-300",
        "bg-cyan-100 border-cyan-300",
    ];
    return accents[index % accents.length];
}

function renderKeyframes(events) {
    state.events = Array.isArray(events) ? events : [];
    const container = el("keyframe-groups");
    if (!container) return;

    const cameraLookup = new Map();
    state.cameras.forEach((camera, index) => {
        cameraLookup.set(camera.camera_id, {
            camera_id: camera.camera_id,
            name: camera.name || `摄像头 ${index + 1}`,
        });
    });

    state.events.forEach((event, index) => {
        if (!cameraLookup.has(event.camera_id)) {
            cameraLookup.set(event.camera_id, {
                camera_id: event.camera_id,
                name: event.camera_name || `摄像头 ${index + 1}`,
            });
        }
    });

    const cameras = [...cameraLookup.values()];
    if (!cameras.length) {
        container.innerHTML = `
            <div class="md:col-span-2 bg-surface rounded-xl shadow-soft border border-dashed border-gray-200 p-10 text-center text-sm text-gray-500">
                当前没有可展示的关键帧数据。
            </div>
        `;
        return;
    }

    const grouped = new Map();
    cameras.forEach((camera) => grouped.set(camera.camera_id, []));
    state.events.forEach((event) => {
        if (!grouped.has(event.camera_id)) {
            grouped.set(event.camera_id, []);
        }
        grouped.get(event.camera_id).push(event);
    });

    container.innerHTML = cameras
        .map((camera, index) => {
            const accent = cameraGroupAccent(index);
            const eventsForCamera = sortEventsByTime(grouped.get(camera.camera_id) || []);
            const timelineHtml = eventsForCamera.length
                ? eventsForCamera
                      .map((event) => {
                          const risk = riskMeta(event.risk_level);
                          const imageBlock = event.image_url
                              ? `<img src="${escapeHtml(event.image_url)}" alt="${escapeHtml(event.camera_name || camera.name)}" class="h-full w-full object-cover">`
                              : `<span class="text-gray-400 text-sm">暂无抓拍图像</span>`;
                          return `
                              <div class="relative pl-8">
                                  <div class="absolute -left-[9px] top-1 w-4 h-4 rounded-full ${risk.dot} border-4 border-white shadow"></div>
                                  <div class="bg-surface rounded-xl shadow-soft border border-gray-100 p-4 hover:shadow-md transition-shadow">
                                      <div class="aspect-[3/2] bg-gray-200 rounded-lg mb-4 flex items-center justify-center text-gray-400 text-sm overflow-hidden relative">
                                          ${imageBlock}
                                          <span class="absolute bottom-1 right-1 bg-black/60 text-white text-[10px] px-1 rounded">${escapeHtml(formatDateTime(event.timestamp || event.event_time))}</span>
                                      </div>
                                      <div class="flex items-center gap-2 mb-2 flex-wrap">
                                          <span class="px-2 py-1 rounded text-xs font-bold ${risk.badge}">${risk.label}</span>
                                          <span class="px-2 py-1 bg-gray-100 text-gray-500 rounded text-xs font-medium">${escapeHtml(anomalyLabel(event.anomaly_type))}</span>
                                      </div>
                                      <p class="text-sm text-gray-700 leading-relaxed"><strong>分析：</strong>${escapeHtml(event.description || "暂无分析内容")}</p>
                                      <p class="mt-2 text-xs text-gray-500 leading-relaxed"><strong>依据：</strong>${escapeHtml(event.reason || "暂无补充说明")}</p>
                                      <p class="mt-3 text-xs text-gray-400">时间轴：${escapeHtml(event.time_label || formatTime(event.timestamp || event.event_time))}</p>
                                  </div>
                              </div>
                          `;
                      })
                      .join("")
                : `
                    <div class="relative pl-8">
                        <div class="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-gray-300 border-4 border-white shadow"></div>
                        <div class="bg-surface rounded-xl shadow-soft border border-dashed border-gray-200 p-6 text-sm text-gray-500">
                            所选日期暂无关键帧记录。
                        </div>
                    </div>
                `;

            return `
                <div>
                    <h3 class="font-bold text-xl text-gray-700 mb-6 flex items-center gap-3">
                        <span class="w-4 h-4 rounded-full border-2 ${accent}"></span>
                        ${escapeHtml(camera.name)} - ${escapeHtml(camera.camera_id)}
                    </h3>
                    <div class="relative border-l-2 border-primaryLight ml-4 space-y-8 pb-8">
                        ${timelineHtml}
                    </div>
                </div>
            `;
        })
        .join("");
}

function appendChatMessage(role, text, references = [], extra = {}, sessionId = state.currentChatId) {
    const session = getChatSessionById(sessionId);
    if (!session) return;
    const message = {
        id: createMessageId(),
        role: role === "user" ? "user" : "assistant",
        text: String(text || ""),
        references: Array.isArray(references) ? references : [],
        audioUrl: String(extra?.audioUrl || ""),
        createdAt: new Date().toISOString(),
        loading: Boolean(extra?.loading),
        streaming: Boolean(extra?.streaming),
    };
    session.messages.push(message);
    updateSessionMetadata(session);
    state.chatSessions.sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
    persistChatSessions();
    renderChatSessions();
    renderChatMessages();
    return message.id;
}

function updateChatMessage(sessionId, messageId, patch = {}) {
    const session = getChatSessionById(sessionId);
    if (!session) return;
    const message = session.messages.find((item) => item.id === messageId);
    if (!message) return;

    Object.assign(message, patch);
    if (typeof message.text !== "string") {
        message.text = String(message.text || "");
    }
    if (!Array.isArray(message.references)) {
        message.references = [];
    }
    if (typeof message.audioUrl !== "string") {
        message.audioUrl = "";
    }
    message.loading = Boolean(message.loading);
    message.streaming = Boolean(message.streaming);

    updateSessionMetadata(session);
    state.chatSessions.sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
    persistChatSessions();
    renderChatSessions();
    renderChatMessages();
}

function appendChatMessageText(sessionId, messageId, delta) {
    const session = getChatSessionById(sessionId);
    if (!session) return;
    const message = session.messages.find((item) => item.id === messageId);
    if (!message) return;

    message.text = `${message.text || ""}${String(delta || "")}`;
    message.loading = false;
    message.streaming = true;
    updateSessionMetadata(session);
    persistChatSessions();
    renderChatSessions();
    renderChatMessages();
}

function renderChatMessages() {
    const container = el("chat-messages");
    if (!container) return;

    const session = getCurrentChatSession();
    if (!session) {
        container.innerHTML = "";
        return;
    }

    container.innerHTML = session.messages
        .map((message) => {
            const roleClass = message.role === "user"
                ? "bg-primary text-white rounded-2xl rounded-tr-sm text-left"
                : "bg-white border border-gray-100 rounded-2xl rounded-tl-sm text-gray-700 text-left";
            const stackClass = message.role === "user"
                ? "chat-message-stack chat-message-stack-user"
                : "chat-message-stack chat-message-stack-assistant";
            const renderedText = escapeHtml(String(message.text || "").trim());

            const messageBodyHtml = message.loading && !String(message.text || "").trim()
                ? '<div class="chat-typing-indicator" aria-label="正在生成回复"><span></span><span></span><span></span></div>'
                : `<div class="chat-bubble-text text-sm leading-relaxed">${renderedText}${message.streaming ? '<span class="chat-stream-cursor"></span>' : ""}</div>`;

            const referencesHtml = Array.isArray(message.references) && message.references.length
                ? `
                    <div class="chat-reference-panel">
                        <div class="chat-reference-grid">
                            ${message.references
                                .map((item) => {
                                    const imageContent = item.image_url
                                        ? `<img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.camera_name || "关键帧")}" class="w-40 h-24 object-cover rounded">`
                                        : `<div class="w-40 h-24 bg-gray-200 rounded flex items-center justify-center text-xs text-gray-500">暂无截图</div>`;
                                    return `
                                        <div class="border border-gray-200 rounded-lg p-2 bg-white">
                                            <div class="w-40 h-24 rounded mb-2 overflow-hidden relative bg-gray-200">
                                                ${imageContent}
                                                <span class="absolute bottom-1 right-1 bg-black/60 text-white text-[10px] px-1 rounded">${escapeHtml(formatTime(item.event_time || item.timestamp))}</span>
                                            </div>
                                            <p class="text-xs text-gray-500 text-center">${escapeHtml(item.camera_name || item.camera_id || "未知摄像头")}</p>
                                        </div>
                                    `;
                                })
                                .join("")}
                        </div>
                    </div>
                `
                : "";

            return `
                <div class="chat-message-row ${message.role === "user" ? "justify-end" : "justify-start"}" data-message-id="${escapeHtml(message.id)}">
                    <div class="${stackClass}">
                        <div class="${roleClass} chat-bubble ${message.role === "user" ? "chat-bubble-user" : "chat-bubble-assistant"} px-4 py-3 shadow-sm">
                            ${messageBodyHtml}
                        </div>
                        ${referencesHtml}
                    </div>
                </div>
            `;
        })
        .join("");
    container.scrollTop = container.scrollHeight;
}

function bindAudioElement(audioElement) {
    if (!audioElement || audioElement.dataset.bound === "1") return;
    audioElement.dataset.bound = "1";

    audioElement.addEventListener("play", () => {
        if (state.currentAudio && state.currentAudio !== audioElement) {
            state.currentAudio.pause();
        }
        state.currentAudio = audioElement;
    });

    audioElement.addEventListener("ended", () => {
        if (state.currentAudio === audioElement) {
            state.currentAudio = null;
        }
    });
}

function stopCurrentAudio() {
    if (!state.currentAudio) return;
    state.currentAudio.pause();
    state.currentAudio.currentTime = 0;
    state.currentAudio = null;
}

function setVoiceStatus(message = "", tone = "") {
    const node = el("voice-status");
    if (!node) return;
    node.textContent = String(message || "");
    node.dataset.tone = tone || "";
}

function syncChatControls() {
    const input = el("question-input");
    const askButton = el("ask-button");
    const voiceButton = null;
    const voiceIcon = null;
    const interactionBusy = Boolean(state.chatBusy);

    if (input) {
        input.disabled = interactionBusy;
    }
    if (askButton) {
        askButton.disabled = interactionBusy;
    }
    if (voiceButton) {
        voiceButton.disabled = interactionBusy;
        voiceButton.classList.toggle("voice-button-recording", state.voiceRecording);
        voiceButton.classList.toggle("voice-button-processing", !state.voiceRecording && state.voiceBusy);
        voiceButton.setAttribute("aria-label", state.voiceRecording ? "停止录音并发送" : "开始语音提问");
    }
    if (voiceIcon) {
        voiceIcon.innerHTML = state.voiceRecording
            ? '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 6h12v12H6z"></path>'
            : '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 18.5a4.5 4.5 0 004.5-4.5V8a4.5 4.5 0 10-9 0v6a4.5 4.5 0 004.5 4.5z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 11.5a7 7 0 0014 0M12 18.5V21M9 21h6"></path>';
    }
}

function mergeAudioChunks(chunks, totalLength) {
    const inferredLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const safeLength = Math.max(Number(totalLength) || 0, inferredLength);
    const output = new Float32Array(safeLength);
    let offset = 0;
    chunks.forEach((chunk) => {
        const remaining = output.length - offset;
        if (remaining <= 0) {
            return;
        }
        if (chunk.length <= remaining) {
            output.set(chunk, offset);
            offset += chunk.length;
            return;
        }
        output.set(chunk.subarray(0, remaining), offset);
        offset += remaining;
    });
    return offset === output.length ? output : output.subarray(0, offset);
}

function downsampleBuffer(sourceBuffer, sourceRate, targetRate = 16000) {
    if (sourceRate === targetRate) {
        return sourceBuffer;
    }

    const sampleRateRatio = sourceRate / targetRate;
    const outputLength = Math.max(1, Math.round(sourceBuffer.length / sampleRateRatio));
    const output = new Float32Array(outputLength);
    let offsetSource = 0;

    for (let index = 0; index < outputLength; index += 1) {
        const nextOffsetSource = Math.round((index + 1) * sampleRateRatio);
        let accumulator = 0;
        let count = 0;
        for (let sampleIndex = offsetSource; sampleIndex < nextOffsetSource && sampleIndex < sourceBuffer.length; sampleIndex += 1) {
            accumulator += sourceBuffer[sampleIndex];
            count += 1;
        }
        output[index] = count > 0 ? accumulator / count : 0;
        offsetSource = nextOffsetSource;
    }

    return output;
}

function writeAsciiString(view, offset, value) {
    for (let index = 0; index < value.length; index += 1) {
        view.setUint8(offset + index, value.charCodeAt(index));
    }
}

function encodeWavBlob(samples, sampleRate) {
    const bytesPerSample = 2;
    const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample);
    const view = new DataView(buffer);

    writeAsciiString(view, 0, "RIFF");
    view.setUint32(4, 36 + samples.length * bytesPerSample, true);
    writeAsciiString(view, 8, "WAVE");
    writeAsciiString(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * bytesPerSample, true);
    view.setUint16(32, bytesPerSample, true);
    view.setUint16(34, 16, true);
    writeAsciiString(view, 36, "data");
    view.setUint32(40, samples.length * bytesPerSample, true);

    let offset = 44;
    samples.forEach((sample) => {
        const clamped = Math.max(-1, Math.min(1, sample));
        view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
        offset += 2;
    });

    return new Blob([buffer], { type: "audio/wav" });
}

async function startVoiceRecording() {
    if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("当前浏览器不支持麦克风录音。");
    }
    if (!window.isSecureContext) {
        console.warn("当前不是安全上下文，语音功能可能受限。建议使用 HTTPS 或本机 localhost 访问以获得完整功能。");
    }

    const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
        },
    });
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    await audioContext.resume();

    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    const sink = audioContext.createGain();
    sink.gain.value = 0;

    const chunks = [];
    let totalLength = 0;

    state.voiceRecorder = {
        stream,
        audioContext,
        source,
        processor,
        sink,
        chunks,
        totalLength: 0,
        sampleRate: audioContext.sampleRate,
    };

    processor.onaudioprocess = (event) => {
        const inputData = event.inputBuffer.getChannelData(0);
        chunks.push(new Float32Array(inputData));
        totalLength += inputData.length;
        if (state.voiceRecorder) {
            state.voiceRecorder.totalLength = totalLength;
        }
    };

    source.connect(processor);
    processor.connect(sink);
    sink.connect(audioContext.destination);

    state.voiceRecording = true;
    syncChatControls();
    setVoiceStatus("正在录音，再点一次麦克风按钮即可发送。", "processing");
}

async function stopVoiceRecording({ submit = true } = {}) {
    const recorder = state.voiceRecorder;
    if (!recorder) return null;

    recorder.processor.onaudioprocess = null;
    recorder.source.disconnect();
    recorder.processor.disconnect();
    recorder.sink.disconnect();
    recorder.stream.getTracks().forEach((track) => track.stop());
    await recorder.audioContext.close();

    state.voiceRecorder = null;
    state.voiceRecording = false;
    syncChatControls();

    if (!submit) {
        return null;
    }

    const merged = mergeAudioChunks(recorder.chunks, recorder.totalLength);
    if (!merged.length) {
        throw new Error("未录到有效语音，请重试。");
    }

    const downsampled = downsampleBuffer(merged, recorder.sampleRate, 16000);
    return encodeWavBlob(downsampled, 16000);
}

async function requestVoiceTranscription(audioBlob) {
    const formData = new FormData();
    formData.append("audio", audioBlob, `voice_${Date.now()}.wav`);
    return requestJson("/api/voice/transcribe", {
        method: "POST",
        body: formData,
    });
}

async function requestSpeechSynthesis(text) {
    return requestJson("/api/voice/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
    });
}

function syncGlobalAudioPlayer(audioUrl = "") {
    const panel = el("tts-player-panel");
    const player = el("global-tts-player");
    if (!panel || !player) return null;

    const cleanUrl = String(audioUrl || "").trim();
    if (!cleanUrl) {
        panel.classList.add("hidden");
        player.removeAttribute("src");
        player.load();
        return player;
    }

    panel.classList.remove("hidden");
    if (player.getAttribute("src") !== cleanUrl) {
        player.setAttribute("src", cleanUrl);
        player.load();
    }
    bindAudioElement(player);
    return player;
}

async function playAudioUrl(audioUrl) {
    const player = syncGlobalAudioPlayer(audioUrl);
    if (!player || !String(audioUrl || "").trim()) return false;

    stopCurrentAudio();
    try {
        player.currentTime = 0;
        await player.play();
        return true;
    } catch (error) {
        console.warn("自动播放全局语音失败", error);
        return false;
    }
}

async function playMessageAudio(messageId) {
    await new Promise((resolve) => window.requestAnimationFrame(resolve));
    const audioElement = document.querySelector(`audio[data-message-audio="${messageId}"]`);
    if (!audioElement) return false;

    bindAudioElement(audioElement);
    stopCurrentAudio();
    try {
        await audioElement.play();
        return true;
    } catch (error) {
        console.warn("自动播放语音失败", error);
        return false;
    }
}

async function synthesizeAssistantSpeech(sessionId, messageId, answerText) {
    const cleanAnswer = String(answerText || "").trim();
    if (!cleanAnswer) return;

    const slowHintTimer = window.setTimeout(() => {
        setVoiceStatus("语音模型正在预热，首次播报可能需要 20 秒左右，请稍候。", "processing");
    }, 4000);

    try {
        setVoiceStatus("正在合成语音播报...", "processing");
        const speech = await requestSpeechSynthesis(cleanAnswer);
        const audioUrl = String(speech.audio_url || "").trim();
        updateChatMessage(sessionId, messageId, {
            audioUrl,
        });
        syncGlobalAudioPlayer(audioUrl);
        const played = await playAudioUrl(audioUrl) || await playMessageAudio(messageId);
        setVoiceStatus(
            played ? "已完成语音播报。" : "语音已生成，点击播放器即可播报。",
            played ? "success" : "processing"
        );
    } catch (error) {
        setVoiceStatus(error.message || "语音播报失败，请稍后重试。", "error");
    }
}

function periodCardMeta(periodName) {
    const mapping = {
        早晨: {
            border: "border-l-blue-400",
            icon: '<svg class="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z"></path></svg>',
        },
        下午: {
            border: "border-l-orange-400",
            icon: '<svg class="w-5 h-5 text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>',
        },
        晚上: {
            border: "border-l-indigo-500",
            icon: '<svg class="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"></path></svg>',
        },
        凌晨: {
            border: "border-l-gray-600",
            icon: '<svg class="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>',
        },
    };
    return mapping[periodName] || mapping.凌晨;
}

function renderSummary(summary) {
    state.summary = summary || null;
    const overall = el("summary-overall");
    const periodsContainer = el("summary-periods");
    const totalEvents = el("summary-total-events");
    const highRisk = el("summary-high-risk");
    const runtime = el("summary-runtime");

    if (!overall || !periodsContainer || !totalEvents || !highRisk || !runtime) return;

    const periods = Array.isArray(summary?.periods) ? [...summary.periods] : [];
    const order = { 早晨: 0, 下午: 1, 晚上: 2, 凌晨: 3 };
    periods.sort((a, b) => (order[a.name] ?? 99) - (order[b.name] ?? 99));

    const total = periods.reduce((sum, item) => sum + Number(item.event_count || 0), 0);
    const high = periods.reduce((sum, item) => sum + Number(item.high_count || 0), 0);

    totalEvents.textContent = String(total);
    highRisk.textContent = String(high);
    runtime.textContent = "24";
    overall.textContent = summary?.overall_summary || "所选日期暂无总结数据。";

    if (!periods.length) {
        periodsContainer.innerHTML = `
            <div class="md:col-span-2 bg-surface border border-dashed border-gray-200 p-8 rounded-xl text-center text-sm text-gray-500">
                所选日期暂无分时段总结，请重新选择日期或先生成当日分析数据。
            </div>
        `;
        return;
    }

    periodsContainer.innerHTML = periods
        .map((period) => {
            const meta = periodCardMeta(period.name);
            return `
                <div class="bg-surface p-6 rounded-xl shadow-soft border border-l-4 ${meta.border}">
                    <h3 class="font-bold text-lg text-gray-800 mb-3 flex items-center gap-2">
                        ${meta.icon}
                        ${escapeHtml(period.name)}总结 (${escapeHtml(period.time_range || "--")})
                    </h3>
                    <p class="text-gray-600 text-sm leading-relaxed whitespace-pre-line">${escapeHtml(period.summary || "暂无总结内容")}</p>
                    <div class="mt-4 flex flex-wrap gap-2">
                        <span class="px-2 py-1 rounded text-xs font-medium bg-gray-100 text-gray-600">事件 ${escapeHtml(period.event_count || 0)} 起</span>
                        <span class="px-2 py-1 rounded text-xs font-medium bg-red-50 text-red-600">高危 ${escapeHtml(period.high_count || 0)}</span>
                        <span class="px-2 py-1 rounded text-xs font-medium bg-yellow-50 text-yellow-700">中危 ${escapeHtml(period.medium_count || 0)}</span>
                        <span class="px-2 py-1 rounded text-xs font-medium bg-green-50 text-green-700">低危 ${escapeHtml(period.low_count || 0)}</span>
                    </div>
                </div>
            `;
        })
        .join("");
}

async function refreshOverview() {
    try {
        const overview = await requestJson("/api/overview");
        renderCameras(overview.cameras || []);
        renderTaskStatus(overview.task || {});
    } catch (error) {
        console.error(error);
    }
}

async function loadEvents() {
    const date = el("events-date")?.value || todayString();
    state.currentEventsDate = date;

    try {
        const events = await requestJson(`/api/events?date=${encodeURIComponent(date)}`);
        renderKeyframes(Array.isArray(events) ? events : []);
    } catch (error) {
        const container = el("keyframe-groups");
        if (container) {
            container.innerHTML = `
                <div class="md:col-span-2 bg-surface rounded-xl shadow-soft border border-dashed border-red-200 p-10 text-center text-sm text-red-500">
                    ${escapeHtml(error.message)}
                </div>
            `;
        }
    }
}

async function fetchSummary({ regenerate = false } = {}) {
    const date = el("summary-date")?.value || todayString();
    state.currentSummaryDate = date;
    const button = el("load-summary");

    if (button) {
        button.disabled = true;
        button.textContent = regenerate ? "正在生成..." : "正在加载...";
    }

    try {
        const result = regenerate
            ? await requestJson("/api/reports/daily", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                      date,
                      send_to_feishu: Boolean(el("send-feishu")?.checked),
                  }),
              })
            : await requestJson(`/api/summaries?date=${encodeURIComponent(date)}`);
        renderSummary(result);
    } catch (error) {
        renderSummary(null);
        const overall = el("summary-overall");
        if (overall) {
            overall.textContent = error.message;
        }
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = "重新生成";
        }
    }
}

async function startTask() {
    const button = el("run-task");
    if (!button) return;

    const duration = Number(el("duration-seconds")?.value || 30);
    button.disabled = true;
    button.textContent = "分析中...";

    try {
        const result = await requestJson("/api/tasks/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ duration_seconds: duration }),
        });

        renderTaskStatus({
            ...state.task,
            status: result.status || "running",
            message: result.message || "离线分析任务已启动。",
            duration_seconds: duration,
        });
        await refreshOverview();
    } catch (error) {
        renderTaskStatus({
            ...state.task,
            status: "failed",
            message: error.message,
        });
    } finally {
        button.disabled = false;
        button.textContent = "开始离线分析";
    }
}

function handleChatStreamEvent(event, sessionId, messageId) {
    if (!event || typeof event !== "object") return;

    if (event.type === "start") {
        updateChatMessage(sessionId, messageId, {
            loading: true,
            streaming: true,
            text: "",
            references: [],
        });
        return;
    }

    if (event.type === "delta") {
        appendChatMessageText(sessionId, messageId, event.text || "");
        return;
    }

    if (event.type === "done") {
        updateChatMessage(sessionId, messageId, {
            text: String(event.answer || ""),
            references: Array.isArray(event.references) ? event.references : [],
            loading: false,
            streaming: false,
        });
        return;
    }

    if (event.type === "error") {
        updateChatMessage(sessionId, messageId, {
            text: String(event.message || "查询失败，请稍后重试。"),
            references: [],
            loading: false,
            streaming: false,
        });
    }
}

async function requestChatStream({ question, history, sessionId, messageId }) {
    const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, history }),
    });

    if (!response.ok) {
        const message = await response.text();
        throw new Error(message || "请求失败，请稍后重试。");
    }

    if (!response.body) {
        throw new Error("浏览器不支持流式响应。");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let finalEvent = null;

    const flushBuffer = (force = false) => {
        const blocks = [];
        let boundaryIndex = buffer.indexOf("\n\n");
        while (boundaryIndex !== -1) {
            blocks.push(buffer.slice(0, boundaryIndex));
            buffer = buffer.slice(boundaryIndex + 2);
            boundaryIndex = buffer.indexOf("\n\n");
        }
        if (force && buffer.trim()) {
            blocks.push(buffer);
            buffer = "";
        }

        blocks.forEach((block) => {
            const data = block
                .split(/\r?\n/)
                .filter((line) => line.startsWith("data:"))
                .map((line) => line.slice(5).trimStart())
                .join("\n");
            if (!data) return;
            try {
                const parsed = JSON.parse(data);
                handleChatStreamEvent(parsed, sessionId, messageId);
                if (parsed.type === "done" || parsed.type === "error") {
                    finalEvent = parsed;
                }
            } catch (error) {
                console.warn("解析流式聊天事件失败", error, data);
            }
        });
    };

    while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        flushBuffer(done);
        if (done) break;
    }

    return finalEvent || { type: "done", answer: "", references: [] };
}

async function submitQuestion(question, options = {}) {
    const input = el("question-input");
    const clearInput = options?.clearInput !== false;

    if (!input) return null;
    if (state.chatBusy) return null;
    if (!getCurrentChatSession()) {
        startNewChatSession();
    }

    const session = getCurrentChatSession();
    const cleanQuestion = String(question || "").trim();
    if (!cleanQuestion) return null;
    const history = buildChatHistoryPayload(session);

    appendChatMessage("user", cleanQuestion, [], {}, session.id);
    const assistantMessageId = appendChatMessage("assistant", "", [], { loading: true, streaming: true }, session.id);
    if (clearInput) {
        input.value = "";
    }
    state.chatBusy = true;
    syncChatControls();

    try {
        const result = await requestChatStream({
            question: cleanQuestion,
            history,
            sessionId: session.id,
            messageId: assistantMessageId,
        });
        if (result?.type === "error") {
            return result;
        }

        if (speakReply && String(result?.answer || "").trim()) {
            void synthesizeAssistantSpeech(session.id, assistantMessageId, result.answer);
            /*
                setVoiceStatus("正在合成语音播报...", "processing");
                const speech = await requestSpeechSynthesis(result.answer);
                updateChatMessage(session.id, assistantMessageId, {
                    audioUrl: String(speech.audio_url || ""),
                });
                const played = await playMessageAudio(assistantMessageId);
                setVoiceStatus(
                    played ? "已完成语音播报。" : "语音已生成，点击播放器即可播报。",
                    played ? "success" : "processing"
                );
            } catch (error) {
                setVoiceStatus(error.message || "语音播报失败，请稍后重试。", "error");
            }
        }
        */
        }
        return result;
    } catch (error) {
        updateChatMessage(session.id, assistantMessageId, {
            text: `查询失败：${error.message}`,
            references: [],
            loading: false,
            streaming: false,
        });
        return { type: "error", message: error.message };
    } finally {
        state.chatBusy = false;
        syncChatControls();
        if (!state.voiceRecording && !state.voiceBusy) {
            input.focus();
        }
    }
}

async function askQuestion() {
    const input = el("question-input");
    if (!input) return;
    const userQuestion = input.value.trim();
    if (!userQuestion) return;
    setVoiceStatus("", "");
    await submitQuestion(userQuestion, { speakReply: true, clearInput: true });
    return;
    const button = el("ask-button");
    if (!input || !button) return;
    if (state.chatBusy) return;
    if (!getCurrentChatSession()) {
        startNewChatSession();
    }

    const session = getCurrentChatSession();
    const question = input.value.trim();
    if (!question) return;
    const history = buildChatHistoryPayload(session);

    appendChatMessage("user", question, [], {}, session.id);
    const assistantMessageId = appendChatMessage("assistant", "", [], { loading: true, streaming: true }, session.id);
    input.value = "";
    input.disabled = true;
    button.disabled = true;
    state.chatBusy = true;

    try {
        await requestChatStream({
            question,
            history,
            sessionId: session.id,
            messageId: assistantMessageId,
        });
    } catch (error) {
        updateChatMessage(session.id, assistantMessageId, {
            text: `查询失败：${error.message}`,
            references: [],
            loading: false,
            streaming: false,
        });
    } finally {
        state.chatBusy = false;
        input.disabled = false;
        button.disabled = false;
        input.focus();
    }
}

async function handleVoiceButtonClick() {
    if (state.chatBusy || state.voiceBusy) return;

    if (!state.voiceRecording) {
        try {
            await startVoiceRecording();
        } catch (error) {
            setVoiceStatus(error.message || "无法启动麦克风录音。", "error");
        }
        return;
    }

    try {
        state.voiceBusy = true;
        syncChatControls();
        setVoiceStatus("正在转写语音...", "processing");
        const audioBlob = await stopVoiceRecording({ submit: true });
        if (!audioBlob) {
            throw new Error("录音数据为空，请重试。");
        }

        const transcription = await requestVoiceTranscription(audioBlob);
        const transcript = String(transcription.transcript || transcription.text || "").trim();
        if (!transcript) {
            throw new Error("未识别到有效语音内容，请重试。");
        }

        const input = el("question-input");
        if (input) {
            input.value = transcript;
        }
        setVoiceStatus("语音识别完成，正在请求安防智能助理...", "processing");

        const result = await submitQuestion(transcript, {
            speakReply: true,
            fromVoice: true,
            clearInput: true,
        });

        if (result?.type === "error") {
            setVoiceStatus(result.message || "语音问答失败，请稍后重试。", "error");
        }
    } catch (error) {
        setVoiceStatus(error.message || "语音处理失败，请重试。", "error");
    } finally {
        state.voiceBusy = false;
        syncChatControls();
    }
}

function syncGlobalAudioPlayer(audioUrl = "") {
    const panel = el("tts-player-panel");
    const player = el("global-tts-player");
    if (!panel || !player) return null;

    const cleanUrl = String(audioUrl || "").trim();
    if (!cleanUrl) {
        panel.classList.add("hidden");
        player.removeAttribute("src");
        player.load();
        return player;
    }

    panel.classList.remove("hidden");
    if (player.getAttribute("src") !== cleanUrl) {
        player.setAttribute("src", cleanUrl);
        player.load();
    }
    bindAudioElement(player);
    return player;
}

async function playAudioUrl(audioUrl) {
    const player = syncGlobalAudioPlayer(audioUrl);
    if (!player || !String(audioUrl || "").trim()) return false;

    stopCurrentAudio();
    try {
        player.currentTime = 0;
        await player.play();
        return true;
    } catch (error) {
        console.warn("自动播放全局语音失败", error);
        return false;
    }
}

async function synthesizeAssistantSpeech(sessionId, messageId, answerText) {
    const cleanAnswer = String(answerText || "").trim();
    if (!cleanAnswer) return;

    try {
        setVoiceStatus("正在合成语音播报...", "processing");
        const speech = await requestSpeechSynthesis(cleanAnswer);
        const audioUrl = String(speech.audio_url || "").trim();

        updateChatMessage(sessionId, messageId, {
            audioUrl,
        });

        syncGlobalAudioPlayer(audioUrl);
        const played = await playAudioUrl(audioUrl) || await playMessageAudio(messageId);
        setVoiceStatus(
            played ? "已完成语音播报。" : "语音已生成，点击下方播放器即可播报。",
            played ? "success" : "processing"
        );
    } catch (error) {
        setVoiceStatus(error.message || "语音播报失败，请稍后重试。", "error");
    }
}

async function submitQuestion(question, options = {}) {
    const input = el("question-input");
    const speakReply = Boolean(options?.speakReply);
    const fromVoice = Boolean(options?.fromVoice);
    const clearInput = options?.clearInput !== false;

    if (!input) return null;
    if (state.chatBusy || (state.voiceBusy && !fromVoice)) return null;
    if (!getCurrentChatSession()) {
        startNewChatSession();
    }

    const session = getCurrentChatSession();
    const cleanQuestion = String(question || "").trim();
    if (!cleanQuestion) return null;
    const history = buildChatHistoryPayload(session);

    appendChatMessage("user", cleanQuestion, [], {}, session.id);
    const assistantMessageId = appendChatMessage("assistant", "", [], { loading: true, streaming: true }, session.id);
    if (clearInput) {
        input.value = "";
    }
    state.chatBusy = true;
    syncChatControls();

    try {
        const result = await requestChatStream({
            question: cleanQuestion,
            history,
            sessionId: session.id,
            messageId: assistantMessageId,
        });
        if (result?.type === "error") {
            return result;
        }
        return result;
    } catch (error) {
        updateChatMessage(session.id, assistantMessageId, {
            text: `查询失败：${error.message}`,
            references: [],
            loading: false,
            streaming: false,
        });
        return { type: "error", message: error.message };
    } finally {
        state.chatBusy = false;
        syncChatControls();
        input.focus();
    }
}

async function askQuestion() {
    const input = el("question-input");
    if (!input) return;
    const userQuestion = input.value.trim();
    if (!userQuestion) return;
    await submitQuestion(userQuestion, { clearInput: true });
}

function bindEvents() {
    el("run-task")?.addEventListener("click", startTask);
    el("events-date")?.addEventListener("change", loadEvents);
    el("summary-date")?.addEventListener("change", () => fetchSummary({ regenerate: false }));
    el("load-summary")?.addEventListener("click", () => fetchSummary({ regenerate: true }));
    el("new-chat-session")?.addEventListener("click", startNewChatSession);
    el("new-chat-session-large")?.addEventListener("click", startNewChatSession);
    el("ask-button")?.addEventListener("click", askQuestion);
    el("question-input")?.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            askQuestion();
        }
    });
}

function initDates() {
    const today = todayString();
    if (el("events-date")) {
        el("events-date").value = today;
    }
    if (el("summary-date")) {
        el("summary-date").value = today;
    }
    state.currentEventsDate = today;
    state.currentSummaryDate = today;
}

document.addEventListener("DOMContentLoaded", async () => {
    bindEvents();
    initDates();
    loadChatSessions();
    renderChatSessions();
    renderChatMessages();
    syncChatControls();
    switchTab("tab-live");
    updateCameraClocks();
    await refreshOverview();
    await loadEvents();
    await fetchSummary({ regenerate: false });
    window.setInterval(refreshOverview, 5000);
    window.setInterval(updateCameraClocks, 1000);
});
