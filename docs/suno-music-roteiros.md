<!-- Roteiros manuais T7/CA11 do seletor e das Configurações → Música.
     Moram em docs/ (T8); nada novo na pasta do plugin. -->

# Roteiros manuais — T7 e CA11 (seletor do app de Música)

Ambiente: PIA no computador do Diogo, branch `feature/suno-music-provider`.
Não gerar faixa paga no Suno nestes roteiros (só conectar/desconectar e abrir o app).
Estes testes são smoke manual, sem jsdom/testing-library (decisão do CEO, CA11).

Os estados da tela de Configurações dependem dos campos do catálogo da T1
(commit `8501c1d`): `endpoint_configured`, `credential_state` (`missing` /
`configured` / `expired`), `available`, `settings_route`, `server_id`,
`auth_type`, `oauth_connected`. A T1 mascara a URL removendo userinfo, query e
fragment (sem `••••`); o comando pode vir com `••••` no lugar de tokens.

---

## Roteiro 1 — Smoke do seletor no Panel de Música (CA11)

Objetivo: conferir as funções já cobertas pelos testes puros, agora na tela
do app (abrir, trocar de aba, voltar, reutilizar, cancelar).

1. **Suno indisponível (sem credencial válida)**
   - Abra o app de Música.
   - O seletor "Gerador" mostra Local, Gemini e Flow; **Suno não aparece**.
   - Há a dica discreta "Conecte o Suno em Configurações → Música".
   - Clique no atalho: deve abrir Configurações na aba Música (`Apps/music`).

2. **Suno disponível (endpoint + credencial válida)**
   - Com o Suno autorizado, volte ao app (ou recarregue o catálogo voltando o foco).
   - O seletor passa a listar **Suno**, sem reiniciar a PIA.
   - Se `MUSIC_PROVIDER` estiver salvo como `suno_mcp`, o app abre já em Suno.
   - Com o Suno selecionado, aparece a dica de duração indicativa e o aviso
     de cancelamento (créditos).

3. **Foco e visibilidade (CA04, RN05)**
   - Com o app aberto em Suno, desconecte o Suno em outra janela de Configurações
     **→ Música** (não em "Contas MCP") e volte o foco ao app.
   - Sem geração em andamento, o seletor volta para Local e some o Suno,
     com aviso de que o Suno deixou de estar disponível.
   - Observação CA04: conectar ou desconectar o Suno **somente** em
     Configurações → **Contas MCP** (o painel genérico de servidores MCP)
     **não dispara** o evento `pia:music-providers-updated`. O app de Música
     só atualiza nesse caso no recarregamento de foco/visibilidade ou depois
     de reabrir Configurações → Música. O evento é disparado nas ações feitas
     no `MusicSettingsPanel` (salvar, conectar/desconectar OAuth).

4. **Reutilizar prompt (CA08)**
   - No Histórico, reutilize uma faixa com origem Suno.
   - Se o Suno estiver disponível, o seletor fica em Suno e o prompt é carregado.
   - Se não estiver, vai para Local e aparece o aviso para conectar o Suno.

5. **Histórico e cancelamento (CA09)**
   - Faixas Suno no Histórico devem aparecer com o rótulo **"Suno"**, não `suno_mcp`.
   - Com o Suno selecionado, o aviso de cancelamento é visível antes/durante o job.
   - Não é necessário disparar uma geração paga para este smoke; basta conferir
     o texto do aviso na interface.

---

## Roteiro 2 — T7: Configurações → Música (CA02, CA03, CA04)

1. **Instalação nova (sem URL/comando)**
   - Sem endpoint configurado, o selo deve mostrar **"Não configurado"**
     (e não "URL configurada, falta autorizar").
   - Não deve aparecer o aviso de que o app abre em Local, a menos que o
     provedor salvo já seja `suno_mcp` com `available !== true`.

2. **Só URL, falta autorizar (CA02)**
   - Em Configurações → Música, informe só a URL do MCP (sem OAuth/token).
   - Salve com o provedor "Suno (MCP)" selecionado. O salvamento deve ser
     aceito (RN04: `select_provider` grava mesmo sem credencial).
   - O selo de status deve mostrar **"URL configurada, falta autorizar"**.
   - Deve aparecer o aviso de que o app abre em Local até autorizar.
   - Abra o app de Música: o seletor **não lista Suno** e mostra a dica com
     atalho para Configurações → Música.

3. **Deep link**
   - No app, clique em "Conecte o Suno em Configurações → Música"
     (ou use a rota do catálogo, `settings_route`).
   - A PIA deve abrir Configurações já na aba **Música** (`section: "Apps/music"`),
     com o `MusicSettingsPanel` (não a aba Geral).

4. **Conectar e voltar ao app sem reiniciar (CA04)**
   - Em Configurações → Música, clique em "Conectar via OAuth" e conclua a
     autorização (sem gerar faixa).
   - Depois de iniciar o OAuth (URL padrão gravada, ainda sem conta), o selo
     deve ir para **"OAuth pendente"** — não para "falta autorizar".
   - Ao concluir, o selo deve ir para "Conta OAuth conectada (Cofre)".
   - Volte ao app de Música (foco/visibilidade ou navegação), **sem reiniciar**
     a PIA.
   - O seletor passa a mostrar **Suno**. Se o padrão salvo for `suno_mcp`,
     ele vem selecionado (CA03).
   - Lembrete: o mesmo fluxo feito só em **Contas MCP** não dispara o evento
     (veja o item 3 do Roteiro 1).

5. **Desconectar**
   - O botão "Desconectar" só aparece quando `oauth_connected === true`
     (conta OAuth). Com token/bearer ("Credencial configurada") ele não deve
     aparecer.
   - Em Configurações → Música, clique em "Desconectar".
   - O catálogo da tela deve atualizar na hora (o `suno_oauth_disconnect`
     já devolve o catálogo; o painel dispara `pia:music-providers-updated`
     no `finally`, mesmo se um recarregamento posterior falhar).
   - Volte ao app: o Suno some do seletor, sem reiniciar.

6. **Expirado — reautorizar**
   - Quando o catálogo vier com `credential_state: "expired"`, o selo deve
     mostrar **"Expirado — reautorizar"** e o botão "Reconectar OAuth".
   - "Desconectar" só permanece visível se `oauth_connected` ainda for true.
   - O app deve tratar o Suno como indisponível até a reautorização
     (`available=false` + `credential_state=expired` na T1).

7. **Host api.suno.com com outro id (decisão do CEO)**
   - Se houver um servidor MCP com host `api.suno.com` e id diferente de
     `suno_mcp`, mas com credencial válida, o painel deve reconhecê-lo como
     Suno conectado. A T1 do HEAD sempre publica a entrada com `id: suno_mcp`;
     o fallback de host permanece no frontend.

8. **URL/comando mascarados e token sem endpoint**
   - URL devolvida pela T1 (sem query, sem `••••`), se não for editada, não
     deve voltar no payload de salvar (o servidor mantém o valor real).
   - Se o usuário editar um comando que ainda contém `••••`
     (ex.: `npx suno --token •••• --v2`), o salvamento é bloqueado com a
     mensagem para substituir o trecho oculto pelo valor real.
   - Token configurado sem endpoint: selo **"Credencial configurada"**;
     o Suno continua indisponível no app até haver endpoint + credencial.

