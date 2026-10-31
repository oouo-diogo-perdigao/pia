# Serviços compartilhados: notificações, mídia e logs

## Bandeja e configurações

Fechar a janela oculta o workspace. **Encerrar PIA** sai do event loop e executa cleanup numa única ação, mesmo com janela aberta. **Reiniciar PIA** inicia o launcher aguardando a instância anterior encerrar; usa o mesmo caminho de reinício das configurações.

Conectores ficam em Configurações → Conectores, em uma árvore de pastas expansível. Links/histórico antigos com view=connectors são normalizados para essa navegação. Variáveis gerais são agrupadas por Geral, STT, TTS, Imagens/ICE, LLMs e Voz/áudio, mantendo o nome real e o valor na mesma linha. Trocar a aba de variáveis não descarta alterações do formulário.

## Notificações

`src/notifications.py` mantém histórico no WorkspaceStore (até 1000 entradas), leitura, contadores e preferências globais. Apps e bots usam origens `Apps/<id>` ou `Bot/<id>`. O botão direito no ícone de cada app ou no item/card de cada bot abre o menu de silenciamento. O botão direito no sino ativa/desativa a leitura automática. Essas preferências não ficam mais na tela da central. Silenciar bloqueia toast/voz, mas preserva histórico e indicadores de não lidas. Cada bot tem contador próprio; o ícone geral de Bots mostra a soma. Abrir o app/bot em uma página visível e em foco marca os avisos daquela origem como vistos.

Em Python, um app carregado recebe o contexto do workspace:

```python
context.publish_notification('Apps/music', 'Músicas prontas', 'O lote terminou.')
```

Em uma página de app que usa o SDK:

```javascript
import {session, publishNotification} from '/pia/sdk.js';
await session();
await publishNotification('meu_app', 'Concluído', 'O processamento terminou.', [
  {label: 'Abrir resultado', url: 'https://exemplo.com/resultado'}
]);
```

O app deve estar registrado. A rota local autenticada é `POST /api/pia/notifications/publish`, com source/title/text/links. Links aceitam HTTPS; não coloque segredos ou URLs assinadas sensíveis no histórico. Não notifique a cada polling: publique apenas mudanças ou conclusões úteis.

A secretária publica avisos pelo serviço central com links de e-mail, compromisso e Meet quando disponíveis. A antiga preferência speak é migrada uma vez para leitura global, sem sobrescrever preferências já salvas. Preferências de voz não ficam mais na tela da secretária.

Conversas também têm contadores de respostas não visualizadas, tanto na lista quanto no ícone geral. A marca de leitura é persistida por chat e só avança para mensagens de assistente que aparecem na área visível de uma conversa aberta e em foco. Abas ocultas, respostas em outros chats e ramificações inativas não são marcadas automaticamente como lidas. A primeira migração considera o histórico antigo já lido.

## Reprodução compartilhada

`/pia/media.js` fornece um player por janela, mantido durante navegação entre apps. O workspace apresenta controles globais, posição e duração. Chat e app Música usam o mesmo recurso, sem players independentes.

```javascript
import {playMedia, pauseMedia} from '/pia/sdk.js';
await playMedia('/api/pia/music/files/ARQUIVO.mp3', 'Minha música');
await pauseMedia();
```

O recurso precisa ser uma URL autenticada da PIA na mesma origem. A reprodução depende de uma ação do usuário conforme as regras do navegador. O SDK também permite importar `subscribeMedia`, `seekMedia` e `stopMedia` diretamente de `/pia/media.js`. Ao criar uma UI própria, libere subscriptions no unmount.

O frontend informa o estado ao núcleo com identificador de janela e heartbeat. Enquanto houver reprodução ativa, a Mini mostra três notas animadas. Pausa, término e erro encerram a animação; leases e watchdog evitam estado preso após fechar/crashar a página. A rota de áudio oferece byte ranges para buscar posições sem recarregar o arquivo inteiro.

## Logs

Inspeção e logs organiza Main, Apps, Bot, Connectors, Skills e Browser, com painéis recolhíveis e busca no conteúdo carregado; pastas e arquivos começam expandidos. Ao abrir a tela, cada arquivo carrega somente as últimas 100 linhas. Arquivos expandidos recebem incrementos por cursor; essas novas linhas não são limitadas a 100 durante a sessão do visualizador. Busca não varre conteúdo histórico que ainda não foi carregado.

Abrir log usa o programa padrão na sessão nativa ou uma página de texto autenticada no navegador, permitindo consultar o arquivo completo. Limpar um arquivo altera apenas seu painel. O leitor detecta rotação/truncamento e não permite caminhos fora de logs/. Cada resposta incremental é limitada em bytes; o cursor permite continuar sem descartar linhas.

## Capturas

O fluxo anterior foi restaurado: cada captura abre uma janela nova com seu identificador, carregando PNG/base64 pelo adaptador nativo. Foram removidos pré-carregamento, reutilização do editor, metadados paralelos e a rota binária experimental. O app continua solicitando /action/screen-all e a Mini permanece visível; não há espera para ocultá-la. O tempo real depende da captura do sistema e dos monitores.

## Música

O app cria de 1 a 10 faixas por pedido, agrupadas em um card. Progresso percentual corresponde às faixas concluídas, não a uma estimativa inventada da inferência individual. Resultados parciais sobrevivem a falhas/cancelamento. Ao concluir na tela Principal, o app rola até o card.

Destino padrão: pasta Música do sistema, subpasta PIA. `MUSIC_OUTPUT_DIR__PATH` permite selecionar outro diretório em Configurações → variáveis do app. A biblioteca também consulta o destino legado `data/music`. Alterar o destino não move arquivos existentes; arquivos de outros destinos personalizados precisam ser acessados no diretório original.

A PIA solicita o encerramento do processo ACE-Step iniciado por ela após cada geração, inclusive em erro/cancelamento. No Windows, o interpretador pode criar processos filhos que sobrevivem ao processo principal; o encerramento de toda a árvore e a liberação completa de VRAM ainda precisam de correção e validação com hardware. A próxima geração pode recarregar o motor. A PIA não encerra um servidor ACE-Step externo que já estava rodando; para ele, liberação de recursos depende de sua configuração. Não foi executado download de modelos ou geração paga para validar essas mudanças.

## Agentes externos

O ícone de ajuda do painel abre um popup específico para Codex ou AGY, com seleção Windows/PowerShell ou Linux/Bash. Ele contém documentação oficial, comando de instalação, login, verificação de versão e comandos para obter o caminho que deve ser preenchido em AGENTS_CODEX_EXECUTABLE ou AGENTS_AGY_EXECUTABLE. Os comandos são exemplos para copiar, não são executados pela interface. MCP e AG-UI permanecem; ACP legado e o perfil A2A síncrono foram removidos.
