# Usar a PIA como servidor MCP no Codex

PIA → Codex CLI (conector de agentes externos) e Codex → PIA (MCP) são integrações distintas. Este guia configura **Codex consumindo ferramentas da PIA**. Não é necessário configurar AGENTS_CODEX_EXECUTABLE para isso.

## Dados da conexão

| Campo | Valor |
|---|---|
| Nome sugerido | `pia` |
| Transporte | Streamable HTTP, stateless |
| URL padrão | `http://127.0.0.1:8762/protocols/mcp` |
| Porta | `PORT__INT` em `config/.env`; padrão 8762 |
| Autenticação | Bearer fixo quando a chave da PIA está preenchida; sem autenticação quando está vazia |
| Chave da PIA | `OPENAI_COMPAT_API_KEY__SECRET` em `config/.env` (nome legado sem sufixo também é lido) |
| Header, se houver chave | `Authorization: Bearer <chave-da-PIA>` |
| OAuth/client ID/client secret/callback | Não utilizados por este servidor MCP |
| Processo servidor | PIA já em execução; cadastrar a URL no Codex não inicia a PIA |

O valor `local` usado nos exemplos é uma chave de exemplo, não uma senha obrigatória. Use o valor efetivamente configurado na PIA. Não use a chave da OpenAI, a senha da conta Google nem o cookie da interface web como token MCP.

## 1. Inicie a PIA

Na instalação existente, execute `bash start.sh` no Linux ou Git Bash do Windows. Mantenha a PIA rodando na bandeja. Confirme a porta e a chave em Configurações → Geral; salvar variáveis solicita o reinício pelo fluxo do aplicativo.

PIA e Codex precisam alcançar o mesmo endereço. Os exemplos pressupõem ambos no mesmo sistema. WSL, execução remota e tarefas cloud têm seus próprios ambientes de rede; `127.0.0.1` neles pode não apontar para a PIA do Windows. Não altere o endereço para uma máquina externa sem configurar acesso e autenticação apropriados.

## 2. Cadastre no Codex

### Quando a chave da PIA está vazia

No PowerShell ou Bash:

```sh
codex mcp add pia --url http://127.0.0.1:8762/protocols/mcp
codex mcp list
codex mcp get pia
```

Abra uma nova sessão `codex`. Na interface de terminal, `/mcp` mostra servidores e ferramentas ativas. `mcp list`/`get` conferem a configuração salva; não provam sozinhos que a PIA está acessível.

### Quando a PIA exige Bearer

PowerShell, exemplo usando uma PIA configurada com chave `local`:

```powershell
$env:PIA_MCP_TOKEN = 'local'
codex mcp add pia --url http://127.0.0.1:8762/protocols/mcp --bearer-token-env-var PIA_MCP_TOKEN
codex
```

Linux/Bash:

```sh
export PIA_MCP_TOKEN='local'
codex mcp add pia --url http://127.0.0.1:8762/protocols/mcp --bearer-token-env-var PIA_MCP_TOKEN
codex
```

O parâmetro recebe **o nome da variável**, não o token. Codex deve ser iniciado num ambiente que contenha essa variável. A PIA não exporta sua chave automaticamente para outros programas.

Não execute os dois exemplos de cadastro por hábito: escolha a variante correspondente à autenticação configurada. Se já houver um servidor `pia`, confira/edite sua entrada em vez de acrescentar blocos TOML duplicados.

## 3. Alternativa por config.toml e aplicativo desktop

O arquivo de usuário costuma ser `%USERPROFILE%\.codex\config.toml` no Windows ou `~/.codex/config.toml` no Linux, salvo configuração de CODEX_HOME diferente. Acrescente ou edite somente a seção deste servidor, preservando as outras configurações.

Sem autenticação:

```toml
[mcp_servers.pia]
url = "http://127.0.0.1:8762/protocols/mcp"
startup_timeout_sec = 20
tool_timeout_sec = 3600
```

Com token em variável de ambiente, acrescente à mesma seção:

```toml
bearer_token_env_var = "PIA_MCP_TOKEN"
```

O timeout de ferramenta de 3600 segundos é um exemplo para geração musical/imagem demorada; pode ser reduzido para consultas rápidas. Ele não altera os timeouts internos de cada provedor.

Para o aplicativo desktop, uma variável definida com `$env:` só vale para aquele PowerShell e processos iniciados a partir dele. Se Codex já estava aberto ou foi iniciado por outro launcher, pode não recebê-la. Configure a variável no ambiente do usuário e reabra o aplicativo, ou use um header estático na configuração privada do Codex:

