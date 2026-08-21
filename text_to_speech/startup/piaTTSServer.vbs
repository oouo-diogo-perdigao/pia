Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Obtém o caminho da pasta onde o arquivo .vbs está salvo
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Define o caminho do Python da .venv e do script server.py
pythonExe = scriptDir & "\..\.venv\Scripts\python.exe"
serverScript = scriptDir & "\..\server_tts.py"

' Executa em segundo plano sem janela (o parâmetro 0 oculta a janela)
WshShell.Run """" & pythonExe & """ """ & serverScript & """", 0, False

Set WshShell = Nothing
Set fso = Nothing