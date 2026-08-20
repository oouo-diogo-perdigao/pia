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
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```
3. Execute os dois arquivos da pasta `startup`, um atalho foi criado no seu `shell:startup` para a proxima inicialização.

## Atalhos
- Ctrl+Alt+T: Inicia/Para Leitura da clipboard

## GPU
O instalador usa PyTorch 2.11.0 com CUDA 12.8. O script verifica `torch.cuda.is_available()` e usa a GPU automaticamente.

## Segurança
O servidor HTTP escuta somente em `127.0.0.1:8765`; ele não fica exposto na rede.

## **Endpoints da API Local**
O servidor responde no host e porta configurados via `.env` (padrão `127.0.0.1:8765`):

* `POST /speak`: Adiciona o texto enviado à fila de síntese para reprodução direta nas caixas de som locais em segundo plano.
* `POST /stop`: Interrompe a reprodução de áudio em andamento e limpa a fila de processamento local.
* `POST /generate`: Sintetiza o texto enviado e retorna o áudio em formato nativo `audio/wav` no corpo da resposta HTTP (ideal para SillyTavern e clientes web).
* `GET /status`: Retorna o estado atual da aplicação, indicando se o player está reproduzindo áudio, o dispositivo em uso (`cuda`/`cpu`) e se o modelo Kokoro está carregado em memória.