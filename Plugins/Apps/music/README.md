# Música

App React/Mantine com Principal e Sobre. O manifesto `pia.json` identifica o app; `web_api.py` oferece jobs de instalação e geração, cancelamento da espera e biblioteca. Arquivos ficam em `Documentos/pia/music`, no perfil do usuário do sistema. Motor/modelos ficam em `cache/Apps/music` e logs em `logs/plugins/Apps/music-engine.log`.

Escolha de 1 a 10 músicas por pedido, agrupadas em um card. Percentual indica faixas concluídas; o provedor não fornece percentual confiável da inferência individual. O player é compartilhado da PIA e continua ao navegar. A conclusão publica uma notificação e rola até o card se a tela Principal estiver aberta.

O ícone **Reutilizar prompt** do card preenche descrição, letra, provedor, duração solicitada e quantidade de versões, e retorna ao formulário. Ele não inicia uma nova geração automaticamente. Arquivos antigos sem algum desses metadados usam os padrões do formulário.

A PIA solicita o encerramento do processo do motor local ao terminar cada geração; um servidor externo já iniciado não é encerrado. No Windows, processos filhos do interpretador podem sobreviver ao processo principal: a liberação completa de VRAM ainda precisa de correção e validação com hardware. A próxima geração pode demorar para recarregar os modelos.

## Local

A aba **Principal** é dedicada à criação. Os lotes prontos ficam em **Histórico**,
com reprodução, download e reutilização do prompt (que volta à Principal com os
campos preenchidos). Ao concluir um lote com a Principal aberta, o app muda para
Histórico e mostra o resultado. A geração continua ao navegar para outros apps.

Instale Git e uv. Na Principal, use **Instalar motor local (vários GB)**. A PIA prepara ACE-Step 1.5 em Python 3.12 separado do Whisper/TTS, em revisão fixada no serviço. O primeiro início baixa pesos. GPU, memória e duração afetam o desempenho; não há promessa de equivalência de qualidade ao Suno. Também é possível configurar um servidor ACE-Step já instalado em HTTP loopback, com chave opcional. Não exponha esse motor diretamente à rede.

## Google

Gemini/Lyria utiliza a chave Gemini existente da PIA e o modelo configurável `MUSIC_GEMINI_MODEL`. Depende da disponibilidade e cotas da API. Login OAuth Gmail/Drive e assinatura Gemini não substituem a chave da API. Flow Music permite copiar o pedido e abrir o site oficial usando a conta do navegador; não há automação de geração via cookies.

Cancelar encerra a espera e evita salvar o resultado, mas não garante cancelamento do processamento já iniciado no provedor. A duração informada é solicitada, não duração medida.


## Suno

O gerador **Suno** entra no seletor só quando o catálogo marca `available=true`:
há um endpoint (URL do MCP ou comando stdio) **e** uma credencial válida
(OAuth no Cofre ou bearer). Um servidor MCP com host `api.suno.com` e
qualquer id conta como Suno, se a credencial estiver válida.

A configuração fica em **Configurações → Música** (atalho
`section: "Apps/music"`). Informe a URL (o padrão oficial é
`https://api.suno.com/mcp`) ou um comando, e autorize com OAuth (DCR +
PKCE) ou um token bearer no Cofre. O selo da conta reflete o catálogo:

- **Não configurado** — sem endpoint;
- **URL configurada, falta autorizar** — endpoint sem credencial;
- **OAuth pendente** — fluxo de autorização em andamento no painel;
- **Credencial configurada** — bearer (ou equivalente) válido;
- **Conta OAuth conectada (Cofre)** — OAuth concluído;
- **Expirado — reautorizar** — última chamada respondeu 401/403.

É possível salvar o provedor `suno_mcp` sem credencial (RN04); o app de
Música, nesse caso, abre em **Local** e mostra a dica para conectar. O
botão Desconectar só aparece com OAuth conectado.

A duração pedida no Suno é **indicativa**; a faixa pode sair com outro
tamanho. **Cancelar espera** interrompe só a espera na PIA: a geração já
enviada ao Suno pode continuar e **consumir créditos**. O backend pede o lote com `ceil(N/2)` chamadas (2 clips por chamada) e
descarta o excedente. Uma falha em um clip interrompe o lote ali (sem
nova chamada): as faixas prontas entram no Histórico e a notificação
"Músicas prontas" deixa o parcial explícito (ex.: "1 de 3 músicas
prontas (geração interrompida)"). Os metadados usam `provider=suno_mcp`
e o rótulo curto **"Suno"**.

Se o Suno não estiver conectado, ou a credencial tiver expirado, a
geração é recusada **antes** de criar o job (`suno_not_connected` ou
`suno_credential_expired`); o HTTP 400 devolve `{error, code}`. Durante
o job, os códigos estáveis incluem `incomplete_batch`, `download_failed`,
`suno_no_credits`, `suno_auth`, `suno_unavailable` e `suno_timeout`. A
mensagem de `incomplete_batch` é "O Suno devolveu menos músicas que o
esperado." — o "k de N" vive na notificação, em `completed`/`total` e
no `ready_text` (evento de erro e progresso). O progresso final de uma
falha parcial usa `label="Geração interrompida"` e `state="interrupted"`.
O download do áudio é local e seguro (sem gravar a URL remota).

Não há fallback automático para outro gerador. Erros amigáveis: autorização
expirada (reconectar em Configurações → Música), Suno indisponível, ou
tempo esgotado (a geração pode ter sido concluída no Suno). Tokens, `Bearer`
e URLs assinadas (`X-Amz-Signature`, `token=`) não devem aparecer na
interface, nos eventos do job nem no `.json` da faixa.

Testes usam o mock HTTP local `tests/fixtures/fake_suno_mcp.py` (sem
chamada paga). O e2e em `tests/test_music_suno_e2e.py` cobre sucesso,
401, 503, timeout, falha parcial (parada no primeiro clip), lote
incompleto, recusa antes do job, `download_failed`, `suno_no_credits` e
a varredura de vazamento. O roteiro manual do seletor e das
Configurações está em
[suno-music-roteiros.md](../../../docs/suno-music-roteiros.md)
(CA11 sem jsdom; não gerar faixa paga sem autorização).

## Criar apps

Inclua `pia.json`, `plugin.toml`, `lang/pt-BR.json`, página Principal e Sobre. Use `appApi`/`watchJob` e componentes compartilhados em `src/pia/frontend`, retornando jobs para operações longas. Configurações e segredos pertencem à tela de configurações; não devem ser embutidos no JavaScript. Ferramentas de agente são registradas em `src/tool_registry.py` com schema e despacho explícito.

Configuração e dados usam o [perfil SQLite/cofre](../../../docs/PROFILE_MIGRATION.md).
