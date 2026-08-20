#Requires AutoHotkey v2.0
#SingleInstance Force
Persistent

DictationPort := 8767
StartSound := A_ScriptDir "..\..\sounds\start.mp3"
EndSound := A_ScriptDir "..\..\sounds\end.mp3"

global IsListening := false
global AnimFrame := 0

^!d:: {
    global DictationPort, StartSound, EndSound, IsListening

    if (IsListening) {
        ; Parar Gravação
        IsListening := false
        
        if FileExist(EndSound) {
            SoundPlay(EndSound)
        }
        
        ToolTip("Processando áudio...")
        HttpPost("/stop", "{}")
        
        ; NÃO desligamos o timer aqui! 
        ; O PollTranscription continuará rodando em segundo plano
        ; até drenar todo o texto que o servidor ainda está transcrevendo.
        return
    }

    ; Iniciar Gravação
    ToolTip("Iniciando...")
    if FileExist(StartSound) {
        SoundPlay(StartSound)
    }

    resp := HttpPost("/start", "{}")
    if (resp != "") {
        IsListening := true
        ToolTip("Escutando")
        SetTimer(PollTranscription, 150)
    } else {
        ToolTip("Erro ao conectar no servidor!")
        SetTimer(() => ToolTip(), -2000)
    }
}

PollTranscription() {
    global DictationPort, IsListening, AnimFrame

    req := ComObject("WinHttp.WinHttpRequest.5.1")
    try {
        req.Open("GET", "http://127.0.0.1:" DictationPort "/status", false)
        req.Send()

        if (req.Status == 200) {
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

            ; 2. Captura e digita qualquer texto retornado (mesmo após parar de escutar)
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

            ; 3. Condição de encerramento do Timer quando pausado
            if (!IsListening && !isTranscribing && !hasNewText) {
                SetTimer(PollTranscription, 0)
                ToolTip() ; Remove a mensagem da tela
            }
        }
    } catch {
        ; Silencia exceções de conexão temporárias
    }
}

HttpPost(path, body) {
    global DictationPort
    try {
        req := ComObject("WinHttp.WinHttpRequest.5.1")
        req.Open("POST", "http://127.0.0.1:" DictationPort path, false)
        req.SetRequestHeader("Content-Type", "application/json")
        req.Send(body)
        return req.ResponseText
    } catch {
        return ""
    }
}