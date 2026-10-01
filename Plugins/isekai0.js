// ==UserScript==
// @name         Isekaizero pia tts
// @namespace    http://tampermonkey.net/
// @version      2026-10-01
// @description  IsekaiZero TTS via PIA
// @author       You
// @match        https://www.isekaizero.ai/chats/*
// @icon         https://www.google.com/s2/favicons?sz=64&domain=isekaizero.ai
// @grant        none
// ==/UserScript==

(function () {
	"use strict";

	(function () {
		console.log(
			"🟢 [IsekaiZero TTS] Interceptador Universal (Fetch/XHR/EventSource) ativado na porta 8762!",
		);

		const LOCAL_TTS_URL = "http://localhost:8762/tts/stream_text";
		const STORAGE_KEY = "isekaizero_pia_tts_enabled";

		// ==========================================
		// CONTROLE DE ATIVAÇÃO
		// ==========================================

		let ttsEnabled = localStorage.getItem(STORAGE_KEY) !== "false";

		function setTTSState(enabled) {
			ttsEnabled = enabled;
			localStorage.setItem(STORAGE_KEY, String(enabled));

			updateToggleUI();

			console.log(
				enabled
					? "🟢 [IsekaiZero TTS] TTS ativado."
					: "🔴 [IsekaiZero TTS] TTS desativado.",
			);

			// Ao desativar, encerra qualquer texto que esteja sendo reproduzido.
			if (!enabled) {
				sendToTTS("", true);
			}
		}

		// ==========================================
		// BOTÃO FLUTUANTE
		// ==========================================

		let toggleContainer;
		let toggleRadio;

		function createToggleUI() {
			if (document.getElementById("pia-tts-toggle")) {
				return;
			}

			toggleContainer = document.createElement("div");
			toggleContainer.id = "pia-tts-toggle";

			Object.assign(toggleContainer.style, {
				position: "fixed",
				top: "12px",
				left: "12px",
				zIndex: "2147483647",
				display: "flex",
				alignItems: "center",
				justifyContent: "center",
				width: "34px",
				height: "34px",
				borderRadius: "50%",
				background: "rgba(20, 20, 20, 0.85)",
				border: "1px solid rgba(255, 255, 255, 0.25)",
				boxShadow: "0 2px 8px rgba(0, 0, 0, 0.4)",
				cursor: "pointer",
				userSelect: "none",
				backdropFilter: "blur(4px)",
			});

			toggleRadio = document.createElement("div");

			Object.assign(toggleRadio.style, {
				width: "14px",
				height: "14px",
				borderRadius: "50%",
				boxSizing: "border-box",
				border: "2px solid #888",
				background: "transparent",
				transition: "all 0.15s ease",
			});

			toggleContainer.title = "PIA TTS";

			toggleContainer.appendChild(toggleRadio);
			document.body.appendChild(toggleContainer);

			toggleContainer.addEventListener("click", function () {
				setTTSState(!ttsEnabled);
			});

			updateToggleUI();
		}

		function updateToggleUI() {
			if (!toggleContainer || !toggleRadio) {
				return;
			}

			if (ttsEnabled) {
				toggleContainer.style.background = "rgba(20, 20, 20, 0.9)";
				toggleContainer.style.borderColor = "rgba(80, 220, 120, 0.7)";
				toggleContainer.style.boxShadow =
					"0 2px 10px rgba(0, 0, 0, 0.45), 0 0 8px rgba(80, 220, 120, 0.25)";

				toggleRadio.style.background = "#4ade80";
				toggleRadio.style.borderColor = "#4ade80";
			} else {
				toggleContainer.style.background = "rgba(20, 20, 20, 0.75)";
				toggleContainer.style.borderColor = "rgba(255, 255, 255, 0.2)";
				toggleContainer.style.boxShadow = "0 2px 8px rgba(0, 0, 0, 0.4)";

				toggleRadio.style.background = "transparent";
				toggleRadio.style.borderColor = "#888";
			}
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

		initializeToggleUI();

		// ==========================================
		// ENVIO PARA O TTS
		// ==========================================

		// Guarda o fetch original para usarmos no envio ao TTS,
		// evitando loops.
		const originalFetch = window.fetch;

		function sendToTTS(text, flush = false) {
			if (!ttsEnabled) {
				return;
			}

			if (text) {
				console.log(`📤 [TTS] Texto: "${text}"`);
			}

			if (flush) {
				console.log("🌊 [TTS] FLUSH enviado (fim da geração).");
			}

			originalFetch(LOCAL_TTS_URL, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
				},
				body: JSON.stringify({
					text: text,
					flush: flush,
				}),
			}).catch((err) => {
				console.error("❌ Erro no envio local:", err);
			});
		}

		// ==========================================
		// PROCESSADOR CENTRAL DOS PACOTES
		// ==========================================

		function processChunk(dataStr) {
			if (!ttsEnabled) {
				return;
			}

			if (dataStr === "[DONE]") {
				console.log("⏹️ [IsekaiZero TTS] Fim do stream detectado.");

				sendToTTS("", true);
				return;
			}

			if (dataStr === "{}") {
				return;
			}

			try {
				const jsonData = JSON.parse(dataStr);

				if (jsonData.d === 1 && jsonData.a && jsonData.a.content) {
					sendToTTS(jsonData.a.content);
				}
			} catch (e) {
				// Ignora pacotes fragmentados que não são JSON puro ainda.
			}
		}

		// ==========================================
		// QUEBRADOR DE LINHAS PARA FETCH E XHR
		// ==========================================

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

		// ==========================================
		// 1. PATCH NO FETCH
		// ==========================================

		window.fetch = async function (...args) {
			const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";

			const response = await originalFetch.apply(this, args);

			if (url.includes("/stream/start")) {
				console.log("🎙️ [Interceptador] Rota capturada via FETCH!");

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

							buffer += decoder.decode(value, {
								stream: true,
							});

							buffer = processBuffer(buffer);
						}
					} catch (e) {
						console.error("Erro leitura Fetch", e);
					} finally {
						if (ttsEnabled) {
							sendToTTS("", true);
						}
					}
				})();
			}

			return response;
		};

		// ==========================================
		// 2. PATCH NO XMLHTTPREQUEST (XHR)
		// ==========================================

		const OriginalXHR = window.XMLHttpRequest;
		const xhrOpen = OriginalXHR.prototype.open;
		const xhrSend = OriginalXHR.prototype.send;

		OriginalXHR.prototype.open = function (method, url) {
			this._tts_url = url;

			return xhrOpen.apply(this, arguments);
		};

		OriginalXHR.prototype.send = function () {
			if (
				this._tts_url &&
				typeof this._tts_url === "string" &&
				this._tts_url.includes("/stream/start")
			) {
				console.log("🎙️ [Interceptador] Rota capturada via XHR!");

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
							if (ttsEnabled) {
								sendToTTS("", true);
							}
						}
					}
				});
			}

			return xhrSend.apply(this, arguments);
		};

		// ==========================================
		// 3. PATCH NO EVENTSOURCE (SSE NATIVO)
		// ==========================================

		const OriginalEventSource = window.EventSource;

		if (OriginalEventSource) {
			window.EventSource = function (...args) {
				const url = args[0];

				const es = new OriginalEventSource(...args);

				if (url && typeof url === "string" && url.includes("/stream/start")) {
					console.log("🎙️ [Interceptador] Rota capturada via EVENTSOURCE!");

					es.addEventListener("message", function (event) {
						processChunk(event.data);
					});

					es.addEventListener("error", function () {
						if (ttsEnabled) {
							sendToTTS("", true);
						}
					});
				}

				return es;
			};
		}
	})();
})();
