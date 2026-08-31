import json
from .AudioPlayer import AudioPlayer
from .TTSManager import TTSManager


from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .config import HOST, PORT, DEFAULT_VOICE, DEFAULT_SPEED, logging, logger_tts

TTS_MANAGER = TTSManager()
PLAYER = AudioPlayer(TTS_MANAGER)


# ==============================================================================
# SERVIDOR HTTP
# ==============================================================================
class Handler(BaseHTTPRequestHandler):
    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(data.decode("utf-8"))

            if self.path == "/speak":
                text = payload.get("text", "")
                voice = payload.get("voice", DEFAULT_VOICE)
                speed = float(payload.get("speed", DEFAULT_SPEED))
                device = payload.get("device", None)
                style = payload.get("style", None)

                if not isinstance(text, str) or not text.strip():
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                text = clean_text(text)

                # pica o text em quebras de linha duplas para evitar que textos muito longos travem o player
                parts = [p.strip() for p in text.split("\n\n") if p.strip()]

                for part in parts:
                    log_tts_text(part)
                    PLAYER.add_job(part.strip(), voice, speed, device, style)

                logging.info(
                    "[SPEAK] %d parte(s) enviada(s) para a fila local.", len(parts)
                )

                self.send_json(200, {"ok": True, "status": "queued"})
                return

            if self.path == "/stop":
                PLAYER.stop()
                logging.info("[STOP] Leitura interrompida.")
                self.send_json(200, {"ok": True, "status": "stopped"})
                return

            if self.path == "/generate":
                text = payload.get("text", "")
                voice = payload.get("voice", DEFAULT_VOICE)
                speed = float(payload.get("speed", DEFAULT_SPEED))
                style = payload.get("style", None)  # <--- Captura o style também aqui

                if not isinstance(text, str) or not text.strip():
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                text = clean_text(text)

                log_tts_text(text)
                logging.info("[GENERATE] Gerando WAV via Worker Process...")
                wav_data = TTS_MANAGER.generate_wav(text, voice, speed, style=style)

                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_data)))
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(wav_data)
                return

            self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})
        except Exception as exc:
            logging.exception("Erro durante requisição POST HTTP.")
            self.send_json(500, {"ok": False, "error": str(exc)})

    def do_GET(self):
        if self.path == "/warmup":
            logging.info("[WARMUP] Aquecendo Worker do TTS antecipadamente...")
            TTS_MANAGER.ensure_worker_running()
            self.send_json(200, {"ok": True, "status": "warmed_up"})
            return

        if self.path == "/status":
            with PLAYER.lock:
                status = PLAYER.status
            self.send_json(
                200,
                {
                    "ok": True,
                    "status": status,
                    "model_loaded": TTS_MANAGER.is_loaded(),
                },
            )
            return

        if self.path == "/help":
            html_content = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>PIA - Central de Magia e Ajuda</title>
    <style>
        :root {
            --bg-deep: #070913;
            --bg-card: rgba(16, 22, 40, 0.75);
            --border-glow: rgba(59, 130, 246, 0.3);
            --accent-blue: #3b82f6;
            --accent-purple: #8b5cf6;
            --neon-cyan: #06b6d4;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
        }
        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background-color: var(--bg-deep);
            background-image: 
                radial-gradient(circle at 15% 15%, rgba(59, 130, 246, 0.15) 0%, transparent 40%),
                radial-gradient(circle at 85% 85%, rgba(139, 92, 246, 0.15) 0%, transparent 40%);
            color: var(--text-main);
            margin: 0;
            padding: 40px 20px;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .container {
            width: 100%;
            max-width: 950px;
            background: var(--bg-card);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border-glow);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 0 40px rgba(59, 130, 246, 0.15), inset 0 0 20px rgba(139, 92, 246, 0.05);
            box-sizing: border-box;
        }
        .header {
            text-align: center;
            margin-bottom: 35px;
        }
        .logo-area {
            display: inline-flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 15px;
        }
        .logo-icon {
            width: 50px;
            height: 50px;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 0 20px rgba(59, 130, 246, 0.5);
            position: relative;
        }
        .logo-icon::before {
            content: "• •";
            color: #fff;
            font-size: 14px;
            font-weight: bold;
            letter-spacing: 4px;
        }
        h1 {
            font-size: 2.2rem;
            margin: 0;
            background: linear-gradient(135deg, #60a5fa, #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-weight: 800;
        }
        .tagline {
            color: var(--neon-cyan);
            font-size: 0.95rem;
            text-transform: uppercase;
            letter-spacing: 2px;
            margin-top: 5px;
            font-weight: 600;
        }
        .greeting-box {
            background: rgba(59, 130, 246, 0.08);
            border: 1px dashed rgba(59, 130, 246, 0.4);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 30px;
            font-size: 1.05rem;
            line-height: 1.6;
            color: #cbd5e1;
        }
        h2 {
            font-size: 1.3rem;
            color: #93c5fd;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding-bottom: 8px;
            margin-top: 30px;
            margin-bottom: 15px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            margin-bottom: 25px;
            background: rgba(10, 14, 26, 0.5);
            border-radius: 10px;
            overflow: hidden;
        }
        th, td {
            padding: 14px 16px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            font-size: 0.92rem;
        }
        th {
            background-color: rgba(30, 41, 59, 0.7);
            color: #93c5fd;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.8rem;
            letter-spacing: 1px;
        }
        tr:last-child td { border-bottom: none; }
        tr:hover td { background: rgba(59, 130, 246, 0.04); }
        code {
            background: rgba(0, 0, 0, 0.4);
            color: #38bdf8;
            padding: 3px 7px;
            border-radius: 6px;
            font-family: monospace;
            font-size: 0.88rem;
            border: 1px solid rgba(56, 189, 248, 0.2);
        }
        .endpoint-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        .endpoint-card {
            background: rgba(20, 27, 45, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 10px;
            padding: 16px;
            transition: all 0.3s ease;
        }
        .endpoint-card:hover {
            border-color: var(--accent-blue);
            transform: translateY(-2px);
        }
        .method {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: bold;
            margin-bottom: 8px;
        }
        .method.post { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
        .method.get { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); }
        .badge {
            display: inline-block;
            background: rgba(139, 92, 246, 0.2);
            color: #c084fc;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 0.75rem;
            font-weight: 500;
            border: 1px solid rgba(139, 92, 246, 0.3);
        }
        ul { padding-left: 20px; color: var(--text-muted); line-height: 1.6; }
        li strong { color: var(--text-main); }
        .footer-note {
            text-align: center;
            margin-top: 35px;
            font-size: 0.85rem;
            color: var(--text-muted);
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            padding-top: 20px;
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="logo-area">
            <div class="logo-icon"></div>
            <h1>PIA</h1>
        </div>
        <div class="tagline">Protege. Privada. Pessoal. Poderosa. ✨</div>
    </div>

    <div class="greeting-box">
        ✨ <strong>Oiê! Sou a PIA</strong>, sua assistente mágica de inteligência artificial! Estou super feliz e pronta para te ajudar a dar vida aos seus textos com vozes incríveis. Aqui embaixo organizei com muito carinho todas as opções, comandos de estilo e segredos mágicos do nosso servidor TTS! 💖
    </div>

    <h2>🔮 1. Endpoints Mágicos</h2>
    <div class="endpoint-grid">
        <div class="endpoint-card">
            <span class="method post">POST</span> <code>/speak</code>
            <p style="margin: 8px 0 0 0; font-size: 0.88rem; color: var(--text-muted);">Envia texto para a fila local do player de áudio reproduzir.</p>
        </div>
        <div class="endpoint-card">
            <span class="method post">POST</span> <code>/generate</code>
            <p style="margin: 8px 0 0 0; font-size: 0.88rem; color: var(--text-muted);">Sintetiza e retorna diretamente os dados binários do áudio em arquivo <code>.wav</code>.</p>
        </div>
        <div class="endpoint-card">
            <span class="method get">GET</span> <code>/status</code>
            <p style="margin: 8px 0 0 0; font-size: 0.88rem; color: var(--text-muted);">Consulta o estado atual do player e se o modelo está ativo na memória.</p>
        </div>
        <div class="endpoint-card">
            <span class="method get">GET</span> <code>/help</code>
            <p style="margin: 8px 0 0 0; font-size: 0.88rem; color: var(--text-muted);">Abre este painel mágico de documentação interativa.</p>
        </div>
    </div>

    <h2>🧠 2. Motores & Consumo de Memória</h2>
    <table>
        <tr>
            <th>Motor / Modo</th>
            <th>Ativação</th>
            <th>Custo de Memória (Aprox.)</th>
            <th>Propósito Mágico</th>
        </tr>
        <tr>
            <td><strong>Kokoro-82M</strong> <span class="badge">Padrão</span></td>
            <td>Quando <code>style</code> está ausente ou vazio.</td>
            <td>~300 MB a 500 MB (CPU / ONNX)</td>
            <td>Ultraleve e super rápido! Perfeito para leituras fluidas do dia a dia. Voz padrão: <code>pm_santa</code>.</td>
        </tr>
        <tr>
            <td><strong>Qwen3-TTS</strong> <span class="badge">Avançado</span></td>
            <td>Ativado automaticamente ao preencher o campo <code>style</code>.</td>
            <td>~3.5 GB a 4.5 GB (VRAM - RTX 3080 / FP16)</td>
            <td>Poderoso motor de IA generativa para controle profundo de emoções, entonações e estilo!</td>
        </tr>
    </table>

    <h2>🎭 3. Opções do Parâmetro <code>style</code> (Qwen-TTS)</h2>
    <p style="color: var(--text-muted); font-size: 0.9rem; margin-top: -5px;">Você pode usar instruções livres em linguagem natural para guiar a emoção, o ritmo e o personagem da voz:</p>
    <table>
        <tr>
            <th>Categoria</th>
            <th>Exemplos de Instrução para o <code>style</code></th>
            <th>Efeito Mágico no Áudio</th>
        </tr>
        <tr>
            <td><strong>Emoção & Energia</strong></td>
            <td>
                <code>"fale com tom alegre e super animado"</code><br>
                <code>"fale com tom triste, melancólico e com voz chorosa"</code><br>
                <code>"voz calma, acolhedora e relaxante"</code><br>
                <code>"tom bravo, irritado e com muita pressa"</code>
            </td>
            <td>Modula a carga emocional, fazendo a IA sorrir, demonstrar empatia ou transparecer urgência.</td>
        </tr>
        <tr>
            <td><strong>Ritmo & Prosódia</strong></td>
            <td>
                <code>"fale devagar, pausadamente e com clareza"</code><br>
                <code>"voz rápida, com tom empolgado e comercial"</code><br>
                <code>"sussurre bem baixinho, como um segredo"</code>
            </td>
            <td>Controla a velocidade de dicção, pausas dramáticas e intensidade acústica.</td>
        </tr>
        <tr>
            <td><strong>Personas & Papéis</strong></td>
            <td>
                <code>"atue como uma irmãzinha fofa e brincalhona"</code><br>
                <code>"interprete um cientista experiente com tom sério e sábio"</code><br>
                <code>"fale como um apresentador de rádio animado"</code>
            </td>
            <td>Adota características de personalidade e contexto cênico na entrega da locução.</td>
        </tr>
    </table>

    <h2>⚙️ 4. Payload e Atributos da API</h2>
    <ul>
        <li><strong>text</strong> (string, obrigatório): O texto mágico que eu vou transformar em voz para você.</li>
        <li><strong>voice</strong> (string, opcional): Nome da voz (Ex: <code>pm_santa</code> no Kokoro; ou <code>Ryan</code>, <code>Vivian</code>, <code>Serena</code>, <code>Dylan</code>, <code>Aiden</code> no Qwen).</li>
        <li><strong>speed</strong> (float, opcional): Velocidade da locução (Padrão: <code>0.95</code>).</li>
        <li><strong>device</strong> (string, opcional): Dispositivo de destino do áudio.</li>
        <li><strong>style</strong> (string, opcional): Instrução de estilo emocional/direcional (aciona o motor avançado Qwen).</li>
    </ul>

    <h2>🎙️ 5. Lista de Vozes Disponíveis</h2>
    <p style="color: var(--text-muted); font-size: 0.9rem; margin-top: -5px;">Cada motor possui seu próprio catálogo de vozes cheias de personalidade:</p>
    <table>
        <tr>
            <th>Motor</th>
            <th>Vozes Disponíveis (Parâmetro <code>voice</code>)</th>
            <th>Observações</th>
        </tr>
        <tr>
            <td><strong>Kokoro-82M</strong><br><span class="badge">Modo Padrão</span></td>
            <td>
                <code>pm_santa</code> (Masculina - Padrão)<br>
                <code>pm_alex</code> (Masculina)<br>
                <code>pf_dora</code> (Feminina)<br>
                <em>(Outras vozes do ecossistema Kokoro compatíveis com o arquivo de pesos binário podem ser utilizadas informando o respectivo ID de string).</em>
            </td>
            <td>Ideal para português do Brasil com alta fluidez e rapidez.</td>
        </tr>
        <tr>
            <td><strong>Qwen3-TTS</strong><br><span class="badge">Modo Estilo</span></td>
            <td>
                <code>ryan</code> (Masculina - Padrão)<br>
                <code>vivian</code> (Feminina)<br>
                <code>serena</code> (Feminina)<br>
                <code>dylan</code> (Masculina)<br>
                <code>eric</code> (Masculina)<br>
                <code>ono_anna</code> (Feminina)<br>
                <code>sohee</code> (Feminina)<br>
                <code>uncle_fu</code> (Feminina)<br>
                <code>aiden</code> (Masculina)
            </td>
            <td>Utilizadas junto ao parâmetro <code>style</code> para permitir modelagem de emoção, entonação e características vocais avançadas.</td>
        </tr>
    </table>

    <div class="footer-note">
        Feita com 💜 e magia por <strong>PIA</strong>. Sempre ativa. Sempre melhor. ✨
    </div>


</div>
</body>
</html>
"""
            body = html_content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_json(404, {"ok": False})

    def log_message(self, fmt, *args):
        logging.info("%s - %s", self.address_string(), fmt % args)


# ==============================================================================
# TRATAMENTO DE TEXTO (Isolado no processo leve)
# ==============================================================================
def clean_text(text):
    import re

    # Remove caracteres nulos
    text = text.replace("\x00", " ")
    # Normaliza quebras de linha
    text = re.sub(r"\r\n?", "\n", text)
    # Remove links Markdown, mantendo apenas o texto visível.
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove blocos de código Markdown.
    text = re.sub(r"```(?:\w+)?\s*([\s\S]*?)```", r"\1", text)
    # Remove código inline.
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove negrito e itálico Markdown.
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"(?<!\w)\*(.*?)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_(.*?)_(?!\w)", r"\1", text)
    # Remove cabeçalhos Markdown.
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    # Remove citações Markdown.
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    # Remove marcadores de listas.
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    # Remove marcadores de checkbox.
    text = re.sub(r"(?m)^\s*\[[ xX]\]\s*", "", text)
    # Remove linhas horizontais Markdown.
    text = re.sub(r"(?m)^\s*([-*_])(?:\s*\1){2,}\s*$", "", text)
    # Remove espaços repetidos.
    text = re.sub(r"[ \t]+", " ", text)
    # Reduz excesso de linhas vazias.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def log_tts_text(text: str):
    if text and text.strip():
        clean_entry = text.strip().replace("\r\n", " ").replace("\n", " ")
        logger_tts.info(clean_entry)


def run_http_server():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    logging.info("Servidor HTTP leve iniciado em http://%s:%d", HOST, PORT)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor...")
    finally:
        PLAYER.stop()
        TTS_MANAGER.stop_worker()
        try:
            server.server_close()
        except Exception:
            pass
