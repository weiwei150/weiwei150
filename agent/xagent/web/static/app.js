(() => {
  "use strict";

  /* ------------------------------------------------------------------ */
  /* DOM                                                                */
  /* ------------------------------------------------------------------ */

  const els = {
    chat: document.getElementById("chat"),
    messages: document.getElementById("messages"),
    welcome: document.getElementById("welcome"),
    input: document.getElementById("input"),
    composer: document.getElementById("composer"),
    sendBtn: document.getElementById("sendBtn"),
    sendIcon: document.getElementById("sendIcon"),
    statusPill: document.getElementById("statusPill"),
    statusText: document.getElementById("statusText"),
    streamHint: document.getElementById("streamHint"),
    modelName: document.getElementById("modelName"),
    cwd: document.getElementById("cwd"),
    toolCount: document.getElementById("toolCount"),
    topModel: document.getElementById("topModel"),
    welcomeModel: document.getElementById("welcomeModel"),
    welcomeCwd: document.getElementById("welcomeCwd"),
    themeBtn: document.getElementById("themeBtn"),
    newChatBtn: document.getElementById("newChatBtn"),
    menuBtn: document.getElementById("menuBtn"),
    scrim: document.getElementById("scrim"),
    sidebar: document.getElementById("sidebar"),
    scrollBottom: document.getElementById("scrollBottom"),
    toast: document.getElementById("toast"),
  };

  /* ------------------------------------------------------------------ */
  /* State                                                              */
  /* ------------------------------------------------------------------ */

  const state = {
    sessionId: getSessionId(),
    model: "",
    directory: "",
    tools: [],
    streaming: false,
    abort: null,
    activeAssistant: null,
    activeAssistantRaw: "",
    toolCards: new Map(),
    toolSeq: 0,
    awaitingStarted: false,
    replaying: false,
    cancelledByUser: false,
    statusKind: "idle",
    autoScroll: true,
    toastTimer: 0,
    scrollFrame: 0,
  };

  /* ------------------------------------------------------------------ */
  /* Boot                                                               */
  /* ------------------------------------------------------------------ */

  init();

  function init() {
    const savedTheme = readLocal("xagent.theme");
    const preferredTheme = matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    applyTheme(savedTheme === "light" || savedTheme === "dark" ? savedTheme : preferredTheme);
    bindEvents();
    resizeInput();
    els.input.focus();
    bootstrap();
  }

  async function bootstrap() {
    try {
      const response = await apiFetch("/api/bootstrap");
      if (!response.ok) {
        throw new Error(await readError(response));
      }
      const data = await response.json();
      if (data.session_id) {
        state.sessionId = data.session_id;
        writeSession("xagent.session", data.session_id);
      }
      state.model = data.model || "unknown";
      state.directory = data.directory || "";
      state.tools = Array.isArray(data.tools) ? data.tools : [];
      updateMeta();
      if (Array.isArray(data.history) && data.history.length > 0) {
        replayHistory(data.history);
      }
      setStatus("就绪", "idle");
    } catch (error) {
      setStatus("连接失败", "error");
      addError(`无法连接服务端：${error.message || error}`);
    }
  }

  function updateMeta() {
    els.modelName.textContent = state.model || "—";
    els.cwd.textContent = state.directory || "—";
    els.cwd.title = state.directory || "";
    els.toolCount.textContent = state.tools.length ? `${state.tools.length} 个` : "—";
    els.topModel.textContent = state.model || "—";
    els.welcomeModel.textContent = state.model || "—";
    els.welcomeCwd.textContent = state.directory || "—";
    els.welcomeCwd.title = state.directory || "";
  }

  function replayHistory(history) {
    hideWelcome();
    state.replaying = true;
    for (const item of history) {
      try {
        handleEvent(item);
      } catch (error) {
        console.warn("无法恢复历史事件", item, error);
      }
    }
    state.replaying = false;
    finishAssistant();
    setStatus("就绪", "idle");
    scrollToBottom(true);
  }

  /* ------------------------------------------------------------------ */
  /* Sending                                                            */
  /* ------------------------------------------------------------------ */

  async function sendPrompt(rawText) {
    const text = String(rawText || "").trim();
    if (!text) {
      return;
    }
    if (state.streaming) {
      showToast("当前回复还在生成，按 Esc 或点击停止");
      return;
    }

    hideWelcome();
    addUserMessage(text);
    els.input.value = "";
    resizeInput();
    state.streaming = true;
    state.awaitingStarted = true;
    state.cancelledByUser = false;
    state.autoScroll = true;
    setStreamingUI(true);
    setStatus("思考中…", "busy");
    setStreamHint("正在生成回复…");
    scrollToBottom(true);

    state.abort = new AbortController();
    try {
      const response = await apiFetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text }),
        signal: state.abort.signal,
      });
      if (!response.ok) {
        throw new Error(await readError(response));
      }
      await consumeSSE(response);
    } catch (error) {
      if (error.name !== "AbortError") {
        finishAssistant();
        addError(error.message || String(error));
        setStatus("出错", "error");
      }
    } finally {
      state.awaitingStarted = false;
      state.streaming = false;
      state.abort = null;
      setStreamingUI(false);
      setStreamHint("");
      if (state.statusKind !== "error") {
        setStatus("就绪", "idle");
      }
      state.cancelledByUser = false;
      scrollToBottom();
      els.input.focus();
    }
  }

  function cancelStream() {
    if (!state.streaming) {
      return;
    }
    state.cancelledByUser = true;
    state.abort?.abort();
    finishAssistant();
    addSystem("已取消当前请求。", "◌");
    setStatus("就绪", "idle");
    setStreamHint("");
  }

  async function newChat() {
    if (state.streaming) {
      cancelStream();
      await sleep(220);
    }

    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const response = await apiFetch("/api/reset", { method: "POST" });
        if (response.ok) {
          clearConversation();
          showToast("已开始新会话");
          return;
        }
        if (response.status === 409) {
          await sleep(260);
          continue;
        }
        showToast(`无法新建会话：${await readError(response)}`);
        return;
      } catch (error) {
        showToast(`无法新建会话：${error.message || error}`);
        return;
      }
    }
    showToast("任务仍在取消中，请稍后再试");
  }

  function clearConversation() {
    els.messages.replaceChildren();
    els.welcome.hidden = false;
    state.activeAssistant = null;
    state.activeAssistantRaw = "";
    state.toolCards.clear();
    state.awaitingStarted = false;
    state.replaying = false;
    state.autoScroll = true;
    setStatus("就绪", "idle");
    setStreamHint("");
    els.input.value = "";
    resizeInput();
    els.chat.scrollTop = 0;
    updateScrollButton();
    els.input.focus();
  }

  /* ------------------------------------------------------------------ */
  /* SSE                                                                */
  /* ------------------------------------------------------------------ */

  async function consumeSSE(response) {
    if (!response.body) {
      throw new Error("浏览器不支持流式响应");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const chunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const event = parseSSEChunk(chunk);
        if (event) {
          handleEvent(event);
        }
        boundary = buffer.indexOf("\n\n");
      }
    }

    buffer += decoder.decode();
    if (buffer.trim()) {
      const event = parseSSEChunk(buffer);
      if (event) {
        handleEvent(event);
      }
    }
  }

  function parseSSEChunk(chunk) {
    let eventType = "message";
    const dataLines = [];
    for (const line of chunk.split("\n")) {
      if (!line || line.startsWith(":")) {
        continue;
      }
      if (line.startsWith("event:")) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (dataLines.length === 0) {
      return null;
    }
    try {
      const item = JSON.parse(dataLines.join("\n"));
      return {
        type: item.type || eventType,
        data: item.data || {},
        at: item.at || 0,
      };
    } catch (error) {
      console.warn("无法解析 SSE 数据", chunk, error);
      return null;
    }
  }

  /* ------------------------------------------------------------------ */
  /* Events                                                             */
  /* ------------------------------------------------------------------ */

  function handleEvent(event) {
    const data = event.data || {};
    switch (event.type) {
      case "started":
        if (state.awaitingStarted && !state.replaying) {
          state.awaitingStarted = false;
        } else {
          addUserMessage(data.prompt || "", event.at);
        }
        hideWelcome();
        break;

      case "text":
        handleText(data.text || "", event.at);
        break;

      case "tool_start":
        handleToolStart(data, event.at);
        break;

      case "tool_end":
        handleToolEnd(data, event.at);
        break;

      case "done":
        handleDone(data, event.at);
        break;

      case "error":
        finishAssistant();
        addError(data.message || "请求失败");
        setStatus("出错", "error");
        setStreamHint("");
        break;

      case "cancelled":
        finishAssistant();
        addSystem("已取消当前请求。", "◌");
        setStatus("就绪", "idle");
        setStreamHint("");
        break;

      default:
        break;
    }
  }

  function handleText(text, at) {
    hideWelcome();
    const assistant = ensureAssistant(at);
    state.activeAssistantRaw += text;
    assistant.body.textContent = state.activeAssistantRaw;
    assistant.body.classList.add("streaming");
    setStatus("思考中…", "busy");
    setStreamHint("正在生成回复…");
    scrollToBottom();
  }

  function handleToolStart(data, at) {
    finishAssistant();
    addToolCard(data, at);
    hideWelcome();
    const name = data.name || "tool";
    setStatus(`执行工具 · ${name}`, "busy");
    setStreamHint(`正在执行 ${name}…`);
  }

  function handleToolEnd(data, at) {
    const card = state.toolCards.get(data.id);
    if (card) {
      finishToolCard(card, data);
    } else {
      const created = addToolCard(
        {
          id: data.id,
          name: data.name || "tool",
          raw: "",
          arguments: null,
        },
        at,
      );
      finishToolCard(created, data);
    }
    setStatus("思考中…", "busy");
    setStreamHint("正在整理工具结果…");
    scrollToBottom();
  }

  function handleDone(data, at) {
    if (state.activeAssistant) {
      finishAssistant();
    } else if (data.content) {
      const assistant = ensureAssistant(at);
      state.activeAssistantRaw = data.content;
      finishAssistant();
    }

    if (!data.content && !data.tool_calls) {
      addSystem("本轮没有返回文本内容。", "ℹ");
    }
    setStatus("就绪", "idle");
    setStreamHint("");
    scrollToBottom();
  }

  /* ------------------------------------------------------------------ */
  /* Message rendering                                                  */
  /* ------------------------------------------------------------------ */

  function addUserMessage(text, at) {
    const shell = createMessageShell("user", "你", "你", at);
    shell.body.innerHTML = renderMarkdown(text);
    scrollToBottom();
    return shell;
  }

  function ensureAssistant(at) {
    if (state.activeAssistant) {
      return state.activeAssistant;
    }
    const shell = createMessageShell("assistant", "✦", "XAgent", at);
    shell.body.classList.add("markdown", "streaming");
    state.activeAssistant = shell;
    state.activeAssistantRaw = "";
    return shell;
  }

  function finishAssistant() {
    const assistant = state.activeAssistant;
    if (!assistant) {
      state.activeAssistantRaw = "";
      return;
    }
    assistant.body.classList.remove("streaming");
    const text = state.activeAssistantRaw;
    assistant.body.innerHTML = renderMarkdown(text || "（无文本回复）");
    state.activeAssistant = null;
    state.activeAssistantRaw = "";
  }

  function createMessageShell(role, icon, name, at) {
    const root = document.createElement("div");
    root.className = `msg ${role}`;

    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = icon;

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    const head = document.createElement("div");
    head.className = "msg-head";

    const nameEl = document.createElement("span");
    nameEl.className = "msg-name";
    nameEl.textContent = name;

    const timeEl = document.createElement("span");
    timeEl.className = "msg-time";
    timeEl.textContent = formatTime(at);

    const body = document.createElement("div");
    body.className = "msg-body";

    head.append(nameEl, timeEl);
    bubble.append(head, body);
    root.append(avatar, bubble);
    els.messages.append(root);
    return { root, bubble, body, timeEl };
  }

  function addSystem(text, icon = "ℹ") {
    const notice = document.createElement("div");
    notice.className = "notice";
    const iconEl = document.createElement("span");
    iconEl.className = "notice-icon";
    iconEl.textContent = icon;
    const textEl = document.createElement("span");
    textEl.textContent = text;
    notice.append(iconEl, textEl);
    els.messages.append(notice);
    scrollToBottom();
  }

  function addError(text) {
    const notice = document.createElement("div");
    notice.className = "notice error";
    const iconEl = document.createElement("span");
    iconEl.className = "notice-icon";
    iconEl.textContent = "✖";
    const textEl = document.createElement("span");
    textEl.textContent = text;
    notice.append(iconEl, textEl);
    els.messages.append(notice);
    scrollToBottom();
  }

  /* ------------------------------------------------------------------ */
  /* Tool cards                                                         */
  /* ------------------------------------------------------------------ */

  function addToolCard(data, at) {
    const name = data.name || "tool";
    const shell = createMessageShell("tool", "⚙", "工具调用", at);
    shell.body.classList.add("tool-body");

    const card = document.createElement("div");
    card.className = "tool-card";
    card.dataset.status = "pending";

    const head = document.createElement("div");
    head.className = "tool-head";

    const nameEl = document.createElement("span");
    nameEl.className = "tool-name";
    nameEl.textContent = name;

    const statusEl = document.createElement("span");
    statusEl.className = "tool-status";
    statusEl.dataset.status = "pending";
    statusEl.textContent = "执行中";

    const summaryEl = document.createElement("div");
    summaryEl.className = "tool-summary";
    const brief = summarizeArguments(data.arguments, data.raw);
    summaryEl.textContent = brief ? `正在执行 · ${brief}` : "正在执行…";

    const details = document.createElement("details");
    details.className = "tool-details";
    const summary = document.createElement("summary");
    const chevron = document.createElement("span");
    chevron.className = "tool-chevron";
    chevron.textContent = "▸";
    const detailsLabel = document.createElement("span");
    detailsLabel.textContent = "参数与结果";
    summary.append(chevron, detailsLabel);

    const detailBody = document.createElement("div");
    detailBody.className = "tool-detail-body";
    appendDetail(detailBody, "参数", formatArguments(data.arguments, data.raw));

    details.append(summary, detailBody);
    head.append(nameEl, statusEl);
    card.append(head, summaryEl, details);
    shell.body.append(card);

    const key = data.id || `tool-${(state.toolSeq += 1)}`;
    const record = {
      shell,
      card,
      statusEl,
      summaryEl,
      detailBody,
      name,
      hasResult: false,
    };
    state.toolCards.set(key, record);
    scrollToBottom();
    return record;
  }

  function finishToolCard(record, data) {
    const ok = Boolean(data.success);
    record.card.dataset.status = ok ? "ok" : "error";
    record.statusEl.dataset.status = ok ? "ok" : "error";
    record.statusEl.textContent = ok ? "完成" : "失败";
    record.summaryEl.textContent = summarizeResult(ok, data.payload, data.content);

    if (!record.hasResult) {
      appendDetail(record.detailBody, "结果", formatResult(data.content, data.payload));
      record.hasResult = true;
    }
    if (!ok) {
      record.card.querySelector("details").open = true;
    }
  }

  function appendDetail(container, label, text) {
    const labelEl = document.createElement("div");
    labelEl.className = "tool-detail-label";
    labelEl.textContent = label;
    const pre = document.createElement("pre");
    pre.textContent = text;
    container.append(labelEl, pre);
  }

  function summarizeArguments(argumentsObject, raw) {
    if (argumentsObject && typeof argumentsObject === "object") {
      const parts = [];
      for (const key of ["path", "directory", "filename", "source", "destination"]) {
        if (argumentsObject[key] !== undefined && argumentsObject[key] !== null) {
          parts.push(`${key}=${argumentsObject[key]}`);
        }
      }
      if (parts.length > 0) {
        return truncate(parts.join(" · "), 120);
      }
      try {
        return truncate(JSON.stringify(argumentsObject), 120);
      } catch {
        return "";
      }
    }
    return truncate(String(raw || "").replace(/\s+/g, " "), 120);
  }

  function summarizeResult(success, payload, content) {
    if (!success) {
      const error = (payload && payload.error) || content || "执行失败";
      return `✗ ${truncate(String(error).replace(/\s+/g, " "), 160)}`;
    }

    const parts = [];
    if (payload && typeof payload === "object") {
      if (payload.count !== undefined) {
        parts.push(`共 ${payload.count} 项`);
      }
      if (payload.deleted_files !== undefined) {
        parts.push(`删除 ${payload.deleted_files} 个文件`);
      }
      if (payload.replaced !== undefined) {
        parts.push(`替换 ${payload.replaced} 处`);
      }
      if (payload.datetime !== undefined) {
        parts.push(String(payload.datetime));
      }
      if (parts.length === 0 && payload.path !== undefined) {
        parts.push(String(payload.path));
      }
      if (parts.length === 0 && payload.directory !== undefined) {
        parts.push(String(payload.directory));
      }
    }
    if (parts.length === 0) {
      parts.push("执行成功");
    }
    return `✓ ${truncate(parts.join(" · "), 160)}`;
  }

  function formatArguments(argumentsObject, raw) {
    if (argumentsObject && typeof argumentsObject === "object") {
      try {
        return JSON.stringify(argumentsObject, null, 2);
      } catch {
        return String(argumentsObject);
      }
    }
    const text = String(raw || "").trim();
    return text || "(无参数)";
  }

  function formatResult(content, payload) {
    const text = String(content || "").trim();
    if (text) {
      try {
        return JSON.stringify(JSON.parse(text), null, 2);
      } catch {
        return text;
      }
    }
    if (payload && typeof payload === "object") {
      try {
        return JSON.stringify(payload, null, 2);
      } catch {
        return String(payload);
      }
    }
    return "(无内容)";
  }

  /* ------------------------------------------------------------------ */
  /* Markdown                                                           */
  /* ------------------------------------------------------------------ */

  const ESCAPES = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => ESCAPES[character]);
  }

  function renderMarkdown(source) {
    if (!source) {
      return "";
    }

    const codeBlocks = [];
    let text = String(source).replace(/\r\n?/g, "\n");
    text = text.replace(/```([\w#+.-]*)[ \t]*\n([\s\S]*?)```/g, (_, language, code) => {
      const index = codeBlocks.length;
      codeBlocks.push({ language: language || "", code: code.replace(/\n$/, "") });
      return `\n\n\u0000CODE${index}\u0000\n\n`;
    });

    const lines = text.split("\n");
    const html = [];
    let paragraph = [];
    let list = null;

    const flushParagraph = () => {
      if (paragraph.length === 0) {
        return;
      }
      html.push(`<p>${paragraph.join("<br>")}</p>`);
      paragraph = [];
    };

    const flushList = () => {
      if (!list) {
        return;
      }
      html.push(
        `<${list.type}>${list.items.map((item) => `<li>${item}</li>`).join("")}</${list.type}>`,
      );
      list = null;
    };

    const flushAll = () => {
      flushParagraph();
      flushList();
    };

    for (const rawLine of lines) {
      const line = rawLine.trimEnd();
      const trimmed = line.trim();

      const codeMatch = trimmed.match(/^\u0000CODE(\d+)\u0000$/);
      if (codeMatch) {
        flushAll();
        const block = codeBlocks[Number(codeMatch[1])];
        if (block) {
          html.push(renderCodeBlock(block));
        }
        continue;
      }

      if (!trimmed) {
        flushAll();
        continue;
      }

      const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        flushAll();
        const level = heading[1].length;
        html.push(`<h${level}>${renderInline(escapeHtml(heading[2]))}</h${level}>`);
        continue;
      }

      if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
        flushAll();
        html.push("<hr>");
        continue;
      }

      const quote = trimmed.match(/^>\s?(.*)$/);
      if (quote) {
        flushAll();
        html.push(`<blockquote>${renderInline(escapeHtml(quote[1]))}</blockquote>`);
        continue;
      }

      const unordered = trimmed.match(/^[-*+]\s+(.*)$/);
      if (unordered) {
        flushParagraph();
        if (!list || list.type !== "ul") {
          flushList();
          list = { type: "ul", items: [] };
        }
        list.items.push(renderInline(escapeHtml(unordered[1])));
        continue;
      }

      const ordered = trimmed.match(/^\d+[.)]\s+(.*)$/);
      if (ordered) {
        flushParagraph();
        if (!list || list.type !== "ol") {
          flushList();
          list = { type: "ol", items: [] };
        }
        list.items.push(renderInline(escapeHtml(ordered[1])));
        continue;
      }

      flushList();
      paragraph.push(renderInline(escapeHtml(line)));
    }

    flushAll();

    return html
      .join("")
      .replace(/\u0000CODE(\d+)\u0000/g, (_, index) => {
        const block = codeBlocks[Number(index)];
        return block ? renderCodeBlock(block) : "";
      });
  }

  function renderInline(escapedText) {
    const inlineCodes = [];
    let text = escapedText.replace(/`([^`\n]+)`/g, (_, code) => {
      const index = inlineCodes.length;
      inlineCodes.push(`<code>${code}</code>`);
      return `\u0001IC${index}\u0001`;
    });

    text = text.replace(
      /\[([^\]]+)\]\(([^)\s]+)\)/g,
      (_, label, url) => {
        const safeUrl = /^(https?:\/\/|mailto:)/i.test(url) ? url : "#";
        return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${label}</a>`;
      },
    );
    text = text.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,!?:;]|$)/g, "$1<em>$2</em>");
    text = text.replace(/\u0001IC(\d+)\u0001/g, (_, index) => inlineCodes[Number(index)]);
    return text;
  }

  function renderCodeBlock(block) {
    const language = block.language ? escapeHtml(block.language) : "code";
    return (
      '<div class="code-block">' +
      '<div class="code-head">' +
      `<span>${language}</span>` +
      '<button type="button" class="copy-btn">复制</button>' +
      "</div>" +
      `<pre><code>${escapeHtml(block.code)}</code></pre>` +
      "</div>"
    );
  }

  /* ------------------------------------------------------------------ */
  /* Status & UI                                                        */
  /* ------------------------------------------------------------------ */

  function setStatus(text, kind) {
    state.statusKind = kind;
    els.statusPill.dataset.kind = kind;
    els.statusText.textContent = text;
    els.chat.setAttribute("aria-busy", kind === "busy" ? "true" : "false");
  }

  function setStreamHint(text) {
    els.streamHint.textContent = text;
  }

  function setStreamingUI(streaming) {
    els.sendBtn.classList.toggle("stop", streaming);
    els.sendBtn.setAttribute("aria-label", streaming ? "停止生成" : "发送");
    els.sendBtn.title = streaming ? "停止生成" : "发送";
    els.sendIcon.textContent = streaming ? "■" : "↑";
  }

  function showToast(message) {
    clearTimeout(state.toastTimer);
    els.toast.textContent = message;
    els.toast.classList.add("visible");
    state.toastTimer = window.setTimeout(() => {
      els.toast.classList.remove("visible");
    }, 2400);
  }

  function hideWelcome() {
    els.welcome.hidden = true;
  }

  function isNearBottom() {
    return els.chat.scrollHeight - els.chat.scrollTop - els.chat.clientHeight < 90;
  }

  function scrollToBottom(force = false) {
    if (!force && !state.autoScroll) {
      updateScrollButton();
      return;
    }
    if (state.scrollFrame) {
      return;
    }
    state.scrollFrame = requestAnimationFrame(() => {
      state.scrollFrame = 0;
      els.chat.scrollTop = els.chat.scrollHeight;
      updateScrollButton();
    });
  }

  function updateScrollButton() {
    els.scrollBottom.classList.toggle("visible", !isNearBottom());
  }

  /* ------------------------------------------------------------------ */
  /* Events / helpers                                                   */
  /* ------------------------------------------------------------------ */

  function bindEvents() {
    els.composer.addEventListener("submit", (event) => {
      event.preventDefault();
      if (state.streaming) {
        cancelStream();
        return;
      }
      sendPrompt(els.input.value);
    });

    els.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        if (state.streaming) {
          showToast("正在生成回复，按 Esc 或点击停止");
          return;
        }
        sendPrompt(els.input.value);
      }
    });

    els.input.addEventListener("input", resizeInput);

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && state.streaming) {
        event.preventDefault();
        cancelStream();
      }
    });

    document.addEventListener("click", (event) => {
      const promptButton = event.target.closest("[data-prompt]");
      if (!promptButton) {
        return;
      }
      const prompt = promptButton.dataset.prompt || "";
      if (state.streaming) {
        showToast("当前回复还在生成，按 Esc 或点击停止");
        return;
      }
      closeSidebar();
      els.input.value = prompt;
      resizeInput();
      els.input.focus();
      sendPrompt(prompt);
    });

    els.newChatBtn.addEventListener("click", newChat);

    els.themeBtn.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(next);
    });

    els.menuBtn.addEventListener("click", () => {
      document.body.classList.toggle("sidebar-open");
    });

    els.scrim.addEventListener("click", closeSidebar);

    els.scrollBottom.addEventListener("click", () => {
      state.autoScroll = true;
      scrollToBottom(true);
    });

    els.chat.addEventListener("scroll", () => {
      state.autoScroll = isNearBottom();
      updateScrollButton();
    }, { passive: true });

    els.messages.addEventListener("click", async (event) => {
      const copyButton = event.target.closest(".copy-btn");
      if (!copyButton) {
        return;
      }
      const code = copyButton.closest(".code-block")?.querySelector("code")?.textContent || "";
      try {
        await copyText(code);
        copyButton.textContent = "已复制";
        window.setTimeout(() => {
          copyButton.textContent = "复制";
        }, 1400);
      } catch {
        showToast("复制失败，请手动选择代码");
      }
    });

    window.addEventListener("resize", updateScrollButton);
  }

  function resizeInput() {
    els.input.style.height = "auto";
    els.input.style.height = `${Math.min(els.input.scrollHeight, 180)}px`;
  }

  function closeSidebar() {
    document.body.classList.remove("sidebar-open");
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    writeLocal("xagent.theme", theme);
    els.themeBtn.textContent = theme === "dark" ? "☀" : "☾";
    els.themeBtn.title = theme === "dark" ? "切换到亮色主题" : "切换到暗色主题";
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute("content", theme === "dark" ? "#080b10" : "#f3f6fb");
    }
  }

  /* ------------------------------------------------------------------ */
  /* Utilities                                                          */
  /* ------------------------------------------------------------------ */

  function apiFetch(path, options = {}) {
    const headers = {
      "X-Session-Id": state.sessionId,
      ...(options.headers || {}),
    };
    return fetch(path, { ...options, headers });
  }

  async function readError(response) {
    try {
      const data = await response.json();
      return data.error || data.detail || `HTTP ${response.status}`;
    } catch {
      return `HTTP ${response.status}`;
    }
  }

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.append(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }

  function truncate(text, limit) {
    const value = String(text || "");
    return value.length > limit ? `${value.slice(0, limit - 1)}…` : value;
  }

  function formatTime(at) {
    const date = at ? new Date(at * 1000) : new Date();
    return date.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function getSessionId() {
    const existing = readSession("xagent.session");
    if (existing) {
      return existing;
    }
    const id = typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
    writeSession("xagent.session", id);
    return id;
  }

  function readSession(key) {
    try {
      return window.sessionStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function writeSession(key, value) {
    try {
      window.sessionStorage.setItem(key, value);
    } catch {
      /* 隐私模式下忽略存储失败 */
    }
  }

  function readLocal(key) {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function writeLocal(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch {
      /* 隐私模式下忽略存储失败 */
    }
  }
})();
