# Servidor de Speech to Text (TTS)

Servidor local de **Speech-to-Text (STT)** em Python alimentado por **Faster-Whisper** e integrado ao Windows via **AutoHotkey (AHK)**.

Ao acionar o atalho no teclado, o sistema capta o áudio do microfone, processa a transcrição em tempo real via modelos Whisper e digita o texto automaticamente na janela ativa.

Custo de memoria parado < 2 mb


## Instaladores e Pré-requisitos
- (AutoHotKey)[https://www.autohotkey.com/]
* Python 3.12


## 🚀 Instalação
1. Abra PowerShell nesta pasta.
2. Execute:
```powershell
cd speech_to_text
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```
3. Execute os dois arquivos da pasta `startup`, um atalho foi criado no seu `shell:startup` para a proxima inicialização.


## Atalhos
- Ctrl+Alt+D: Inicia/Para Transcrição de voz


## **5. Endpoints da API Local**
O servidor responde no host e porta configurados via `.env`:

- `POST /start`: Inicia a captura de áudio pelo microfone.
- `POST /stop`: Interrompe a gravação e processa o trecho final.
- `GET /status`: Retorna o estado atual da gravação, transcrição e entrega os blocos de texto processados.

Padrão OpenAI:
- `POST /v1/audio/transcriptions` 
- `GET /v1/models`
- `OPTIONS` para CORS

O endpoint de transcrição aceita:

- `multipart/form-data` no padrão OpenAI (`file`, `model`, `language`, `prompt`, `temperature`, `response_format`);
- upload multipart com `Transfer-Encoding: chunked`, usado pelo Open WebUI quando ele faz streaming do arquivo;
- JSON/Base64 no formato opcional do Open WebUI (`input_audio.data`);
- `response_format=json`, `text` e `verbose_json`.

O campo `model` recebido é aceito para compatibilidade de protocolo. A inferência continua usando o modelo definido por `STT_MODEL` no seu `.env`.



# Servidor de Text to Speech (TTS)

Este projeto executa um servidor em Python (`server.py`) responsável por sintetizar texto em áudio utilizando o modelo neural **Kokoro TTS** e reproduzir o resultado via **SoundDevice**.

Custo de memoria parado < 2 mb

## Instaladores e Pré-requisitos
- (AutoHotKey)[https://www.autohotkey.com/]
- (espeak-ng)[https://github.com/espeak-ng/espeak-ng/releases]
* Python 3.12

## 🚀 Instalação
1. Abra PowerShell nesta pasta.
2. Execute:
```powershell
cd text_to_speech
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```
3. Execute os dois arquivos da pasta `startup`, um atalho foi criado no seu `shell:startup` para a proxima inicialização.

## Atalhos
- Ctrl+Alt+T: Inicia/Para Leitura da clipboard

## GPU
O instalador usa PyTorch 2.11.0 com CUDA 12.8. O script verifica `torch.cuda.is_available()` e usa a GPU automaticamente.

## Segurança
O servidor HTTP escuta somente local ele não fica exposto na rede.

## **Endpoints da API Local**
O servidor responde no host e porta configurados via `.env`:

* `POST /speak`: Adiciona o texto enviado à fila de síntese para reprodução direta nas caixas de som locais em segundo plano.
* `POST /stop`: Interrompe a reprodução de áudio em andamento e limpa a fila de processamento local.
* `POST /generate`: Sintetiza o texto enviado e retorna o áudio em formato nativo `audio/wav` no corpo da resposta HTTP (ideal para SillyTavern e clientes web).
* `GET /status`: Retorna o estado atual da aplicação, indicando se o player está reproduzindo áudio, o dispositivo em uso (`cuda`/`cpu`) e se o modelo Kokoro está carregado em memória.

Padrão OpenAI:
- `POST /v1/audio/speech`
- `GET /v1/models`


## Endpoints
- `GET /v1/models`
- `POST /v1/images/generations`
- `POST /v1/images/edits`
- `POST /v1/images/variations`
- `GET /health`
- `GET /v1/images/files/<arquivo>` para `response_format=url`

Para o modelo `sd_xl_base_1.0.safetensors` imagens menores que 1024x1024 geram imagens ruins.

## Ciclo de memória

Por padrão os jobs são serializados. Depois de baixar a imagem final do ComfyUI, o gateway executa no `finally`:

1. `GET /queue`;
2. se não houver job rodando ou pendente, `POST /free`;
3. envia `{ "unload_models": true, "free_memory": true }`.

Isso evita que uma requisição descarregue o modelo enquanto outra o utiliza.

## Qual FLUX está instalado?

### Checkpoint all-in-one

O checkpoint oficial all-in-one Schnell FP8 é carregado por `CheckpointLoaderSimple` e deve ficar em `models/checkpoints`.

```env
COMFYUI_MODEL_LAYOUT=checkpoint
COMFYUI_CHECKPOINT=flux1-schnell-fp8.safetensors
```

Seu volume atual atende esse layout:

```yaml
- ./cache:/home/user/ComfyUI/models/checkpoints
```

## Download do modelo
# command: >
#   bash -c "
#   if [ ! -f /home/user/ComfyUI/models/checkpoints/flux1-schnell.safetensors ]; then
#     echo 'Baixando o modelo FLUX.1 Schnell...' &&
#     wget --header=\"Authorization: Bearer $$HF_TOKEN\" -O /home/user/ComfyUI/models/checkpoints/flux1-schnell.safetensors https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/flux1-schnell.safetensors;
#   fi &&
#   exec /home/user/venv/bin/python main.py --highvram --listen 0.0.0.0
#   "

### Split/full

O `flux1-schnell.safetensors` full/split é carregado por `UNETLoader` e exige os text encoders e o VAE separados:

```env
COMFYUI_MODEL_LAYOUT=split
COMFYUI_UNET=flux1-schnell.safetensors
COMFYUI_CLIP_L=clip_l.safetensors
COMFYUI_T5XXL=t5xxl_fp8_e4m3fn.safetensors
COMFYUI_VAE=ae.safetensors
```

Estrutura:

```text
models/diffusion_models/flux1-schnell.safetensors
models/text_encoders/clip_l.safetensors
models/text_encoders/t5xxl_fp8_e4m3fn.safetensors
models/vae/ae.safetensors
```

Nesse caso monte o diretório `models` inteiro no container, não apenas `checkpoints`.

## Testes

### ComfyUI

```powershell
curl.exe http://127.0.0.1:8188/system_stats
curl.exe http://127.0.0.1:8188/models/checkpoints
```

Para split:

```powershell
curl.exe http://127.0.0.1:8188/models/diffusion_models
curl.exe http://127.0.0.1:8188/models/text_encoders
curl.exe http://127.0.0.1:8188/models/vae
```

### Gateway

```powershell
curl.exe http://127.0.0.1:8764/health
curl.exe -H "Authorization: Bearer local" http://127.0.0.1:8764/v1/models
```

### Geração

```powershell
curl.exe -X POST "http://127.0.0.1:8764/v1/images/generations" `
  -H "Authorization: Bearer local" `
  -H "Content-Type: application/json" `
  -d "{\"model\":\"gpt-image-1\",\"prompt\":\"a glass castle under an aurora\",\"size\":\"1024x1024\",\"n\":1,\"response_format\":\"b64_json\"}" `
  -o response.json
```

### Edição

```powershell
curl.exe -X POST "http://127.0.0.1:8764/v1/images/edits" `
  -H "Authorization: Bearer local" `
  -F "model=gpt-image-1" `
  -F "prompt=turn the sky into a dramatic aurora" `
  -F "image=@input.png;type=image/png" `
  -F "response_format=b64_json" `
  -o edit.json
```

### Edição com máscara

O caminho implementado usa o canal alpha do PNG. Áreas transparentes são tratadas como editáveis, coerentemente com a máscara de edição OpenAI e com a máscara retornada pelo `LoadImage` do ComfyUI.

```powershell
curl.exe -X POST "http://127.0.0.1:8764/v1/images/edits" `
  -H "Authorization: Bearer local" `
  -F "model=gpt-image-1" `
  -F "prompt=replace the masked object with a crystal relic" `
  -F "image=@input.png;type=image/png" `
  -F "mask=@mask.png;type=image/png" `
  -F "response_format=b64_json" `
  -o edit-mask.json
```

## Open WebUI

Se o gateway roda no Windows e o Open WebUI em Docker:

```text
Engine: OpenAI
Base URL: http://host.docker.internal:8764/v1
API key: local
Model: gpt-image-1
```

O Open WebUI atual chama `/images/generations` sobre essa base. O gateway devolve `b64_json` por padrão e também suporta `url`.
