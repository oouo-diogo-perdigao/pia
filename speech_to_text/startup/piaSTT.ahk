#Requires AutoHotkey v2.0
#SingleInstance Force
Persistent

DictationPort := 8762
global IsListening := false

^!d:: {
    global DictationPort, IsListening

    req := ComObject("WinHttp.WinHttpRequest.5.1")

    if (IsListening) {
        req.Open("POST", "http://127.0.0.1:" DictationPort "/stop", true)
        req.Send()

        IsListening := false
        ToolTip("Finalizando...")
				SetTimer(() => ToolTip(), -2000)
				
        return
    }

    req.Open("GET", "http://127.0.0.1:" DictationPort "/stt/start", true)
    req.Send()

    IsListening := true
		ToolTip("Escutando")
}