#Requires AutoHotkey v2.0
#SingleInstance Force
Persistent

; Configurações da fala
Voice := "pm_santa"   ; Ex: "pm_santa", "pf_dora", etc.
Speed := 0.95          ; Ex: 0.85 (lento), 1.0 (normal), 1.25 (rápido)

StartSound := A_ScriptDir "..\..\sounds\start.mp3"
EndSound := A_ScriptDir "..\..\sounds\end.mp3"

; ============================================================
; ÚNICO COMANDO: Ctrl + Alt + T
; Se estiver lendo:                  para.
; Se não estiver lendo:              lê o clipboard.
; ============================================================
^!t:: {
    global Voice, Speed, StartSound, EndSound

    status := GetServerStatus()

    ; --------------------------------------------------------
    ; Servidor não está rodando.
    ; --------------------------------------------------------
    if (status = "") {
        ToolTip("Servidor Kokoro TTS não está rodando!")
        SetTimer(() => ToolTip(), -2500)
        return
    }

    ; --------------------------------------------------------
    ; Se estiver reproduzindo, para.
    ; --------------------------------------------------------
    if (
        status = "generating"
        || status = "playing"
        || status = "paused"
    ) {
        HttpPost("/stop", "{}")

        ; if FileExist(EndSound) {
        ;     SoundPlay(EndSound)
        ; }

        ToolTip("Leitura parada")
        SetTimer(() => ToolTip(), -1000)
        return
    }

    ; --------------------------------------------------------
    ; Servidor está idle. Lê o clipboard.
    ; --------------------------------------------------------
    text := A_Clipboard
    if (Trim(text) = "") {
        ToolTip("Área de transferência vazia")
        SetTimer(() => ToolTip(), -1500)
        return
    }

    ; if FileExist(StartSound) {
    ;     SoundPlay(StartSound)
    ; }

    ; Monta o JSON com text, voice e speed
    payload := '{"text":"' JsonEscape(text) '", "voice":"' Voice '", "speed":' Speed '}'

    ; O servidor recebe a chamada.
    HttpPost("/speak", payload)
    
    ToolTip("Enviado para leitura...")
    SetTimer(() => ToolTip(), -1000)
}

; ============================================================
; Verifica o estado atual do servidor.
; ============================================================
GetServerStatus() {
    try {
        req := ComObject("WinHttp.WinHttpRequest.5.1")
        req.Open("GET", "http://127.0.0.1:8765/status", false)
        req.Send()

        if (req.Status != 200)
            return ""

        response := req.ResponseText

        if RegExMatch(response, '"status"\s*:\s*"([^"]+)"', &match) {
            return match[1]
        }

        return "idle"
    } catch {
        return ""
    }
}

; ============================================================
; Envia POST para o servidor.
; ============================================================
HttpPost(path, body) {
    try {
        req := ComObject("WinHttp.WinHttpRequest.5.1")
        req.Open("POST", "http://127.0.0.1:8765" path, false)
        req.SetRequestHeader("Content-Type", "application/json; charset=utf-8")
        req.Send(body)

        return req.Status = 200
    } catch as err {
        ToolTip("Erro ao comunicar com Kokoro: " err.Message)
        SetTimer(() => ToolTip(), -3000)
        return false
    }
}

; ============================================================
; Escapa texto para JSON.
; ============================================================
JsonEscape(text) {
    text := StrReplace(text, "\", "\\")
    text := StrReplace(text, '"', '\"')
    text := StrReplace(text, "`r", "\r")
    text := StrReplace(text, "`n", "\n")
    text := StrReplace(text, "`t", "\t")
    return text
}