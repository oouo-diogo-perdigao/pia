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

* `POST /start`: Inicia a captura de áudio pelo microfone.
* `POST /stop`: Interrompe a gravação e processa o trecho final.
* `GET /status`: Retorna o estado atual da gravação, transcrição e entrega os blocos de texto processados.