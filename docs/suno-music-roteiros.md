<!-- Roteiros manuais do Suno pela PIA Server (T9). Substituem os roteiros
     T7/CA11 do Suno local (URL/OAuth no PC), que saiu na T8. -->

# Roteiros manuais — Suno pela PIA Server

> **Atenção: gerar de verdade no Suno gasta créditos da conta.** Os roteiros
> abaixo não geram nada, exceto onde está marcado **[gasta créditos]**. Esses
> passos só podem ser feitos com o **ok explícito do Diogo**, dado para aquele
> teste. Sem o ok, pare no passo anterior ao **Gerar**.

Arquitetura e contrato: [PLATFORM_SERVICES.md](PLATFORM_SERVICES.md#suno-pela-pia-server).
Rotas com exemplos: coleção Postman (`postman/PIA.postman_collection.json`,
pasta "07 · Workspace e serviços").

Pré-requisitos:

- PIA pareada com a PIA Server (Configurações → PIA Server) e servidor com a
  capability `suno:3`.
- Nenhum token, link de áudio ou prompt pode aparecer na interface, nos
  eventos do job, nos `.json` das faixas nem em `logs/`. Confira ao final de
  cada roteiro (busque por `Bearer`, `token=`, `X-Amz-Signature`, `suno.com`).
- Para testar sem gasto, use uma pia-server de desenvolvimento com o Suno
  simulado. A suíte automática usa `tests/fixtures/fake_pia_server_suno.py`.

---

## 1. Conectar uma conta

1. Abra Configurações → Música. Sem conta, aparece "Conecte o Suno em
   Configurações → Música" e o app de Música não lista o Suno no seletor.
2. Clique em **Conectar conta Suno**. A PIA chama `POST /music/suno/connect`
   e abre o `auth_url` no navegador. O login no Suno acontece na página da
   PIA Server; nada é digitado na PIA local.
3. Enquanto a autorização não termina, a tela fica aguardando (o painel
   consulta `GET /music/suno/connect/<attempt_id>` a cada 3 s).
4. Ao concluir, a conta aparece na lista com apelido, nome ou e-mail, e o
   Suno passa a aparecer no seletor do app **sem reiniciar** a PIA.
5. Variações:
   - Feche a aba sem autorizar e espere a tentativa expirar: a resposta é
     `{state: "expired"}` (200) e a tela pede para clicar em Conectar conta
     Suno de novo.
   - Negue a autorização no Suno: `failed` com `suno_oauth_denied`.
   - Autorize uma conta Suno já ligada a outra conta PIA: `failed` com
     `suno_account_taken` e a mensagem para desconectá-la lá primeiro.

## 2. Renomear

1. Em Configurações → Música, edite o apelido de uma conta e salve. A PIA
   chama `POST /music/suno/accounts/<id>/rename {label}`.
2. O apelido novo aparece na lista e no seletor de conta do app.
3. Apelido vazio ou com mais de 80 caracteres: erro `invalid_label`, sem
   mudar nada.

## 3. Desconectar

1. Clique em **Desconectar** numa conta e confirme.
2. A PIA chama `POST /music/suno/disconnect {account_id}`; a conta some na
   hora e, se era a única, o Suno sai do seletor do app.
3. O histórico das gerações dessa conta continua visível.

## 4. Gerar com uma conta **[gasta créditos no passo 3]**

1. Com exatamente uma conta válida, abra o app de Música e escolha Suno. A
   conta já vem escolhida.
2. Confira o aviso de que a duração é indicativa e de que cancelar não
   interrompe o que já foi enviado.
3. **Só com o ok do Diogo:** peça 1 música e clique em Gerar. O progresso
   mostra "k de N músicas prontas"; as faixas chegam pela PIA Server e entram
   no Histórico com o rótulo "Suno" (extras: "Suno · extra").

Sem gasto: com o Suno indisponível (sem conta ou não pareado), tente gerar
pela API e confira a recusa antes do job (`suno_not_connected`,
`suno_credential_expired` ou `pia_server_unpaired`), sem job criado.

## 5. Gerar com duas contas **[gasta créditos no passo 4]**

1. Conecte uma segunda conta.
2. No app, o seletor de conta aparece **sem conta escolhida**
   (`selected_account_id = null`), mesmo que uma delas seja a padrão no
   servidor ou tenha sido usada antes. O `/music/select` não guarda conta.
3. Sem escolher a conta, o Gerar fica bloqueado com "Escolha a conta Suno"
   (pela API: 400 `suno_account_required`).
4. **Só com o ok do Diogo:** escolha uma conta e gere 1 música. A geração usa
   a conta escolhida (`suno_account_id` no generate).
5. Com um job em andamento, tentar outro job na mesma conta PIA responde
   `suno_job_active`.

## 6. Offline antes e durante o job

1. Antes do job: desligue a rede ou a PIA Server. O Suno aparece como
   indisponível ("Não foi possível falar com a PIA Server agora") e a geração
   é recusada com `pia_server_unreachable`.
2. Durante um job (só no roteiro 4 ou 5, com o ok): derrube a rede. O
   progresso mostra que a conexão caiu (`connection: lost`) e a geração
   continua no servidor. Ao voltar a rede, as faixas são baixadas e o
   progresso volta a `ok`.
3. Reabrir a PIA no meio de um job deste PC: ao abrir o app ou Configurações
   → Música, o job é retomado e as faixas pendentes são baixadas (retomada
   lazy, risco conhecido).

## 7. Histórico

1. Abra a aba Histórico. Os itens vêm da PIA Server mesclados com os locais,
   jobs ativos primeiro.
2. Confira os estados das faixas: tocar (arquivo neste PC), **Baixar
   novamente** (faixa Suno sem arquivo aqui), faixa local de outro PC
   (`other_device_local`) e sem ação (faixa local deste PC que sumiu).
3. Excluir um item: some da lista e não volta ao recarregar, mas **o arquivo
   continua na pasta** de música.
4. Offline ou sem pareamento: só os itens locais aparecem, com o aviso de
   servidor indisponível; excluir é recusado.
5. Gere uma música **Local** (sem custo) com a PIA pareada: o registro aparece
   no histórico do servidor sem o áudio. Repita offline: o registro fica na
   fila (até 500 itens/30 dias) e sobe quando a conexão volta. Sem pareamento,
   nada é enviado nem guardado.

## 8. Baixar novamente

1. Apague da pasta de música o arquivo de uma faixa Suno (ou abra o Histórico
   em outro PC da mesma conta).
2. A faixa mostra **Baixar novamente**. Clique: vira um job e, ao terminar, a
   faixa toca a partir da pasta deste PC. Clicar de novo durante o download
   não cria outro job.
3. Faixa cujo link não existe mais no Suno: "Esta música não está mais
   disponível no Suno." (`suno_track_unavailable`).
4. Faixa local de outro PC: `not_origin_device`. Faixa local deste PC que
   sumiu: sem botão (pela API, `local_audio_missing`).

Baixar novamente não gera nada no Suno e não gasta créditos.

## 9. Migração das credenciais antigas

1. Num perfil que ainda tem as credenciais do Suno local (settings
   `MUSIC_SUNO_MCP_*`, entradas `mcp:connector:suno_mcp:*` no cofre ou o
   servidor MCP `suno_mcp`), abra a PIA.
2. Aparece o aviso listando só os **nomes** do que foi encontrado, nunca os
   valores.
3. **Agora não**: nada é apagado e o aviso não volta no próximo início.
4. **Remover**: apaga só depois da confirmação (`{confirm: true}`); sem ela a
   API responde `confirmation_required`. Depois, o aviso some.
5. Até remover, o token antigo continua no export e no sync do perfil (risco
   conhecido aceito).
