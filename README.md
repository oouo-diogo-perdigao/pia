# PIA

PIA é um assistente pessoal multimodal para Windows que reúne, em um único servidor Python, **Speech-to-Text (STT)**, **Text-to-Speech (TTS)**, **chat/LLM**, **geração e edição de imagens**, **wake word**, comandos locais e uma interface visual de estado.

O projeto expõe APIs compatíveis com partes da API da OpenAI para facilitar integração com clientes como Open WebUI, scripts locais, AutoHotkey e outras aplicações.

![PIA](./pia.png)

## Principais recursos

- **STT híbrido com fallback automático**
  - Gemini 3.5 Transcribe Live;
  - Groq Whisper via LiteLLM;
  - Faster-Whisper local.
- **Chat com fallback de providers**
  - Gemini;
  - Groq;
  - modelo local via Ollama.
- **TTS local**
  - Kokoro ONNX;
  - Qwen3-TTS.
- **Imagens**
  - geração, edição e variações através do ComfyUI;
  - interface OpenAI-compatible.
- **Wake word**
  - detecção local com sherpa-onnx;
  - palavra-chave configurável por arquivo.
- **Comandos locais dinâmicos**
  - módulos Python carregados de `src/commands/`.
- **Overlay/HUD**
  - estados de listening, thinking, processing, speaking e pulse.
- **Integração Windows**
  - inserção de texto no cursor;
  - AutoHotkey;
  - launcher com visualização dos logs.

---

## Requisitos

