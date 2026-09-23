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
