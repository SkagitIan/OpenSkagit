function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
        return parts.pop().split(";").shift();
    }
    return null;
}

document.addEventListener("DOMContentLoaded", () => {
    const transcript = document.getElementById("chat-transcript");
    const form = document.getElementById("chat-form");
    const input = document.getElementById("chat-input");
    const suggestions = document.querySelectorAll(".chat-suggestions__item");
    const subtitle = document.querySelector(".chat-panel__subtitle");

    if (!form || !transcript || !input) {
        return;
    }

    const conversation = [
        {
            role: "system",
            content:
                "You are the OpenSkagit assistant. Provide clear, actionable answers about Skagit Valley parcels, valuations, zoning, permitting, and community insights.",
        },
        {
            role: "assistant",
            content: "Welcome! Ask about parcels, valuations, or spatial trends across the Skagit Valley.",
        },
    ];

    let isSending = false;

    function createBubble(role, content, pending = false) {
        const bubble = document.createElement("div");
        bubble.className = `chat-bubble${role === "user" ? " chat-bubble--user" : " chat-bubble--bot"}${pending ? " chat-bubble--pending" : ""}`;

        const label = document.createElement("span");
        label.className = "chat-bubble__label";
        label.textContent = role === "user" ? "You" : "OpenSkagit";

        const message = document.createElement("p");
        message.innerText = content;

        bubble.appendChild(label);
        bubble.appendChild(message);

        transcript.appendChild(bubble);
        transcript.scrollTop = transcript.scrollHeight;

        return { bubble, message };
    }

    function setSubtitle(text) {
        if (subtitle) {
            subtitle.textContent = text;
        }
    }

    function sendMessage(message) {
        if (isSending || !message) {
            return;
        }

        isSending = true;
        setSubtitle("Sending to OpenAI…");

        removeSuggestions();

        createBubble("user", message);
        const history = conversation
            .filter((entry) => entry.role !== "system")
            .map((entry) => ({ role: entry.role, content: entry.content }));

        conversation.push({ role: "user", content: message });

        const pendingEntry = createBubble("assistant", "Thinking…", true);

        const payload = {
            message,
            history,
        };

        const csrfToken = getCookie("csrftoken");

        fetch("/api/chat/", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
            },
            body: JSON.stringify(payload),
        })
            .then(async (response) => {
                const data = await response.json().catch(() => ({}));

                if (!response.ok) {
                    throw new Error(data.error || "Unable to reach the assistant.");
                }

                const reply = data.reply || "I couldn't generate a response just yet. Try again in a moment.";

                conversation.push({ role: "assistant", content: reply });
                pendingEntry.message.innerText = reply;
                pendingEntry.bubble.classList.remove("chat-bubble--pending");

                setSubtitle("Connected to OpenAI API");
            })
            .catch((error) => {
                const fallback = error.message || "We hit a snag. Please try again.";
                pendingEntry.message.innerText = fallback;
                pendingEntry.bubble.classList.remove("chat-bubble--pending");
                setSubtitle("Temporarily offline – retry shortly");
            })
            .finally(() => {
                isSending = false;
            });
    }

    function removeSuggestions() {
        const suggestionWrapper = transcript.querySelector(".chat-suggestions");
        if (suggestionWrapper) {
            suggestionWrapper.remove();
        }
    }

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        const message = input.value.trim();
        if (!message) {
            return;
        }

        input.value = "";
        sendMessage(message);
    });

    suggestions.forEach((button) => {
        button.addEventListener("click", () => {
            const example = button.getAttribute("data-example");
            if (example) {
                input.value = example;
                input.focus();
                sendMessage(example);
            }
        });
    });
});
