#Requires AutoHotkey v2.0
#SingleInstance Force
Persistent

DictationPort := 8762
StartSound := A_ScriptDir "..\..\sounds\start.mp3"
EndSound := A_ScriptDir "..\..\sounds\end.mp3"

global IsListening := false
global AnimFrame := 0
global ConnectionFailures := 0 ; Contador para tratar erros de conexão

; ============================================================
; ÚNICO COMANDO: Ctrl + Alt + D
; ============================================================
^!d:: {
    global DictationPort, StartSound, EndSound, IsListening, ConnectionFailures

    if (IsListening) {
        ; Dispara o stop em segundo plano (assíncrono)
        HttpPostAsync("/stop", "{}")

        ; Parar Gravação
        IsListening := false
        ToolTip("Processando áudio...")
        
        if FileExist(EndSound) {
            SoundPlay(EndSound)
        }
        return
    }

    ; 1. Dispara a requisição HTTP em paralelo imediatamente
		req := ComObject("WinHttp.WinHttpRequest.5.1")
    req.Open("GET", "http://127.0.0.1:" DictationPort "/start", false)
		req.Send()

    ; 2. Atualiza interface e áudio INSTANTANEAMENTE ao apertar a tecla
    IsListening := true
    ConnectionFailures := 0 ; Reseta o contador de erros
    ToolTip("Escutando")
    if FileExist(StartSound) {
        SoundPlay(StartSound)
    }

    ; 3. Inicia o Polling para checar resposta e capturar áudio
    SetTimer(PollTranscription, 150)
}

PollTranscription() {
    global DictationPort, IsListening, AnimFrame, ConnectionFailures

    req := ComObject("WinHttp.WinHttpRequest.5.1")
    try {
        req.Open("GET", "http://127.0.0.1:" DictationPort "/status", false)
        req.Send()

        if (req.Status == 200) {
            ConnectionFailures := 0 ; Sucesso! Reseta falhas
            body := req.ResponseText
            
            isSpeaking := InStr(body, '"is_speaking": true')
            isTranscribing := InStr(body, '"is_transcribing": true')
            
            ; 1. Atualiza feedback visual
            if (IsListening) {
                if (isSpeaking || isTranscribing) {
                    AnimFrame := Mod(AnimFrame + 1, 3)
                    if (AnimFrame == 0)
                        ToolTip("Escutando .  ")
                    else if (AnimFrame == 1)
                        ToolTip("Escutando .. ")
                    else
                        ToolTip("Escutando ...")
                } else {
                    ToolTip("Escutando")
                }
            }

            ; 2. Captura e digita qualquer texto retornado
            hasNewText := false
            if RegExMatch(body, '"text_chunks"\s*:\s*\[(.*?)\]', &match) {
                chunks := match[1]
                Loop Parse, chunks, "," {
                    item := Trim(A_LoopField, ' "')
                    if (item != "") {
                        SendText(item " ")
                        hasNewText := true
                    }
                }
            }

            ; 3. Encerramento normal quando pausado
            if (!IsListening && !isTranscribing && !hasNewText) {
                SetTimer(PollTranscription, 0)
                ToolTip() ; Remove a mensagem da tela
            }
        }
    } catch {
        ; Se o servidor estiver offline, o catch será acionado.
        ; Se falhar 3 vezes consecutivas (450ms), encerra e avisa o usuário.
        ConnectionFailures++
        if (IsListening && ConnectionFailures >= 3) {
            IsListening := false
            SetTimer(PollTranscription, 0)
            ToolTip("Erro ao conectar no servidor!")
            SetTimer(() => ToolTip(), -2000)
        }
    }
}

; Função para disparar HTTP POST sem bloquear o script (Assíncrono)
HttpPostAsync(path, body) {
    global DictationPort
    try {
        req := ComObject("WinHttp.WinHttpRequest.5.1")
        req.Open("POST", "http://127.0.0.1:" DictationPort path, true)
        req.SetRequestHeader("Content-Type", "application/json")
        req.Send(body)
    } catch {
        ; Ignora exceções imediatas de disparo
    }
}