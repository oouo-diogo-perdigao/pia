Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Obtém o caminho da pasta onde o arquivo .vbs está salvo
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Define o diretório de trabalho dois níveis acima (onde está o package.json)
targetDir = fso.GetAbsolutePathName(scriptDir & "\..\..\")

' Executa o comando npm run stt no diretório alvo sem exibir janela (0)
WshShell.CurrentDirectory = targetDir
WshShell.Run "cmd.exe /c npm run stt", 0, False

Set WshShell = Nothing
Set fso = Nothing