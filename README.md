# PIA

PIA é um assistente pessoal multimodal para Windows que reúne, em um único servidor Python, **Speech-to-Text (STT)**, **Text-to-Speech (TTS)**, **chat/LLM**, **geração e edição de imagens**, **wake word**, comandos locais e uma interface visual de estado.

O projeto expõe APIs compatíveis com partes da API da OpenAI para facilitar integração com clientes como Open WebUI, scripts locais e outras aplicações.

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
  - módulos Python carregados de `Plugins/Skills/`.
- **Overlay/HUD**
  - estados de listening, thinking, processing, speaking e pulse.
- **Atalhos globais**
  - os mesmos comandos no Windows e no Linux, configurados em `shortcuts.yaml`;
  - inserção de texto no cursor;
  - launcher com ícone na bandeja e visualização dos logs.

---

## Requisitos

- Windows ou Linux;
- Python 3.12;
- [uv](https://docs.astral.sh/uv/);
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

A bandeja e a API sobem juntas. Não há um atalho que abra só o servidor.

### Executar agora

**Linux**

```bash
bash startup/piaSATServer.sh
```

**Windows**

Abra `dist\PIA Server Python.exe`. Esse executável sobe a bandeja e a API. Se a pasta `dist` ainda não tiver o arquivo, gere-o na raiz do projeto:

```powershell
uv run pyinstaller --onefile --noconsole --name "PIA Server Python" --icon "pia.ico" --add-data "pia.png;." pia_launcher.py
```

### Iniciar com o computador

Com a PIA aberta, o menu do ícone tem o item **Inicializar**. Marcado, ela entra no próximo login. Desmarcado, não entra.

Se a PIA não estiver aberta, dá para ligar ou desligar na mão:

**Linux.** O login lê `~/.config/autostart/piaSAT.desktop`. Para ligar, o arquivo precisa existir, apontar para `startup/piaSATServer.sh` e conter `X-GNOME-Autostart-enabled=true`. O `install.ps1` grava isso. Para desligar, apague o arquivo ou mude essa chave para `false`.

**Windows.** A pasta Inicializar do usuário (`shell:startup`) precisa ter um atalho `PIA.lnk` cujo destino é `dist\PIA Server Python.exe`. Crie esse atalho para ligar. Apague o atalho para desligar. O executável tem de existir antes.

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

## API de transcrição com timestamps e legendas

`POST /v1/audio/transcriptions` aceita multipart (`file`) ou JSON Base64
(`input_audio.data` e `input_audio.format`). `model=whisper-1` é um alias de
compatibilidade: os providers são escolhidos por `STT_PROVIDERS`.

Exemplo importável no Postman (no PowerShell, use `curl.exe` em uma linha):

```bash
curl --request POST 'http://127.0.0.1:8762/v1/audio/transcriptions' \
  --header 'Authorization: Bearer local' \
  --form 'file=@podcast.mp3' \
  --form 'model=whisper-1' \
  --form 'language=pt' \
  --form 'response_format=verbose_json'
```

Para exigir esse token, configure `OPENAI_COMPAT_API_KEY=local` no servidor.
Se a variável estiver vazia, a autenticação continua opcional. Não configure o
header Content-Type manualmente ao enviar multipart.

Contrato dos formatos:

- `json` (padrão): `{"text":"..."}`, preservando os clientes existentes.
- `text`: texto UTF-8.
- `verbose_json`: `task`, `language`, `duration`, `text` e `segments`.
  `duration` é a duração integral do áudio em segundos, incluindo silêncios.
  Cada segmento contém `id` (índice a partir de zero), `start`, `end` e `text`.
  Os tempos são segundos relativos ao início do arquivo enviado, sem remover pausas.
  Não há timestamps por palavra neste contrato.
- `srt`: legendas UTF-8, MIME `application/x-subrip`, tempos `HH:MM:SS,mmm`.
- `vtt`: legendas UTF-8, MIME `text/vtt`, cabeçalho `WEBVTT` e tempos `HH:MM:SS.mmm`.
  Ambos usam os mesmos segmentos do `verbose_json`, arredondados a milissegundos.

Exemplo ilustrativo de resposta:

```json
{
  "task": "transcribe",
  "language": "pt",
  "duration": 105.0,
  "text": "Primeira fala. Segunda fala.",
  "segments": [
    {"id": 0, "start": 2.25, "end": 3.5, "text": "Primeira fala."},
    {"id": 1, "start": 93.1, "end": 94.2, "text": "Segunda fala."}
  ]
}
```

Para obter arquivos de legenda, troque `response_format` e salve a resposta:

```bash
curl 'http://127.0.0.1:8762/v1/audio/transcriptions' \
  -H 'Authorization: Bearer local' -F 'file=@podcast.mp3' \
  -F 'response_format=srt' --output podcast.srt
curl 'http://127.0.0.1:8762/v1/audio/transcriptions' \
  -H 'Authorization: Bearer local' -F 'file=@podcast.mp3' \
  -F 'response_format=vtt' --output podcast.vtt
```

Para `verbose_json`, `srt` e `vtt`, o Gemini Live é pulado porque o adaptador
atual só fornece texto. O Groq é solicitado com `verbose_json`, que fornece
segmentos, e o Faster-Whisper local preserva os tempos nativos do modelo.
Ausência de segmentos reais, falhas ou limites do provedor acionam o próximo
provider configurado. Inclua `local` em `STT_PROVIDERS=gemini,groq,local` para
permitir fallback em arquivos que excedem os limites remotos. Se nenhum provider
configurado conseguir fornecer tempos reais, a rota retorna HTTP 500 com um erro
OpenAI-compatible em `error.message`; nunca fabrica tempos para o texto.
Áudio sem fala é válido: texto vazio, segmentos vazios e duração real; SRT vazio
ou VTT contendo somente o cabeçalho.

O arquivo inteiro é enviado ao provider, sem divisão adicional pela PIA.
O Faster-Whisper processa janelas internas e restaura os timestamps na linha do
tempo original após o VAD, preservando os silêncios. A PIA não concatena janelas
sobrepostas nem deduplica frases iguais (elas podem ser repetições legítimas).
Não é necessário recortar o áudio a cada 30 segundos no cliente.

Limites e dependências:

- `OPENAI_COMPAT_MAX_UPLOAD_BYTES=209715200`: 200 MiB para o **corpo HTTP inteiro**,
  incluindo overhead multipart ou Base64; excesso retorna HTTP 413.
- `OPENAI_COMPAT_TIMEOUT_SECONDS=180`: espera pelo worker local; aumente no `.env`
  para podcasts longos e ajuste também os timeouts do cliente/proxy. A execução
  local usa memória proporcional ao áudio decodificado; o limite de upload não
  garante que qualquer duração caiba na memória disponível.
- Não foram adicionados pacotes. O decoder PyAV de `faster-whisper` mede a duração
  integral no caminho Groq com timestamps. O caminho local usa a duração medida
  pelo próprio Faster-Whisper e VAD (ONNX Runtime), já presentes nas dependências.
  O modelo local precisa estar disponível ou ser baixado no primeiro uso.

Testes offline da API, providers, worker e legendas:
`python -m unittest discover -s tests -p test_transcription.py`.
Os providers/modelos e o desktop são substituídos por mocks; os testes HTTP usam
um servidor real em loopback.

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

A política `LLM_MODEL` vale para chamadas internas e para `/v1/chat/completions` quando o cliente omite `model`. O campo `model` da requisição pode sobrescrever essa política.

```dotenv
LLM_MODEL=free
LLM_PROVIDERS=gemini,groq,local
LLM_REMOTE_COOLDOWN_SECONDS=300
```

A hierarquia é cumulativa: `all` e `paid` permitem modelos pagos, gratuitos e locais; `free` permite gratuitos e locais; `local` permite apenas locais. `all` e `paid` são equivalentes enquanto o catálogo contiver essas três categorias.

| Seletor | Modelos permitidos |
|---|---|
| `free` | Gratuitos e locais |
| `all-local` | Todos os remotos configurados |
| `+gemini=free` | Apenas Gemini gratuitos |
| `free-local+gemini=paid` | Gratuitos remotos e Gemini pagos |
| `all-groq` | Todos, exceto Groq |
| `local+openrouter=free` | Locais e OpenRouter gratuitos |

`+` inclui e `-` exclui, da esquerda para a direita. `provider=tier` aplica a hierarquia dentro daquele provider. Um seletor iniciado por `-` parte de todos os modelos; um iniciado por `+` parte de nenhum. As operações alteram a seleção, preservando a ordem de fallback do catálogo. Um ID exato anunciado em `/v1/models`, como `gemini/gemini-3.8-flash`, seleciona somente aquele modelo. Os aliases antigos `my-agent` e `gemini-local` usam `LLM_MODEL`.

## Gemini e ordem de fallback

A lista padrão, classificada como gratuita pela configuração da PIA, é:

```text
gemini-3.8-flash
gemini-3.7-flash
gemini-3.6-flash
gemini-3.5-flash
gemini-3-flash-preview
gemini-2.5-flash
gemini-3.5-flash-lite
gemini-3.1-flash-lite
gemini-2.5-flash-lite
```

Configure `LLM_GEMINI_FREE_MODELS` para substituir essa lista e `LLM_GEMINI_PAID_MODELS` para acrescentar modelos pagos (nomes separados por vírgula). Os nomes são tentados na ordem informada. Erros de quota, acesso, modelo inexistente ou conexão fazem a PIA tentar o próximo candidato. O cooldown é por provider/modelo, sem bloquear os outros Gemini. Providers sem credenciais são ignorados.

A PIA não confirma que um modelo existe ou está disponível no nível gratuito da sua conta e não altera a configuração de faturamento do provedor. As categorias são regras locais de seleção, não limites de custo. Revise as listas conforme sua conta.

## Providers e catálogo

`LLM_PROVIDERS` define a ordem dos providers. Dentro de cada provider, a PIA tenta a lista gratuita e depois a paga, filtradas pelo seletor. O local usa `LLM_LOCAL_MODEL` (ou a lista ordenada `LLM_LOCAL_MODELS`) e `LLM_LOCAL_API_BASE` (padrões `ollama/qwen3:8b` e `http://localhost:11434`).

- Gemini: `AGE_GEMINI_API_KEY`, com fallback para `GEMINI_API_KEY`.
- Groq: `GROQ_API_KEY`; a lista gratuita usa `LLM_GROQ_FREE_MODELS` ou, se ausente, `LLM_GROQ_MODEL`. Modelos pagos: `LLM_GROQ_PAID_MODELS`.
- OpenRouter: acrescente `openrouter` a `LLM_PROVIDERS`, configure `OPENROUTER_API_KEY`, `LLM_OPENROUTER_FREE_MODELS` e/ou `LLM_OPENROUTER_PAID_MODELS`.
- Cloudflare: acrescente `cloudflare` a `LLM_PROVIDERS`, configure `CLOUDFLARE_API_KEY`, `LLM_CLOUDFLARE_API_BASE` conforme sua integração e `LLM_CLOUDFLARE_FREE_MODELS` e/ou `LLM_CLOUDFLARE_PAID_MODELS`.

As listas aceitam IDs LiteLLM com ou sem o prefixo do provider. Não há modelos OpenRouter/Cloudflare habilitados por padrão. Use as categorias conforme o plano da sua conta. `LLM_GEMINI_MODEL` foi substituído pelas listas Gemini.

Para outras integrações, `LLM_MODEL_CATALOG` aceita uma lista JSON de entradas adicionais, sem chaves secretas:

```dotenv
LLM_MODEL_CATALOG='[{"provider":"custom","model":"openai/my-model","tier":"paid","api_key_env":"CUSTOM_API_KEY","api_base_env":"CUSTOM_API_BASE"}]'
```

`model` deve ser um ID aceito pelo LiteLLM; `api_key_env` e `api_base_env` são nomes de variáveis de ambiente. As entradas adicionais ficam após as listas padrão. O seletor também aceita `+custom=paid` e `-custom`.

`GET /v1/models` anuncia `all`, `paid`, `free`, `local` e os IDs configurados, além dos modelos de áudio/imagens. Essa listagem representa o catálogo, não uma verificação de credenciais. As políticas LLM se aplicam ao chat e às chamadas de chat internas (inclusive classificação de vozes via `TTS_LLM_MODEL`); os IDs dos endpoints de STT, síntese e imagens continuam específicos de cada modalidade.

## API e streaming

```json
{
  "model": "free-local+gemini=paid",
  "messages": [
    {"role": "system", "content": "Responda em português."},
    {"role": "user", "content": "Olá!"}
  ],
  "stream": false
}
```

A API preserva o histórico de mensagens, ferramentas e opções como `temperature`, `max_tokens` e `response_format`; responde com o modelo realmente usado. Seletores inválidos retornam HTTP 400; esgotamento dos candidatos retorna HTTP 503, sem apresentar erro como resposta de sucesso.

Com `stream=true`, há fallback se a falha ocorrer antes de qualquer conteúdo ou chamada de ferramenta. Depois que a resposta começa, a PIA não a reinicia em outro modelo. Falhas posteriores são sinalizadas como erro SSE, encerrando com `[DONE]`.

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

Executar a bandeja e a API: no Linux, `bash startup/piaSATServer.sh`; no Windows, `dist\PIA Server Python.exe`. O item **Inicializar** do ícone liga ou desliga a entrada no login.

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

### Progresso de transcrição local

A aba `stt` do visualizador mostra preparação e progresso de arquivos transcritos pelo Whisper local. O percentual acompanha os segmentos na linha do tempo original; pode avançar em saltos nos silêncios removidos pelo VAD. O estado 100% só aparece após concluir a iteração dos segmentos. O limite `STT_GROQ_MAX_UPLOAD_BYTES=25000000` evita uploads acima de 25 MB ao Groq e passa ao próximo provedor sem aplicar cooldown ao Groq. Reinicie servidor e visualizador após atualizar; executáveis empacotados do launcher precisam ser reconstruídos.

### Whisper local na GPU

Para uma NVIDIA com bibliotecas CUDA/cuDNN compatíveis, use `STT_DEVICE=cuda` e `STT_COMPUTE_TYPE=float16` no `.env`. A instalação local com RTX 3080 de 10 GB foi validada com inferência CUDA real usando o modelo em cache. O log informa dispositivo e precisão efetivos. O ajuste vale para todas as transcrições do Whisper local, mantendo a ordem dos provedores e uma tarefa por worker. Reinicie a PIA para carregar a configuração; não é necessário interromper uma transcrição em andamento. Para economizar VRAM, pode-se avaliar `int8_float16`; para retornar à CPU, use `cpu` e `int8`.

## Skills de voz e plugins

Os comandos agora são projetos em `Plugins/Skills`, com `plugin.toml` e uma função `execute` que recebe APIs da PIA. Leia [o guia das skills](docs/SKILLS.md) e veja [o projeto de exemplo](Plugins/Skills/exemplo/README.md). As integrações de navegador ficam em `Plugins/Browser`, incluindo o userscript IsekaiZero.
