(() => {
  function getCookie(name) {
    const cookies = document.cookie ? document.cookie.split(";") : [];
    for (const cookie of cookies) {
      const trimmed = cookie.trim();
      if (trimmed.startsWith(`${name}=`)) {
        return decodeURIComponent(trimmed.substring(name.length + 1));
      }
    }
    return null;
  }

  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatAssistantText(text) {
    return escapeHtml(text).replace(/\n/g, "<br>");
  }

  class ChatController {
    constructor(root) {
      this.root = root;
      this.mode = root.dataset.chatStyle || "fullpage";
      this.form = root.querySelector("[data-chat-form]");
      this.messagesEl = root.querySelector("[data-chat-messages]");
      this.inputEl = this.form ? this.form.querySelector("textarea[name='prompt']") : null;
      this.statusEl = root.querySelector("[data-chat-status]");
      this.errorEl = root.querySelector("[data-chat-error]");
      this.historyContainer = root.querySelector("[data-chat-history]");
      this.scrollWrapper = root.querySelector("[data-chat-scroll]") || this.messagesEl;
      this.conversationInput = this.form ? this.form.querySelector("[data-chat-conversation-input]") : null;
      this.sendUrl = root.dataset.sendUrl || "";
      this.historyUrl = root.dataset.historyUrl || "";
      this.newUrl = root.dataset.newUrl || "";
      this.conversationId = root.dataset.conversationId || "";
      this.initialPrompt = root.dataset.initialPrompt || "";
      this.isStreaming = false;
      this.activeAssistant = null;
    }

    connect() {
      if (!this.form || !this.messagesEl || !this.sendUrl) {
        return;
      }

      this.form.addEventListener("submit", (event) => {
        event.preventDefault();
        const prompt = (this.inputEl?.value || "").trim();
        if (prompt) {
          this.sendPrompt(prompt);
        }
      });

      this.bindSuggestionButtons();
      this.bindResetButtons();
      this.conversationId = this.conversationId || this.conversationInput?.value || "";
      this.checkInitialMode();

      if (this.initialPrompt) {
        const prompt = this.initialPrompt;
        this.initialPrompt = "";
        this.root.dataset.initialPrompt = "";
        this.fillInput(prompt);
        setTimeout(() => this.sendPrompt(prompt), 300);
      }
    }

    bindSuggestionButtons() {
      this.root.querySelectorAll("[data-chat-suggestion]").forEach((button) => {
        button.addEventListener("click", () => {
          const suggestion = button.getAttribute("data-chat-suggestion");
          if (!suggestion) {
            return;
          }
          this.fillInput(suggestion);
          this.sendPrompt(suggestion);
        });
      });
    }

    bindResetButtons() {
      this.root.querySelectorAll("[data-chat-reset]").forEach((button) => {
        button.addEventListener("click", () => {
          this.startNewConversation();
        });
      });
    }

    fillInput(text) {
      if (!this.inputEl) return;
      this.inputEl.value = text;
      this.inputEl.focus();
    }

    checkInitialMode() {
      const hasMessages = this.messagesEl && this.messagesEl.children.length > 0;
      if (hasMessages) {
        this.switchToConversationMode();
      }
    }

    updateStatus(message) {
      if (this.statusEl) {
        this.statusEl.textContent = message;
      }
    }

    showError(message) {
      if (this.errorEl) {
        this.errorEl.textContent = message;
      }
    }

    clearError() {
      if (this.errorEl) {
        this.errorEl.textContent = "";
      }
    }

    setConversationId(conversationId) {
      this.conversationId = conversationId || "";
      this.root.dataset.conversationId = this.conversationId;
      if (this.conversationInput) {
        this.conversationInput.value = this.conversationId;
      }
    }

    appendUserMessage(text) {
      this.clearPlaceholders();
      const container = document.createElement("div");
      container.className = this.getMessageClass("user");
      container.dataset.role = "user";

      const avatar = document.createElement("div");
      avatar.className = this.getAvatarClass("user");
      avatar.textContent = "U";

      const body = document.createElement("div");
      body.className = this.getMessageBodyClass();
      body.innerHTML = escapeHtml(text).replace(/\n/g, "<br>");

      container.appendChild(avatar);
      container.appendChild(body);
      this.messagesEl.appendChild(container);
      this.scrollToBottom();
    }

    createAssistantBubble() {
      this.clearPlaceholders();
      const container = document.createElement("div");
      container.className = this.getMessageClass("assistant");
      container.dataset.role = "assistant";

      const avatar = document.createElement("div");
      avatar.className = this.getAvatarClass("assistant");
      avatar.textContent = "A";

      const body = document.createElement("div");
      body.className = this.getMessageBodyClass();

      const content = document.createElement("div");
      content.className = "chat-content";
      content.innerHTML = "<span class='chat-thinking'>Thinking…</span>";
      body.appendChild(content);

      const sources = document.createElement("div");
      sources.className = "chat-sources chat-sources--hidden";
      body.appendChild(sources);

      container.appendChild(avatar);
      container.appendChild(body);
      this.messagesEl.appendChild(container);
      this.scrollToBottom();

      return { element: container, contentEl: content, sourcesEl: sources, buffer: "" };
    }

    getMessageClass(role) {
      const baseClasses = "chat-message";
      if (this.mode === "widget") {
        return `${baseClasses} chat-message--${role} chat-message--widget`;
      }
      return `${baseClasses} chat-message--${role}`;
    }

    getAvatarClass(role) {
      return `chat-avatar chat-avatar--${role}`;
    }

    getMessageBodyClass() {
      if (this.mode === "widget") {
        return "chat-message-body chat-message-body--widget";
      }
      return "chat-message-body";
    }

    updateAssistantContent(assistant, text) {
      assistant.buffer = text;
      assistant.contentEl.innerHTML = formatAssistantText(text);
      this.scrollToBottom();
    }

    updateAssistantSources(assistant, sources) {
      if (!assistant.sourcesEl) return;
      assistant.sourcesEl.innerHTML = "";
      if (!sources || !sources.length) {
        assistant.sourcesEl.classList.add("chat-sources--hidden");
        return;
      }
      assistant.sourcesEl.classList.remove("chat-sources--hidden");
      sources.forEach((source, index) => {
        const chip = document.createElement("span");
        chip.className = "chat-source-chip";

        const badge = document.createElement("span");
        badge.textContent = `#${index + 1}`;
        chip.appendChild(badge);

        if (source.parcel_number) {
          const parcel = document.createElement("span");
          parcel.textContent = source.parcel_number;
          chip.appendChild(parcel);
        }
        if (source.address) {
          const addr = document.createElement("span");
          addr.className = "chat-source-address";
          addr.textContent = source.address;
          chip.appendChild(addr);
        }
        if (typeof source.distance === "number") {
          const distance = document.createElement("span");
          distance.textContent = `${source.distance.toFixed(2)}mi`;
          chip.appendChild(distance);
        }

        assistant.sourcesEl.appendChild(chip);
      });
    }

    async startNewConversation() {
      if (!this.newUrl) return;
      try {
        this.updateStatus("Starting a new conversation…");
        const response = await fetch(this.newUrl, {
          method: "POST",
          headers: {
            "X-CSRFToken": getCookie("csrftoken") || "",
            Accept: "application/json",
          },
        });

        if (!response.ok) {
          throw new Error("Unable to start a new chat right now.");
        }
        const data = await response.json();
        this.setConversationId(data.conversation_id);
        this.messagesEl.innerHTML = "";
        this.updateStatus("Ready when you are.");
        this.clearError();
        this.switchToHeroMode();
        if (this.inputEl) {
          this.inputEl.value = "";
        }
        if (this.historyUrl) {
          this.refreshHistory();
        }
      } catch (error) {
        this.showError(error.message || "Unable to reset the conversation.");
      }
    }

    clearPlaceholders() {
      if (!this.messagesEl) return;
      this.messagesEl.querySelectorAll("[data-chat-placeholder]").forEach((node) => node.remove());
      this.switchToConversationMode();
    }

    switchToConversationMode() {
      const mainEl = document.querySelector('.main');
      const heroModeWrapper = document.querySelector('.hero-mode');
      const heroSection = document.querySelector('.hero');
      const suggestionsEl = document.querySelector('[data-suggestions]');
      const toolsSection = document.querySelector('.tools-section');

      if (mainEl) {
        mainEl.classList.remove('hero-mode');
        mainEl.classList.add('conversation-mode');
      }

      if (heroModeWrapper) {
        heroModeWrapper.style.minHeight = 'auto';
        heroModeWrapper.style.display = 'block';
      }

      if (heroSection) {
        heroSection.style.display = 'none';
      }

      if (suggestionsEl) {
        suggestionsEl.style.display = 'none';
      }

      if (toolsSection) {
        toolsSection.style.display = 'block';
      }

      if (this.messagesEl) {
        this.messagesEl.style.display = 'flex';
      }
    }

    switchToHeroMode() {
      const mainEl = document.querySelector('.main');
      const heroModeWrapper = document.querySelector('.hero-mode');
      const heroSection = document.querySelector('.hero');
      const suggestionsEl = document.querySelector('[data-suggestions]');
      const toolsSection = document.querySelector('.tools-section');

      if (mainEl) {
        mainEl.classList.add('hero-mode');
        mainEl.classList.remove('conversation-mode');
      }

      if (heroModeWrapper) {
        heroModeWrapper.style.minHeight = 'calc(100vh - 80px)';
        heroModeWrapper.style.display = 'flex';
      }

      if (heroSection) {
        heroSection.style.display = 'block';
      }

      if (suggestionsEl) {
        suggestionsEl.style.display = 'grid';
      }

      if (toolsSection) {
        toolsSection.style.display = 'none';
      }

      if (this.messagesEl) {
        this.messagesEl.style.display = 'none';
      }
    }

    async sendPrompt(prompt) {
      if (!prompt || this.isStreaming) {
        return;
      }

      this.isStreaming = true;
      this.clearError();
      this.appendUserMessage(prompt);
      this.updateStatus("Contacting OpenAI…");
      this.activeAssistant = this.createAssistantBubble();

      const formData = new FormData(this.form);
      formData.set("prompt", prompt);
      if (this.conversationId) {
        formData.set("conversation_id", this.conversationId);
      }

      if (this.inputEl) {
        this.inputEl.value = "";
        this.resizeInput();
      }

      try {
        const response = await fetch(this.sendUrl, {
          method: "POST",
          body: formData,
          headers: {
            "X-CSRFToken": getCookie("csrftoken") || "",
          },
        });

        if (!response.ok) {
          throw new Error("The assistant is unavailable. Try again in a moment.");
        }

        if (!response.body || !response.body.getReader) {
          const raw = await response.text();
          this.processBufferedPayloads(raw, this.activeAssistant);
        } else {
          await this.readStream(response.body.getReader(), this.activeAssistant);
        }

        this.updateStatus("Ready when you are.");
        if (this.historyUrl) {
          this.refreshHistory();
        }
      } catch (error) {
        this.showError(error.message || "Unable to reach the assistant.");
        this.updateStatus("Temporarily offline — retry shortly.");
        if (this.activeAssistant) {
          this.updateAssistantContent(this.activeAssistant, error.message || "We hit a snag. Try again shortly.");
        }
      } finally {
        this.isStreaming = false;
        this.activeAssistant = null;
      }
    }

    async readStream(reader, assistant) {
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        buffer = this.processBufferedPayloads(buffer, assistant);
      }

      if (buffer.trim()) {
        this.handleStreamPayload(buffer.trim(), assistant);
      }
    }

    processBufferedPayloads(buffer, assistant) {
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        this.handleStreamPayload(line, assistant);
      }
      return buffer;
    }

    handleStreamPayload(rawLine, assistant) {
      const trimmed = rawLine.trim();
      if (!trimmed) {
        return;
      }

      let payload;
      try {
        payload = JSON.parse(trimmed);
      } catch (error) {
        console.warn("Unable to parse chat chunk", error);
        return;
      }

      if (!assistant) {
        return;
      }

      switch (payload.type) {
        case "conversation":
          this.setConversationId(payload.conversation_id);
          break;
        case "delta":
          this.updateAssistantContent(assistant, (assistant.buffer || "") + (payload.text || ""));
          break;
        case "final":
          this.updateAssistantContent(assistant, payload.text || assistant.buffer || "");
          this.updateAssistantSources(assistant, payload.sources || []);
          this.clearError();
          break;
        case "error":
          this.updateAssistantContent(assistant, payload.message || "Something went wrong.");
          this.showError(payload.message || "Something went wrong.");
          break;
        default:
          break;
      }
    }

    scrollToBottom() {
      if (this.scrollWrapper) {
        requestAnimationFrame(() => {
          this.scrollWrapper.scrollTo({ top: this.scrollWrapper.scrollHeight, behavior: "smooth" });
        });
      }
    }

    async refreshHistory() {
      if (!this.historyUrl || !this.historyContainer) {
        return;
      }
      try {
        const response = await fetch(this.historyUrl, { headers: { "HX-Request": "true" } });
        if (!response.ok) return;
        const html = await response.text();
        this.historyContainer.innerHTML = html;
      } catch (error) {
        console.warn("Unable to refresh history", error);
      }
    }
  }

  function initChatWidget(wrapper) {
    const toggle = wrapper.querySelector("[data-chat-widget-toggle]");
    const panel = wrapper.querySelector("[data-chat-widget-panel]");
    const close = wrapper.querySelector("[data-chat-widget-close]");

    if (!toggle || !panel) {
      return;
    }

    toggle.addEventListener("click", () => {
      panel.classList.add("chat-widget--open");
    });

    if (close) {
      close.addEventListener("click", () => {
        panel.classList.remove("chat-widget--open");
      });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-chat-widget]").forEach((node) => initChatWidget(node));
    document.querySelectorAll("[data-chat-root]").forEach((root) => {
      const controller = new ChatController(root);
      controller.connect();
    });
  });
})();
