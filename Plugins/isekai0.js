// ==UserScript==
// @name         Isekaizero pia tts
// @namespace    http://tampermonkey.net/
// @version      2026-10-01
// @description  IsekaiZero TTS via PIA
// @author       You
// @match        https://www.isekaizero.ai/chats/*
// @icon         https://raw.githubusercontent.com/oouo-diogo-perdigao/pia/refs/heads/develop/pia.svg
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
		const PIA_LOGO_URL =
			"https://raw.githubusercontent.com/oouo-diogo-perdigao/pia/refs/heads/develop/pia.svg";

		let ttsEnabled = localStorage.getItem(STORAGE_KEY) !== "false";

		let menuOpen = false;

		let toggleContainer;
		let logoButton;
		let menu;
		let toggleSwitch;
		let toggleKnob;

		// ==========================================
		// ENVIO PARA O TTS
		// ==========================================

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
		// CONTROLE DE ATIVAÇÃO
		// ==========================================

		function setTTSState(enabled) {
			ttsEnabled = enabled;

			localStorage.setItem(STORAGE_KEY, String(enabled));

			updateToggleUI();

			console.log(
				enabled
					? "🟢 [IsekaiZero TTS] TTS ativado."
					: "🔴 [IsekaiZero TTS] TTS desativado.",
			);

			if (!enabled) {
				sendToTTS("", true);
			}
		}

		// ==========================================
		// MENU DA PIA
		// ==========================================

		function toggleMenu() {
			menuOpen = !menuOpen;

			if (menuOpen) {
				menu.style.display = "flex";
			} else {
				menu.style.display = "none";
			}
		}

		// ==========================================
		// INTERFACE
		// ==========================================

		function createToggleUI() {
			if (document.getElementById("pia-tts-toggle-container")) {
				return;
			}

			// Container principal
			toggleContainer = document.createElement("div");
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

			// ==========================================
			// BOTÃO DA LOGO
			// ==========================================

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
				transition: "border-color 0.15s ease, box-shadow 0.15s ease",
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
				toggleMenu();
			});

			// ==========================================
			// MENU
			// ==========================================

			menu = document.createElement("div");
			menu.id = "pia-tts-menu";

			Object.assign(menu.style, {
				display: "none",
				marginTop: "8px",
				padding: "10px 12px",
				minWidth: "150px",
				boxSizing: "border-box",
				flexDirection: "row",
				alignItems: "center",
				justifyContent: "space-between",
				gap: "14px",
				borderRadius: "10px",
				background: "rgba(20, 20, 20, 0.94)",
				border: "1px solid rgba(255, 255, 255, 0.15)",
				boxShadow: "0 4px 16px rgba(0, 0, 0, 0.45)",
				backdropFilter: "blur(8px)",
				color: "#fff",
				fontSize: "13px",
				lineHeight: "1",
			});

			const menuLabel = document.createElement("span");

			menuLabel.textContent = "TTS";

			Object.assign(menuLabel.style, {
				whiteSpace: "nowrap",
				fontWeight: "500",
			});

			// ==========================================
			// TOGGLE
			// ==========================================

			toggleSwitch = document.createElement("div");

			Object.assign(toggleSwitch.style, {
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

			toggleKnob = document.createElement("div");

			Object.assign(toggleKnob.style, {
				position: "absolute",
				top: "2px",
				left: "2px",
				width: "12px",
				height: "12px",
				borderRadius: "50%",
				background: "#888",
				transition: "transform 0.15s ease, background 0.15s ease",
			});

			toggleSwitch.appendChild(toggleKnob);

			toggleSwitch.addEventListener("click", (event) => {
				event.stopPropagation();
				setTTSState(!ttsEnabled);
			});

			menu.appendChild(menuLabel);
			menu.appendChild(toggleSwitch);

			toggleContainer.appendChild(logoButton);
			toggleContainer.appendChild(menu);

			document.body.appendChild(toggleContainer);

			updateToggleUI();
		}

		function updateToggleUI() {
			if (!toggleSwitch || !toggleKnob || !logoButton) {
				return;
			}

			if (ttsEnabled) {
				toggleSwitch.style.background = "rgba(74, 222, 128, 0.35)";

				toggleSwitch.style.borderColor = "rgba(74, 222, 128, 0.7)";

				toggleKnob.style.background = "#4ade80";
				toggleKnob.style.transform = "translateX(16px)";

				logoButton.style.borderColor = "rgba(74, 222, 128, 0.6)";

				logoButton.style.boxShadow =
					"0 2px 10px rgba(0, 0, 0, 0.45), 0 0 8px rgba(80, 220, 120, 0.2)";
			} else {
				toggleSwitch.style.background = "rgba(255, 255, 255, 0.08)";

				toggleSwitch.style.borderColor = "rgba(255, 255, 255, 0.2)";

				toggleKnob.style.background = "#888";
				toggleKnob.style.transform = "translateX(0)";

				logoButton.style.borderColor = "rgba(255, 255, 255, 0.25)";

				logoButton.style.boxShadow = "0 2px 8px rgba(0, 0, 0, 0.4)";
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
				// Ignora pacotes fragmentados.
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
		// 2. PATCH NO XMLHTTPREQUEST
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

						if (this.readyState === 4 && ttsEnabled) {
							sendToTTS("", true);
						}
					}
				});
			}

			return xhrSend.apply(this, arguments);
		};

		// ==========================================
		// 3. PATCH NO EVENTSOURCE
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