```toml
[mcp_servers.pia]
url = "http://127.0.0.1:8762/protocols/mcp"
http_headers = { Authorization = "Bearer local" }
startup_timeout_sec = 20
tool_timeout_sec = 3600
```

Esse último bloco é uma alternativa ao bloco com bearer_token_env_var, não um segundo bloco para colar junto. Substitua `local` pela chave configurada; tokens privados não devem ser versionados ou compartilhados em capturas/logs. Reabra o cliente/sessão após modificar a configuração. O cliente que executa o MCP precisa conseguir acessar a PIA local.

## Login: três coisas distintas

1. **Login do Codex:** sua autenticação normal no Codex para usar o modelo. Não autentica automaticamente na PIA.
2. **Acesso MCP à PIA:** sem login quando a chave está vazia, ou header Bearer fixo quando preenchida. A PIA não implementa OAuth para MCP; **não use `codex mcp login pia`**, client ID, client secret ou callback para esta conexão.
3. **Contas dos conectores:** Gmail, Agenda, Drive e outros serviços são conectados dentro da PIA. Depois disso, as ferramentas MCP usam essas integrações; selecione a conta explicitamente. Conectar o MCP não concede permissões Google/Microsoft novas.

## Verificar sem executar ações

PowerShell, exemplo de listagem de ferramentas (chave `local` apenas se a PIA estiver assim configurada):

```powershell
$body = @{ jsonrpc = '2.0'; id = 1; method = 'tools/list'; params = @{} } | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8762/protocols/mcp' -ContentType 'application/json' -Headers @{ Authorization = 'Bearer local' } -Body $body
```

Quando a chave está vazia, omita `-Headers`. Para testar uma chave privada sem repeti-la no comando, use `-Headers @{ Authorization = 'Bearer ' + $env:PIA_MCP_TOKEN }`.

O resultado JSON-RPC deve conter `result.tools`. As ferramentas atuais são:

- `pia_accounts`: listar contas disponíveis, sem credenciais.
- `pia_resources`: consultar e-mail, agenda e arquivos da conta escolhida.
- `pia_camera`: fotografar pela câmera.
- `pia_image`: gerar imagens.
- `pia_music`: gerar música.
- `pia_delegate`: consultar Codex CLI ou AGY.

Exemplo inicial de pedido no Codex: **“Use o MCP pia para listar minhas contas disponíveis.”** Isso consulta o conector; não envia e-mails, captura imagens ou gera música. Evite delegar do Codex para ele mesmo via pia_delegate, pois é outra chamada e não compartilha esta conversa automaticamente.

## Diagnóstico

| Sintoma | Conferir |
|---|---|
| Connection refused/timeout de inicialização | PIA iniciada, porta correta, cliente no mesmo ambiente de rede |
| HTTP 401 | Chave diferente, variável ausente no processo do Codex ou mudança ainda sem reiniciar a PIA |
| Falha de login OAuth | Não há OAuth MCP nesta implementação; configure Bearer ou nenhum token conforme a PIA |
| HTTP 403 com Origin | A rota rejeita Origin de outra origem; não configure um header Origin arbitrário |
| HTTP 404 | Use `/protocols/mcp`, não `/mcp`, `/v1` ou a URL da página de chat |
| Configurado, mas sem ferramentas na sessão | Reabra o cliente/sessão e confira `/mcp`; list/get só mostram cadastro |
| Ferramenta musical expira | Ajuste tool_timeout_sec; confirme também o estado do motor e logs da PIA |
| Contas não aparecem | Configure-as nos conectores da PIA; o login do Codex não as substitui |

O servidor oferece initialize, ping, tools/list e tools/call, além de aceitar notificações MCP; transporte stateless com resposta JSON. Não oferece OAuth MCP, SSE de retomada, resources/list nem prompts/list. A lista de ferramentas não depende de ter câmera ou motor musical instalados; a execução dessas ferramentas pode exigir preparação adicional.

## Referências e validação

- [MCP no Codex — documentação oficial OpenAI](https://developers.openai.com/codex/mcp/)
- [Implementação e outros endpoints da PIA](../INTEROPERABILITY.md)
- [Conector de agentes externos, sentido PIA → CLI](../Plugins/Connectors/agents/README.md)

O comando de cadastro e suas flags foram conferidos no `codex mcp add --help` instalado. A rota local foi consultada com tools/list e retornou HTTP 200 e seis ferramentas; nenhuma ferramenta com efeito foi executada. Este guia não altera automaticamente a configuração do Codex e não equivale a testar a conexão final dentro de uma sessão dele.
