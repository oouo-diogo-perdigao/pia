#Requires AutoHotkey v2.0
#SingleInstance Force
Persistent

; ============================================================
; ÚNICO COMANDO: Ctrl + Alt + T
; Funciona exatamente como falar a palavra de comando (Wakeword)
; ============================================================
^!p:: {
    try {
        req := ComObject("WinHttp.WinHttpRequest.5.1")
        req.Open("POST", "http://127.0.0.1:8760/trigger", false)
        req.Send("{}")

        if (req.Status = 200) {
            ToolTip("Sessão de voz iniciada!")
            SetTimer(() => ToolTip(), -1200)
        } else {
            ToolTip("Falha na resposta do Servidor Wakeword")
            SetTimer(() => ToolTip(), -2000)
        }
    } catch as err {
        ToolTip("Servidor Wakeword não está rodando na porta 8760")
        SetTimer(() => ToolTip(), -2000)
    }
}