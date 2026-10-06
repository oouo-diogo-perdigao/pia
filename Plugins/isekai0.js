// ==UserScript==
// @name         Isekaizero pia tts
// @namespace    http://tampermonkey.net/
// @version      2026-10-06
// @description  IsekaiZero TTS/STT via PIA
// @author       You
// @match        https://www.isekaizero.ai/chats/*
// @icon         https://raw.githubusercontent.com/oouo-diogo-perdigao/pia/refs/heads/develop/pia.svg
// @grant        none
// ==/UserScript==

(function () {
    "use strict";

    const PIA_BASE_URL = "http://localhost:8762";
    const STORYTELLING_URL = `${PIA_BASE_URL}/tts/storytelling`;
    const LOCAL_RECORD_URL = `${PIA_BASE_URL}/action/local-record`;
    const LOCAL_RECORD_STREAM_URL = `${PIA_BASE_URL}/action/local-record/stream`;

    const TTS_STORAGE_KEY = "isekaizero_pia_tts_enabled";
    const KOKORO_STORAGE_KEY = "isekaizero_pia_kokoro_only";
    const PIA_LOGO_URL =
        "https://raw.githubusercontent.com/oouo-diogo-perdigao/pia/refs/heads/develop/pia.svg";

    const originalFetch = window.fetch.bind(window);

    let ttsEnabled = localStorage.getItem(TTS_STORAGE_KEY) !== "false";
    let kokoroOnly = localStorage.getItem(KOKORO_STORAGE_KEY) === "true";

    // STT intentionally never persists between page loads.
    let sttEnabled = false;
    let sttRecording = false;
    let sttStarting = false;
    let sttEventSource = null;

    let storyBuffer = "";
    let menuOpen = false;

    let logoButton;
    let menu;

    const toggleControls = {};

    console.log(
        "🟢 [IsekaiZero PIA] TTS/STT ativado na porta 8762.",
    );

    // ============================================================
    // TOGGLES / UI
    // ============================================================

    function createToggleControl(labelText, onClick) {
        const row = document.createElement("div");
        Object.assign(row.style, {
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "14px",
            width: "100%",
            minWidth: "210px",
        });

        const label = document.createElement("span");
        label.textContent = labelText;
        Object.assign(label.style, {
            whiteSpace: "nowrap",
            fontWeight: "500",
            flex: "1",
        });

        const toggle = document.createElement("div");
        Object.assign(toggle.style, {
            position: "relative",
            width: "34px",
            height: "18px",
            borderRadius: "999px",
            cursor: "pointer",
            flexShrink: "0",
            transition: "background 0.15s ease, border-color 0.15s ease",
            border: "1px solid rgba(255, 255, 255, 0.2)",
            boxSizing: "border-box",
        });

        const knob = document.createElement("div");
        Object.assign(knob.style, {
            position: "absolute",
            top: "2px",
            left: "2px",
            width: "12px",
            height: "12px",
            borderRadius: "50%",
            background: "#888",
            transition: "transform 0.15s ease, background 0.15s ease",
        });

        toggle.appendChild(knob);
        toggle.addEventListener("click", (event) => {
            event.stopPropagation();
            onClick();
        });

        row.appendChild(label);
        row.appendChild(toggle);

        return { row, label, toggle, knob };
    }

    function paintToggle(control, state) {
        if (!control) {
            return;
        }

        if (state === "on") {
            control.toggle.style.background = "rgba(74, 222, 128, 0.35)";
            control.toggle.style.borderColor = "rgba(74, 222, 128, 0.7)";
            control.knob.style.background = "#4ade80";
            control.knob.style.transform = "translateX(16px)";
            return;
        }

        if (state === "waiting") {
            control.toggle.style.background = "rgba(250, 204, 21, 0.28)";
            control.toggle.style.borderColor = "rgba(250, 204, 21, 0.75)";
            control.knob.style.background = "#facc15";
            control.knob.style.transform = "translateX(16px)";
            return;
        }

        control.toggle.style.background = "rgba(255, 255, 255, 0.08)";
        control.toggle.style.borderColor = "rgba(255, 255, 255, 0.2)";
        control.knob.style.background = "#888";
        control.knob.style.transform = "translateX(0)";
    }

    function updateToggleUI() {
        if (!logoButton) {
            return;
        }

        paintToggle(toggleControls.tts, ttsEnabled ? "on" : "off");
        paintToggle(toggleControls.kokoro, kokoroOnly ? "on" : "off");

        const textarea = getVisibleTextarea();

        if (!sttEnabled) {
            toggleControls.stt.label.textContent = "STT · desligado";
            paintToggle(toggleControls.stt, "off");
        } else if (!textarea || !sttRecording) {
            toggleControls.stt.label.textContent = "STT · aguardando textarea";
            paintToggle(toggleControls.stt, "waiting");
        } else {
            toggleControls.stt.label.textContent = "STT · ativo";
            paintToggle(toggleControls.stt, "on");
        }

        logoButton.style.borderColor = ttsEnabled
            ? "rgba(74, 222, 128, 0.6)"
            : "rgba(255, 255, 255, 0.25)";
        logoButton.style.boxShadow = ttsEnabled
            ? "0 2px 10px rgba(0,0,0,.45), 0 0 8px rgba(80,220,120,.2)"
            : "0 2px 8px rgba(0,0,0,.4)";
    }

    function createToggleUI() {
        if (document.getElementById("pia-tts-toggle-container")) {
            return;
        }

        const toggleContainer = document.createElement("div");
        toggleContainer.id = "pia-tts-toggle-container";

        Object.assign(toggleContainer.style, {
            position: "fixed",
            top: "12px",
            left: "12px",
            zIndex: "2147483647",
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-start",
            fontFamily:
                "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        });

        logoButton = document.createElement("div");
        logoButton.id = "pia-tts-logo";

        Object.assign(logoButton.style, {
            width: "34px",
            height: "34px",
            borderRadius: "50%",
            background: "rgba(20, 20, 20, 0.9)",
            border: "1px solid rgba(255, 255, 255, 0.25)",
            boxShadow: "0 2px 8px rgba(0, 0, 0, 0.4)",
            cursor: "pointer",
            userSelect: "none",
            backdropFilter: "blur(4px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxSizing: "border-box",
            overflow: "hidden",
            transition: "border-color .15s ease, box-shadow .15s ease",
        });

        const logo = document.createElement("img");
        logo.src = PIA_LOGO_URL;
        logo.alt = "PIA";

        Object.assign(logo.style, {
            width: "24px",
            height: "24px",
            display: "block",
            objectFit: "contain",
            pointerEvents: "none",
        });

        logoButton.appendChild(logo);
        logoButton.title = "PIA";
        logoButton.addEventListener("click", () => {
            menuOpen = !menuOpen;
            menu.style.display = menuOpen ? "flex" : "none";
        });

        menu = document.createElement("div");
        menu.id = "pia-tts-menu";

        Object.assign(menu.style, {
            display: "none",
            marginTop: "8px",
            padding: "10px 12px",
            minWidth: "230px",
            boxSizing: "border-box",
            flexDirection: "column",
            alignItems: "stretch",
            gap: "10px",
            borderRadius: "10px",
            background: "rgba(20, 20, 20, 0.94)",
            border: "1px solid rgba(255, 255, 255, 0.15)",
            boxShadow: "0 4px 16px rgba(0, 0, 0, 0.45)",
            backdropFilter: "blur(8px)",
            color: "#fff",
            fontSize: "13px",
            lineHeight: "1.2",
        });

        toggleControls.tts = createToggleControl("TTS", () => {
            setTTSState(!ttsEnabled);
        });

        toggleControls.kokoro = createToggleControl("Kokoro only", () => {
            kokoroOnly = !kokoroOnly;
            localStorage.setItem(KOKORO_STORAGE_KEY, String(kokoroOnly));
            updateToggleUI();
        });

        toggleControls.stt = createToggleControl("STT · desligado", () => {
            setSTTState(!sttEnabled);
        });

        menu.appendChild(toggleControls.tts.row);
        menu.appendChild(toggleControls.kokoro.row);
        menu.appendChild(toggleControls.stt.row);

        toggleContainer.appendChild(logoButton);
        toggleContainer.appendChild(menu);
        document.body.appendChild(toggleContainer);

        updateToggleUI();
    }

    function initializeToggleUI() {
        if (document.body) {
            createToggleUI();
            return;
        }

        const observer = new MutationObserver(() => {
            if (document.body) {
                observer.disconnect();
                createToggleUI();
            }
        });

        observer.observe(document.documentElement, {
            childList: true,
            subtree: true,
        });
    }

    function setTTSState(enabled) {
        ttsEnabled = enabled;
        localStorage.setItem(TTS_STORAGE_KEY, String(enabled));

        if (!enabled) {
            storyBuffer = "";
        }

        updateToggleUI();

        console.log(
            enabled
                ? "🟢 [IsekaiZero PIA] TTS ativado."
                : "🔴 [IsekaiZero PIA] TTS desativado.",
        );
    }

    // ============================================================
    // STORYTELLING TTS
    // ============================================================

    function appendStoryText(text) {
        if (!ttsEnabled || !text) {
            return;
        }

        storyBuffer += text;
    }

    function flushStory() {
        const text = storyBuffer.trim();
        storyBuffer = "";

        if (!ttsEnabled || !text) {
            return;
        }

        const payload = { text };

        if (kokoroOnly) {
            payload.kokoro = "only";
        }

        console.log(
            `📤 [TTS] Enviando storytelling (${kokoroOnly ? "Kokoro only" : "normal"}).`,
        );

        originalFetch(STORYTELLING_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        }).catch((error) => {
            console.error("❌ [TTS] Erro ao enviar storytelling:", error);
        });
    }

    function processChunk(dataStr) {
        if (dataStr === "[DONE]") {
            flushStory();
            return;
        }

        if (!ttsEnabled || dataStr === "{}") {
            return;
        }

        try {
            const jsonData = JSON.parse(dataStr);

            if (jsonData.d === 1 && jsonData.a && jsonData.a.content) {
                appendStoryText(jsonData.a.content);
            }
        } catch (_error) {
            // Fragmentos incompletos são recompostos pelo buffer externo.
        }
    }

    function processBuffer(buffer) {
        const lines = buffer.split("\n");
        const remaining = lines.pop();

        for (const line of lines) {
            if (line.trim().startsWith("data: ")) {
                processChunk(line.replace("data:", "").trim());
            }
        }

        return remaining;
    }

    // ============================================================
    // STT INTO VISIBLE TEXTAREA
    // ============================================================

    function isElementVisible(element) {
        if (!element || !element.isConnected) {
            return false;
        }

        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();

        return (
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            Number(style.opacity || "1") !== 0 &&
            rect.width > 0 &&
            rect.height > 0
        );
    }

    function getVisibleTextarea() {
        const textareas = Array.from(document.querySelectorAll("textarea")).filter(
            isElementVisible,
        );

        if (!textareas.length) {
            return null;
        }

        if (
            document.activeElement instanceof HTMLTextAreaElement &&
            textareas.includes(document.activeElement)
        ) {
            return document.activeElement;
        }

        return textareas.sort((a, b) => {
            const areaA =
                a.getBoundingClientRect().width * a.getBoundingClientRect().height;
            const areaB =
                b.getBoundingClientRect().width * b.getBoundingClientRect().height;
            return areaB - areaA;
        })[0];
    }

    function normalizeVoiceCommand(text) {
        return String(text || "")
            .trim()
            .toLocaleLowerCase("pt-BR")
            .replace(/[.!?,;:]+$/g, "")
            .trim();
    }

    function setTextareaValue(textarea, value) {
        const descriptor = Object.getOwnPropertyDescriptor(
            HTMLTextAreaElement.prototype,
            "value",
        );

        if (descriptor && descriptor.set) {
            descriptor.set.call(textarea, value);
        } else {
            textarea.value = value;
        }

        textarea.dispatchEvent(
            new InputEvent("input", {
                bubbles: true,
                inputType: "insertText",
                data: value,
            }),
        );
    }

    function insertTextIntoTextarea(textarea, text) {
        textarea.focus();

        const currentValue = textarea.value || "";
        const start = textarea.selectionStart ?? currentValue.length;
        const end = textarea.selectionEnd ?? start;

        let insertion = text.trim();

        if (!insertion) {
            return;
        }

        const prefix = currentValue.slice(0, start);
        const suffix = currentValue.slice(end);

        if (prefix && !/\s$/.test(prefix)) {
            insertion = " " + insertion;
        }

        if (suffix && !/^\s/.test(suffix)) {
            insertion += " ";
        } else if (!suffix) {
            insertion += " ";
        }

        const newValue = prefix + insertion + suffix;
        const newCursor = prefix.length + insertion.length;

        setTextareaValue(textarea, newValue);
        textarea.setSelectionRange(newCursor, newCursor);
    }

    function simulateShiftEnter(textarea) {
        textarea.focus();

        const eventOptions = {
            key: "Enter",
            code: "Enter",
            keyCode: 13,
            which: 13,
            shiftKey: true,
            bubbles: true,
            cancelable: true,
        };

        textarea.dispatchEvent(new KeyboardEvent("keydown", eventOptions));
        textarea.dispatchEvent(new KeyboardEvent("keypress", eventOptions));
        textarea.dispatchEvent(new KeyboardEvent("keyup", eventOptions));
    }

    function handleSTTChunk(text) {
        const textarea = getVisibleTextarea();

        if (!sttEnabled || !textarea) {
            syncSTTState();
            return;
        }

        if (normalizeVoiceCommand(text) === "enviar") {
            console.log("📨 [STT] Comando 'enviar' detectado. Shift+Enter.");
            simulateShiftEnter(textarea);
            return;
        }

        insertTextIntoTextarea(textarea, text);
    }

    async function startSTTRecording() {
        if (!sttEnabled || sttRecording || sttStarting || !getVisibleTextarea()) {
            return;
        }

        sttStarting = true;
        updateToggleUI();

        try {
            const response = await originalFetch(LOCAL_RECORD_URL, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    insert_at_cursor: false,
                }),
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            if (!sttEnabled || !getVisibleTextarea()) {
                await stopSTTRecording();
                return;
            }

            sttEventSource = new EventSource(LOCAL_RECORD_STREAM_URL);
            sttRecording = true;

            sttEventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    const chunks = Array.isArray(data.text_chunks)
                        ? data.text_chunks
                        : [];

                    for (const text of chunks) {
                        handleSTTChunk(text);
                    }
                } catch (error) {
                    console.error("❌ [STT] Evento SSE inválido:", error);
                }
            };

            sttEventSource.onerror = () => {
                if (!sttEnabled || !getVisibleTextarea()) {
                    stopSTTRecording();
                }
            };

            console.log("🎙️ [STT] Gravação iniciada para a textarea.");
        } catch (error) {
            console.error("❌ [STT] Falha ao iniciar:", error);
            sttRecording = false;
        } finally {
            sttStarting = false;
            updateToggleUI();
        }
    }

    async function stopSTTRecording() {
        if (sttEventSource) {
            sttEventSource.close();
            sttEventSource = null;
        }

        const wasRecording = sttRecording || sttStarting;
        sttRecording = false;
        sttStarting = false;

        if (wasRecording) {
            try {
                await originalFetch(LOCAL_RECORD_URL, {
                    method: "DELETE",
                });
            } catch (error) {
                console.error("❌ [STT] Falha ao parar:", error);
            }
        }

        updateToggleUI();
    }

    function syncSTTState() {
        if (!sttEnabled) {
            if (sttRecording || sttStarting) {
                stopSTTRecording();
            } else {
                updateToggleUI();
            }
            return;
        }

        if (!getVisibleTextarea()) {
            if (sttRecording || sttStarting) {
                stopSTTRecording();
            } else {
                updateToggleUI();
            }
            return;
        }

        if (!sttRecording && !sttStarting) {
            startSTTRecording();
        } else {
            updateToggleUI();
        }
    }

    function setSTTState(enabled) {
        sttEnabled = enabled;

        if (!enabled) {
            stopSTTRecording();
        } else {
            syncSTTState();
        }

        updateToggleUI();
    }

    // Isekai is a dynamic SPA. Polling avoids coupling this plugin to its
    // framework internals and reliably catches textarea mount/unmount.
    setInterval(syncSTTState, 500);

    window.addEventListener("focus", syncSTTState);
    window.addEventListener("resize", syncSTTState);

    window.addEventListener("pagehide", () => {
        if (sttEventSource) {
            sttEventSource.close();
            sttEventSource = null;
        }

        if (sttRecording || sttStarting) {
            originalFetch(LOCAL_RECORD_URL, {
                method: "DELETE",
                keepalive: true,
            }).catch(() => {});
        }

        sttRecording = false;
        sttStarting = false;
    });

    // ============================================================
    // FETCH INTERCEPTOR
    // ============================================================

    window.fetch = async function (...args) {
        const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
        const response = await originalFetch(...args);

        if (url.includes("/stream/start")) {
            const clone = response.clone();

            (async () => {
                const reader = clone.body.getReader();
                const decoder = new TextDecoder("utf-8");
                let buffer = "";

                try {
                    while (true) {
                        const { done, value } = await reader.read();

                        if (done) {
                            break;
                        }

                        buffer += decoder.decode(value, { stream: true });
                        buffer = processBuffer(buffer);
                    }
                } catch (error) {
                    console.error("❌ [TTS] Erro lendo Fetch:", error);
                } finally {
                    flushStory();
                }
            })();
        }

        return response;
    };

    // ============================================================
    // XHR INTERCEPTOR
    // ============================================================

    const OriginalXHR = window.XMLHttpRequest;
    const xhrOpen = OriginalXHR.prototype.open;
    const xhrSend = OriginalXHR.prototype.send;

    OriginalXHR.prototype.open = function (method, url) {
        this._piaStreamUrl = url;
        return xhrOpen.apply(this, arguments);
    };

    OriginalXHR.prototype.send = function () {
        if (
            this._piaStreamUrl &&
            typeof this._piaStreamUrl === "string" &&
            this._piaStreamUrl.includes("/stream/start")
        ) {
            let lastLength = 0;
            let buffer = "";

            this.addEventListener("readystatechange", function () {
                if (this.readyState === 3 || this.readyState === 4) {
                    const responseText = this.responseText || "";
                    const newData = responseText.substring(lastLength);
                    lastLength = responseText.length;

                    buffer += newData;
                    buffer = processBuffer(buffer);

                    if (this.readyState === 4) {
                        flushStory();
                    }
                }
            });
        }

        return xhrSend.apply(this, arguments);
    };

    // ============================================================
    // EVENTSOURCE INTERCEPTOR
    // ============================================================

    const OriginalEventSource = window.EventSource;

    if (OriginalEventSource) {
        window.EventSource = function (...args) {
            const url = args[0];
            const eventSource = new OriginalEventSource(...args);

            if (url && typeof url === "string" && url.includes("/stream/start")) {
                eventSource.addEventListener("message", (event) => {
                    processChunk(event.data);
                });

                eventSource.addEventListener("error", () => {
                    flushStory();
                });
            }

            return eventSource;
        };

        window.EventSource.prototype = OriginalEventSource.prototype;
    }

    initializeToggleUI();
    updateToggleUI();
})();