- Windows;
- Python 3.12;
- [uv](https://docs.astral.sh/uv/);
- AutoHotkey v2 para os atalhos;
- SoX para partes do pipeline de áudio;
- Ollama apenas se o fallback LLM local for utilizado;
- ComfyUI apenas se os endpoints de imagem forem utilizados;
- GPU/CUDA é opcional para vários recursos, mas recomendada para os modelos locais mais pesados.

---

## Instalação

Na raiz do projeto:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

O instalador usa `uv`, cria o ambiente virtual quando necessário, executa `uv sync` e cria `.env` a partir de `.env.example` quando o arquivo ainda não existe.

Também é possível preparar manualmente:

```powershell
uv venv
uv sync
Copy-Item .env.example .env
```

Para iniciar diretamente:

```powershell
uv run python -m server
```

---

# Configuração

Toda a configuração principal fica no arquivo `.env`.

## Servidor

```dotenv
HOST=127.0.0.1
PORT=8762
OPENAI_COMPAT_API_KEY=local
PUBLIC_BASE_URL=http://127.0.0.1:8762
```

Se `OPENAI_COMPAT_API_KEY` estiver vazio, os endpoints OpenAI-compatible ficam sem autenticação.

---

# Speech-to-Text

O STT recebe áudio do microfone, separa enunciados por silêncio e tenta os providers na ordem definida em:

```dotenv
STT_PROVIDERS=gemini,groq,local
```

A ordem é literal. Com a configuração acima:

1. tenta Gemini;
2. se Gemini estiver sem chave, falhar ou entrar em cooldown, tenta Groq;
3. se Groq também não estiver disponível, usa Faster-Whisper local.

Providers remotos que falham ficam temporariamente em cooldown para evitar repetir a mesma chamada inútil em cada frase.

## Gemini STT

```dotenv
STT_GEMINI_API_KEY=
STT_GEMINI_MODEL=gemini-3.5-transcribe-live
STT_REMOTE_COOLDOWN_SECONDS=900
```

A chave STT dedicada tem prioridade. Se não estiver configurada, o código também aceita `GEMINI_API_KEY` ou `AGE_GEMINI_API_KEY`.

## Groq STT

```dotenv
GROQ_API_KEY=
STT_GROQ_MODEL=groq/whisper-large-v3-turbo
```

A chamada é feita por `litellm.transcription()`.

## STT local

```dotenv
STT_MODEL=large-v3-turbo
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
STT_CPU_THREADS=8
STT_SAMPLE_RATE=16000
STT_CHANNELS=1
STT_WHISPER_TIMEOUT=600
```

O Faster-Whisper é carregado em processo separado e pode ser descarregado após inatividade.

## Ditado

O `STTManager` apenas transcreve e distribui texto. A decisão de inserir texto no cursor pertence à camada `LocalActions`.

O fluxo usado pelo atalho de ditado é:

```text
Ctrl+Alt+D
  -> POST /action/local-record {"insert_at_cursor": true}
  -> AudioRecorder
  -> STTManager
  -> Gemini / Groq / Faster-Whisper
  -> LocalActions
  -> clipboard temporário
  -> Ctrl+V na janela ativa
```

Sessões iniciadas por wake word usam a mesma gravação com `insert_at_cursor=false`, portanto a transcrição vira comando/agente e não é colada automaticamente.

---

# Chat / LLM

A rota `/v1/chat/completions` usa a mesma ideia de fallback ordenado:

```dotenv
LLM_PROVIDERS=gemini,groq,local
```

Com essa configuração, o chat tenta Gemini, depois Groq e, por último, Ollama local.

## Modelos padrão

```dotenv
LLM_GEMINI_MODEL=gemini/gemini-3.5-flash
LLM_GROQ_MODEL=groq/openai/gpt-oss-120b
LLM_LOCAL_MODEL=ollama/qwen3:8b
LLM_LOCAL_API_BASE=http://localhost:11434
LLM_REMOTE_COOLDOWN_SECONDS=300
```

Credenciais:

```dotenv
AGE_GEMINI_API_KEY=
GROQ_API_KEY=
```

O provider Gemini também aceita `GEMINI_API_KEY` como fallback de credencial.

O runtime não depende mais de `models.yaml` para determinar a prioridade do chat. A ordem dos providers é definida diretamente por `LLM_PROVIDERS`.

## Streaming

`/v1/chat/completions` suporta `stream=true`.

Se um provider falhar antes de gerar o primeiro chunk, o próximo provider é tentado. Se a transmissão já começou, o servidor não reinicia a resposta em outro modelo, evitando texto duplicado no mesmo stream.

---

# Text-to-Speech

O serviço de TTS possui backends locais e roda modelos pesados em workers isolados.

Principais configurações:

```dotenv
TTS_DEFAULT_VOICE=pm_santa
TTS_DEFAULT_SPEED=0.95
TTS_DEVICE=cuda
TTS_KOKORO_MODEL=./cache/Kokoro-82M
TTS_KOKORO_IDLE_TIMEOUT=600
TTS_QWEN_IDLE_TIMEOUT=600
```

Modelos anunciados pela API:

- `tts-1`;
- `tts-1-hd`;
- `gpt-4o-mini-tts`;
- `gpt-4o-mini-tts-2025-12-15`.

Formatos suportados pelo gateway incluem WAV, MP3, Opus, AAC, FLAC e PCM.

---

# Imagens / ComfyUI

A PIA expõe um gateway OpenAI-compatible para o ComfyUI.

Modelo anunciado:

```text
gpt-image-1
```

Principais endpoints:

- `POST /v1/images/generations`;
- `POST /v1/images/edits`;
- `POST /v1/images/variations`;
- `GET /v1/images/files/<token>`.

O gateway suporta layouts de modelo `checkpoint` e `split`, serialização de jobs e liberação automática de RAM/VRAM após o processamento quando configurado.

Exemplo:

```dotenv
ICE_COMFYUI_URL=http://127.0.0.1:8188
ICE_COMFYUI_MODEL_LAYOUT=checkpoint
ICE_COMFYUI_CHECKPOINT=flux1-schnell.safetensors
ICE_IMAGE_DEFAULT_SIZE=1024x1024
ICE_IMAGE_MAX_N=1
```

---

# Wake word e comandos locais

O listener de wake word usa `sherpa-onnx` e mantém um microfone dedicado aguardando a palavra-chave configurada.

Os comandos Python são carregados dinamicamente de:

```text
src/commands/
```

Um módulo de comando precisa expor:

```python
COMMAND_NAME = "meu comando"

def execute():
    ...
```

A versão atual inclui comandos para:

- abrir bloco de notas;
- abrir navegador;
- aprender novo comando;
- previsão do tempo;
- modo ditado;
- recarregar comandos.

Quando uma fala começa com `comando`, o loader tenta encontrar a ação local mais próxima. Caso não haja correspondência suficiente, o texto é repassado ao agente.

---

# Overlay / OVE

A interface visual mantém contadores/estados para atividades do assistente.

Rotas disponíveis:

- `GET /ove/status`;
- `POST /ove/start`;
- `POST /ove/stop`;
- `POST /ove/blink`;
- `POST /ove/thinking`;
- `POST /ove/processing`;
- `POST /ove/speaking`;
- `POST /ove/silent`;
- `POST /ove/listening`;
- `POST /ove/pulse`.

---

# API HTTP

## OpenAI-compatible

| Método | Endpoint | Função |
|---|---|---|
| GET | `/v1/models` | Lista modelos expostos pelo gateway |
| POST | `/v1/chat/completions` | Chat, com streaming opcional e fallback LLM |
| POST | `/v1/audio/transcriptions` | Transcrição de áudio com fallback STT |
| POST | `/v1/audio/speech` | Síntese de voz |
| GET | `/v1/audio/voices` | Lista vozes disponíveis |
| POST | `/v1/images/generations` | Geração de imagem |
| POST | `/v1/images/edits` | Edição de imagem |
| POST | `/v1/images/variations` | Variação de imagem |

`/v1/audio/translations` e `/v1/audio/voice_consents` existem apenas como respostas explícitas de não implementação.

## Local Actions

| Método | Endpoint | Função |
|---|---|---|
| POST | `/action/text-at-cursor` | Insere texto ou imagem no controle atualmente focado |
| GET | `/action/text-at-cursor` | Seleciona/copia e retorna o texto do controle focado |
| DELETE | `/action/text-at-cursor` | Seleciona e remove todo o conteúdo do controle focado |
| GET | `/action/screen` | Retorna PNG do monitor onde está o cursor do mouse |
| GET | `/action/screen-all` | Retorna PNG contendo todos os monitores |
| POST | `/action/local-record` | Inicia gravação STT; aceita `{"insert_at_cursor": true|false}` |
| DELETE | `/action/local-record` | Encerra a gravação STT |
| GET | `/action/local-record` | Retorna status e textos pendentes |
| GET | `/action/local-record/stream` | Stream SSE de transcrições |
| POST | `/action/play-audio` | Reproduz áudio imediatamente em canal independente; chamadas podem sobrepor |
| DELETE | `/action/play-audio` | Para um áudio imediato por `id`; sem `id`, para todos os imediatos |
| POST | `/action/play-audio-queue` | Enfileira áudio para reprodução estritamente sequencial |
| DELETE | `/action/play-audio-queue` | Para o atual e limpa a fila; com `{"next": true}`, apenas pula o atual |
| POST | `/action/image` | Salva a imagem recebida e abre no navegador padrão |

`/action/text-at-cursor` aceita JSON com `text`, JSON com imagem em data URL, `text/plain`, `image/*` ou multipart. As rotas de áudio aceitam conteúdo bruto ou multipart. `POST /action/play-audio` também aceita JSON como `{"path":"D:\\\\codes\\\\pia\\\\sounds\\\\end.mp3"}` para tocar um arquivo absoluto do Windows. A fila e os áudios imediatos usam canais independentes.

## Storytelling

`POST /tts/storytelling` aceita o modo opcional:

```json
{
  "text": "[Ayla] \"Olá.\" O vento sopra.",
  "kokoro": "only"
}
```

Com `kokoro: "only"`, todos os trechos são processados pelo Kokoro: narração usa `pm_santa`, falas femininas usam `pf_dora` e falas masculinas ou de gênero desconhecido usam `pm_alex`. Sem esse parâmetro, o storytelling mantém a seleção normal de vozes/personagens.

O userscript `Plugins/isekai0.js` possui toggles para TTS, Kokoro-only e STT. O STT sempre inicia desligado ao carregar a página e só mantém a gravação aberta enquanto existe uma `textarea` visível. As transcrições são inseridas diretamente no campo; a sentença isolada `enviar` simula `Shift+Enter`.

## TTS

- `GET /tts/status`;
- `GET /tts/status/stream`;
- `GET /tts/help`;
- `POST /tts/speak`;
- `POST /tts/storytelling`;
- `POST /tts/stream_text`;
- `POST /tts/stop`;
- `POST /tts/generate`.

---

# Logs

Os logs ficam em `logs/`.

| Arquivo | Conteúdo |
|---|---|
| `_main.log` | Eventos gerais do servidor |
| `stt.log` | Somente textos efetivamente transcritos |
| `tts.log` | Eventos/textos do TTS |
| `llm.log` | Entradas, saídas e provider/modelo do chat |

O `stt.log` usa uma única linha por transcrição:

```text
2026-10-05 19:26:10,450 | INFO | Exemplo de transcrição
```

O log periódico de RMS do microfone (`[AUDIO DEBUG]`) não é emitido.

---

# Estrutura principal

```text
PIA
├── server.py
├── pia_launcher.py
├── src/
│   ├── HTTPServer.py
│   ├── STTManager.py
│   ├── LocalActions.py
│   ├── HybridSTTManager.py
│   ├── AudioRecorder.py
│   ├── VoiceAgent.py
│   ├── TTSManager.py
│   ├── ICEManager.py
│   ├── ComfyUIClient.py
│   ├── WorkflowFactory.py
│   ├── PiaOverlay.py
│   ├── thread_wakeword.py
│   ├── commands_loader.py
│   ├── commands/
│   └── agents/
│       ├── AgentManager.py
│       └── GenericAgent.py
├── startup/
├── sounds/
├── .env.example
└── pyproject.toml
```

---

# Execução e desenvolvimento

Executar servidor:

```powershell
uv run python -m server
```

Sincronizar dependências:

```powershell
uv sync
```

A aplicação foi estruturada para manter modelos pesados em workers/processos separados sempre que possível, permitindo liberar RAM/VRAM durante períodos de inatividade.

---

## Observações de segurança

- Não coloque chaves reais no repositório.
- Mantenha `.env` fora do Git.
- Se expuser `HOST=0.0.0.0`, configure `OPENAI_COMPAT_API_KEY` e proteja a rede.
- O fallback local permite continuar usando STT e chat sem depender exclusivamente de APIs externas, desde que os modelos locais necessários estejam instalados.
