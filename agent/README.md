# Voice Agent

Agente pessoal por voz para Windows.

- Segure **Ctrl + Alt + D** para gravar.
- Solte para enviar o áudio à API do Gemini.
- O Gemini transcreve a fala e decide entre responder, executar ações locais, usar memória ou iniciar aprendizado.
- A memória persistente fica em **`data/memory.json`**.
- A LLM nunca recebe um executor de shell arbitrário.

## 1. Instalação

Abra PowerShell nesta pasta e execute:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

Depois abra `.env` e preencha:

```dotenv
GEMINI_API_KEY=SUA_CHAVE_AQUI
```

Por padrão o projeto usa `gemini-3.5-flash-lite` tanto para STT remoto quanto para interpretação.

Execute `stt.ahk` com **AutoHotkey v2**.

## 2. Push-to-talk

```text
Ctrl+Alt+D DOWN  -> POST /start -> gravação local em memória
Ctrl+Alt+D UP    -> POST /stop  -> WAV -> Gemini -> agente
```

O áudio não é transcrito localmente e não há Whisper/CUDA.

## 3. Ações iniciais

### Apagar tudo

Fala:

```text
apaga tudo
```

Executa `Ctrl+A` e `Backspace` no aplicativo ativo.

### Enviar

Fala:

```text
enviar
```

Pressiona `Enter`.

### Abrir programa/site

Exemplos:

```text
abre o Chrome
abre o VS Code
abre o YouTube
```

Programas por nome são abertos pela pesquisa do menu Iniciar. URLs explícitas usam o navegador padrão.

## 4. Perguntas e resposta falada

Perguntas comuns recebem uma resposta curta do Gemini e são enviadas ao TTS.

Para previsão do tempo existe uma ferramenta real baseada em Open-Meteo, sem chave de API adicional:

```text
quantos graus vai fazer amanhã?
```

A localização padrão vem de `DEFAULT_LOCATION` no `.env`.

## 5. TTS

Por padrão:

```dotenv
TTS_MODE=sapi
```

usa `System.Speech` do Windows.

Para usar seu próprio programa de voz:

```dotenv
TTS_MODE=command
TTS_COMMAND=C:\caminho\meu_tts.exe
```

O texto é passado como último argumento. O TTS não usa o clipboard, porque o clipboard é parte do mecanismo de aprendizado.

Se o TTS for um script AHK:

```dotenv
TTS_MODE=command
TTS_COMMAND=C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe
TTS_SCRIPT=C:\caminho\tts.ahk
```

Seu script receberá o texto em `A_Args[1]`.

## 6. Aprendizado de memória

Há uma diferença deliberada entre **aprender um dado** e **aprender código novo**.

### Exemplo: jogo do Roque

Primeira vez:

```text
Você: Abre o jogo do roque no youtube.
Agente: Eu ainda não conheço esse link. Copie o link correto e depois diga pronto.
```

Você copia:

```text
https://www.youtube.com/@nossamesanossalendas
```

Depois fala:

```text
Pronto!
```

O agente lê o clipboard, valida que é uma URL HTTP/HTTPS, grava a ação em `data/memory.json`, agradece e abre o link.

A memória ficará aproximadamente assim:

```json
{
  "id": "learned_...",
  "description": "Abrir o jogo do Roque no YouTube",
  "triggers": [
    "abre o jogo do roque no youtube"
  ],
  "action": {
    "type": "open_url",
    "value": "https://www.youtube.com/@nossamesanossalendas"
  }
}
```

Na próxima vez, a frase é resolvida pela memória e executada sem precisar reaprender o link.

## 7. Aprendizado de nova capacidade

Se você pedir uma ação que não tem executor local, por exemplo:

```text
coloca o volume em 30 por cento
```

não há `exec`, PowerShell arbitrário ou shell produzido pela LLM.

Em vez disso o agente:

1. informa por voz que ainda não sabe executar a operação;
2. cria um arquivo Markdown em `learning_requests/`;
3. copia para o clipboard um prompt de implementação preparado para um agente de código;
4. abre a pasta do projeto e a proposta no VS Code.

Assim você pode usar `Ctrl+V` no seu agente de programação e implementar a nova ferramenta conscientemente.

## 8. Memória de fatos

O schema também suporta fatos persistentes. Por exemplo:

```text
lembre que meu servidor de RPG se chama Atlas
```

O roteador pode armazenar:

```json
{
  "key": "nome do servidor de RPG",
  "value": "Atlas"
}
```

Esses fatos entram no contexto das próximas interpretações.

## 9. Endpoints úteis

### Status

```http
GET http://127.0.0.1:8767/status
```

### Iniciar gravação

```http
POST http://127.0.0.1:8767/start
```

### Encerrar/processar

```http
POST http://127.0.0.1:8767/stop
```

### Testar sem microfone

Também existe um endpoint de desenvolvimento:

```http
POST http://127.0.0.1:8767/text
Content-Type: application/json

{
  "text": "abre o youtube"
}
```

Isso é útil para testar roteamento e memória antes de mexer com áudio.

## 10. Segurança deliberada

O modelo só pode produzir tipos de ação enumerados em `src/models.py`. A execução local é implementada explicitamente em `src/actions.py`.

Uma resposta da LLM nunca é passada diretamente para `cmd.exe`, PowerShell, `exec()` ou `shell=True`.

Ações aprendidas no JSON atualmente executam apenas tipos conhecidos, como `open_url` e `open_path`. Guardar no JSON algo parecido com código não torna esse conteúdo executável.
