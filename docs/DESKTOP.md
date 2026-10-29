# PIA Desktop

## Instalar e executar

Na raiz, `bash install.sh`. Windows usa Git Bash e Python **nativo Windows**;
WSL é tratado como instalação Linux. Linux suporta apt, dnf e pacman. O mesmo
arquivo instala uv (quando ausente), Python 3.12, dependências de áudio/Qt,
SoX/FFmpeg, dependências Python e inicialização no login. Não há mais instalador
PowerShell separado. O ambiente ativo é a `.venv` da raiz. Ao concluir, o instalador abre a PIA em
segundo plano. Para reabrir após encerrar, use `bash start.sh` em ambos os sistemas.
A abertura não instala pacotes e pode ser chamada de qualquer diretório; o terminal
pode ser fechado. `start.sh --foreground` mantém a execução no terminal para
diagnóstico; `start.sh --dry-run` apenas mostra o comando.

```bash
bash install.sh --dry-run --no-system --no-autostart
bash install.sh
bash start.sh
```

`--no-start` prepara tudo sem abrir a PIA. `--dry-run` também não inicia nada.
`--no-system` exige dependências nativas já instaladas. `--no-autostart` não altera
login. `--no-podcast` omite os extras de processamento. Não é preciso CUDA para
iniciar; os modelos locais dependem das escolhas de dispositivo existentes.

Linux precisa de uma sessão gráfica e suporte à bandeja. No GNOME, habilite uma
extensão AppIndicator/tray se seu desktop não exibir ícones Qt. Para Windows e
X11, a companheira usa `WindowTransparentForInput`; em Wayland com XWayland,
o launcher seleciona `xcb` para permitir posicionamento e passagem de cliques.
Wayland puro pode restringir esses recursos por política do compositor. A janela
expandida continua disponível pela bandeja. O login usa o mesmo `start.sh`: uma
entrada `.desktop` no Linux e um atalho para o Git Bash no Windows. Os menus são definidos uma única vez,
sem variantes por sistema operacional.

## Configuração e dados locais

```text
config/
  .env                      # geral, privada
  keywords.txt              # wake words
  models.yaml               # catálogo pessoal
  shortcuts.yaml            # atalhos
  *.example.*               # exemplos distribuídos
Plugins/
  Skills/<skill>/plugin.toml
  Browser/<userscript>/
  Plugins/google/config.json
  Plugins/microsoft/config.json
  Bots/secretaria/config.json
  Apps/podcast_automation/   # fonte, testes, documentação, licença, .env e config próprios
 data/workspace.sqlite3      # chats, rascunhos e deduplicação local (ignorado no Git)
```

A primeira execução/instalação migra `.env`, keywords, models e shortcuts da raiz
para `config/`. Não sobrescreve: conflitos vão para `config/legacy/`. Esse backup
pode conter credenciais; ele também é ignorado no Git. Variáveis de processo
mantêm precedência sobre `config/.env`. Configurações salvas na tela geral exigem
reiniciar a PIA; a tela de plugins mantém os arquivos dentro do próprio plugin.
O código Python fica em `src/`; imagens em `src/images/`, sons em `src/sounds/` e
HTML em `src/ui/`. `qt.conf` fica em `config/`. O compose dos serviços opcionais
fica em `deploy/` e as receitas de empacotamento em `packaging/`. A raiz conserva
apenas os dois scripts, metadados do projeto e pastas de código/dados.

## Companheira, conversas e bandeja

A companheira fica sempre visível até escolher **Ocultar** no menu que aparece ao
passar o mouse. Os cliques nela atingem a janela atrás. Os botões ficam em outra
janela, que recebe cliques normalmente. **Mostrar PIA na tela** na bandeja reabre
somente essa interface. Fechar a janela expandida também apenas a oculta.
**Encerrar PIA** na bandeja encerra os serviços e processos pertencentes à PIA.

O compositor compacto abre pelo botão Mensagem. A seta à esquerda ou Enter envia;
Shift+Enter adiciona uma linha. Clique fora fecha a janela e preserva o rascunho,
inclusive após reiniciar. O microfone inicia/para uma sessão de fala com animação
pulse. As transcrições seguem skills/comandos e o mesmo roteamento de modelos da
PIA; as frases recebidas enquanto uma resposta é gerada ficam na fila.

A janela expandida usa tema escuro com destaques roxos e azuis. A barra de
atividades à esquerda abre listas contextuais de conversas, bots e configurações;
cada aplicativo instalado em `Plugins/Apps/*/plugin.toml` ganha seu próprio botão.
Uma segunda coluna lista os itens da seção selecionada. O conteúdo abre à direita
em abas persistentes, no estilo de um editor: alternar entre conversa e aplicativo
preserva o rascunho e o estado de cada painel. O histórico possui busca por título.
Integrações e inspeção ficam na lista de Configurações. A configuração geral fornece
links para obter chaves dos provedores. Textos de chat são renderizados como texto,
sem executar HTML retornado por modelos. O conteúdo é armazenado neste computador;
conversas enviadas a modelos remotos continuam sujeitas ao provider escolhido.

## Google: Gmail, Agenda e Drive

1. Na tela Plugins → Google, abra **Obter Client ID e configurar OAuth**:
   https://console.cloud.google.com/apis/credentials
2. Crie um projeto e habilite Gmail API, Google Calendar API e Google Drive API.
3. Configure o consentimento OAuth e crie um cliente do tipo **Aplicativo para
   computador / Desktop app**. Se estiver em teste, adicione seus usuários de teste.
4. Informe Client ID e Client Secret na PIA. O segredo vai para o cofre do sistema.
5. Dê um nome como Pessoal ou Trabalho e clique Conectar conta. Autorize no navegador.
6. Repita para outra conta. Reautorizar a mesma identidade atualiza sua conexão.

O fluxo usa PKCE, state aleatório, callback temporário em 127.0.0.1 e refresh
silencioso. Não há servidor OAuth hospedado pela PIA. A conta é identificada pelo
perfil retornado pelo Google; o nome local não altera a identidade autorizada.
Os escopos solicitados são identidade, Gmail readonly, Calendar readonly e Drive
readonly. Escopos Gmail/Drive podem exigir aprovação do projeto ou do administrador
da organização. Desconectar remove os tokens locais; para revogar o consentimento
no provedor, use https://myaccount.google.com/connections.

Referência: https://developers.google.com/identity/protocols/oauth2/native-app

## Microsoft: Outlook, Agenda e OneDrive

Em Plugins → Microsoft, abra https://entra.microsoft.com/ e registre um aplicativo
que aceite os tipos de contas desejados (incluindo pessoais se necessário).
Configure a plataforma **Mobile and desktop applications**, callback
`http://localhost/callback`, e as permissões delegadas `User.Read`, `Mail.Read`,
`Calendars.Read` e `Files.Read`, além de identidade/offline access. Informe o Client
ID e conecte cada conta no navegador. Não usa client secret para cliente público.
Políticas do tenant podem exigir consentimento administrativo.

Referência: https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow

Tokens ficam no Windows Credential Manager ou no Secret Service da sessão Linux,
via `keyring`. No Linux desbloqueie/inicie o cofre na sua sessão; a PIA não usa
fallback para arquivo de tokens em texto simples. Os JSONs dos plugins contêm
apenas Client ID e metadados de contas. Erros OAuth não incluem corpos de resposta
ou tokens nos logs. A PIA nunca usa as contas conectadas ao próprio Codex.

## Secretária local

Conecte as contas Google, vá a Bots/Secretária, marque as contas desejadas e salve.
Ela inicia **desabilitada**; nenhuma automação é ativada por conectar uma conta.

Opções: ativação, lembretes (antecedência em minutos), abertura de Google Meet 2
minutos antes, novos e-mails importantes, leitura por voz, intervalo de consulta,
ID da agenda e filtro Gmail (`is:unread is:important` por padrão).

O scheduler roda em uma thread local e consulta as APIs diretamente. Não usa
ChatGPT, serviço de agendamento remoto ou LLM para classificar e-mails. Importância
vem do filtro Gmail configurado. Na primeira consulta de e-mail começa a observar
a partir daquele momento, sem anunciar todo o estoque de mensagens antigas.
Eventos cancelados, recusados, de dia inteiro e já iniciados não abrem reuniões.
A abertura automática permite apenas URLs HTTPS de meet.google.com; outros links
continuam recebendo lembretes, mas não são abertos automaticamente.

A consulta de agenda cobre as próximas 24 horas, com paginação, e considera
fuso/offset do evento. A deduplicação usa conta + evento + horário de início,
ou conta + ID da mensagem, e persiste após reiniciar. O horário pode variar até
um intervalo de consulta; a configuração padrão consulta a cada 30 segundos.
O computador deve estar acordado, com a PIA e conexão com as APIs ativas. A PIA
não acorda o computador nem abre reuniões que já começaram. O botão Consultar
agora mostra também erros e o horário da última consulta de cada conta.

## Podcast Automation incorporado

O código está em `Plugins/Apps/podcast_automation`; origem e commit estão em
`UPSTREAM.md`, com licença preservada. A PIA instala os extras com `uv sync --extra
podcast`. Não são necessários clone, Git ou ambiente separado para o podcast.
O ambiente integrado é gerenciado pela raiz. Foram removidos Dockerfiles,
composes, instaladores, metadados de ambiente independente e a antiga GUI avulsa.
Há apenas `Plugins/Apps/podcast_automation`: seus comandos ficam em `voice/` e
são registrados pela seção `[voice]` do manifesto do app.

Na tela Plugins → Aplicativos / Skills / Browser, use **Configurar plugin
selecionado** para editar `.env` e `config/config.json` do podcast. Os exemplos
ficam em `docs/examples` do próprio plugin. Preencha campanhas e credenciais antes
de processar/publicar. Links de credenciais Google, R2 e S3 estão nessa tela.
O botão próprio do podcast na barra esquerda abre o painel à direita: processar
sessões, unir SRT/VTT, reconstruir feeds, acompanhar saída e parar tarefas. O
processamento e a publicação usam subprocessos do Python da PIA com o ambiente
próprio do plugin; a interface não abre outra janela de utilitários. Publicações
pedem confirmação e não são iniciadas ao selecionar o aplicativo. O monitoramento
contínuo é opcional; sem ele, processa uma única consulta. Configurações abrem na
segunda aba do próprio aplicativo. Fechar a PIA encerra seu processo. A CLI e os
utilitários originais continuam disponíveis.

Para voz: **comando podcast**, depois **iniciar**, **status**, **parar processamento**,
**abrir RSS**, **abrir transcrições** ou **finalizar**. A interação não publica nada
até receber iniciar. O app usa o Python e as dependências da PIA, sem outro clone.


## Testes

```bash
.venv/Scripts/python.exe -m pytest tests -q
# Bash/Linux: use .venv/bin/python
PYTHONPATH=Plugins/Apps/podcast_automation/src .venv/bin/python -m pytest Plugins/Apps/podcast_automation/tests -q
.venv/bin/python tests/desktop_smoke.py
bash -n install.sh
bash install.sh --dry-run --no-system --no-autostart
```

Os testes de OAuth/providers e agenda usam mocks, sem e-mails reais nem login.
O smoke Qt usa widgets nativos e QtWebEngine reais em modo offscreen, com o backend
de chat simulado e sem chamadas a provedores. Ele valida rascunhos, Enter,
visibilidade, busca e seleção de conversas, rascunhos por chat, navegação da barra
de atividades, editor de aplicativos, flags de passagem de cliques, menus e ativação da animação pulse no
DOM. A passagem real de cliques entre aplicativos ainda precisa de verificação
em uma sessão gráfica Windows/Linux.


## Conversas e ramificações

O microfone do chat dita no campo de mensagem; o envio continua sendo feito por Enter ou pelo botão de envio. O microfone da Mini PIA mantém a conversa por voz.

Cada mensagem oferece copiar, editar, excluir, fork, tocar e tentar novamente. Editar e tentar novamente preservam os caminhos anteriores: use as setas e o contador sob a mensagem para escolher uma alternativa. Só a ramificação selecionada é enviada ao modelo. Fork cria outra conversa independente, copiando o histórico até a mensagem escolhida. Excluir remove a mensagem e seus descendentes nessa ramificação.

O menu de conversa (também acessível pelo botão direito no título) permite fixar, arquivar, renomear, mover e excluir. Arquivadas ficam na lista própria. Use “Selecionar conversas” para excluir várias com confirmação. Arraste para uma pasta destacada ou para “Conversas · sem pasta” para retirar da pasta.

## Capturas

O app screenshots solicita `GET /action/screen-all`; essa rota retorna o PNG de todos os monitores e toca `src/sounds/print.mp3`. A interface principal permanece visível na captura, enquanto a Mini PIA é temporariamente ocultada. Print Screen inicia uma seleção nova; Alt+Print Screen captura a janela ativa.

Os controles ficam sobre a imagem. Ctrl+roda amplia no cursor, sem mudar a função dos botões: esquerdo recorta, direito anota, e pressionar o outro botão cancela o gesto em andamento. O botão do meio copia a cor HTML do pixel, mostrada no canto inferior direito. Cada captura começa com posição e zoom redefinidos.

Ao terminar o recorte, o resultado é salvo e copiado automaticamente, sem confirmação intermediária. A pasta padrão é “PIA Captures” na pasta Imagens do sistema. Escolha a pasta, formato, borda e ações automáticas no painel do app. A galeria lista os arquivos da pasta de destino, inclusive os salvos em sessões anteriores. Nenhuma integração com e-mail é usada.

A secretária oferece “Abrir Meet automaticamente” e uma antecedência configurável em minutos (padrão: 2).


## Ações e arquivos compartilhados

As ações do chat são ícones com tooltip. Copiar usa a área de transferência nativa na janela Qt; copiar e tocar exibem um visto verde por dois segundos. Excluir uma mensagem arma o ícone vermelho por cinco segundos: o segundo clique confirma. O menu horizontal de conversa abre pelos três pontos ou pelo botão direito; excluir entra na seleção em massa, com a conversa já marcada. Cancelar sai da seleção; a lixeira vermelha exclui sem outra confirmação. Arquivadas ficam no rodapé e nova conversa fica no botão + do cabeçalho.

Erros aparecem em vermelho por 20 segundos, pausando a contagem enquanto o mouse está sobre eles. Clique no alerta para copiar o erro completo.

A galeria de capturas usa cartões quadrados e páginas de 24 arquivos, carregadas ao rolar. Abre/atualiza ao entrar no painel ou após nova captura enquanto o painel está visível, sem recriar a lista por polling. Os ícones permitem selecionar, excluir e abrir pelo sistema.

O app Object Storage fornece gerenciamento de arquivos para as contas do plugin homônimo. Google e Discord também são integrações compartilhadas, disponíveis ao podcast e às skills. Consulte os READMEs desses plugins para API, permissões e credenciais. As integrações externas precisam de configuração válida; os testes automatizados usam respostas simuladas.


## Edição, Markdown e ferramentas do chat

Renomear uma conversa substitui o título por um campo na lista. Enter salva, Esc ou sair do campo cancela. Editar uma mensagem abre um editor dentro do histórico; Ctrl+Enter salva, Esc cancela. A edição continua criando uma ramificação, preservando a anterior.

As respostas do chat da interface incluem instrução de Markdown e são renderizadas com títulos, negrito, itálico, listas, tabelas, citações e código. O renderizador cria elementos DOM sem executar HTML recebido. Links de imagem gerados apontam para anexos locais autenticados; URLs javascript e HTML executável não são renderizados.

Pedidos explícitos como “Gere a imagem de uma garota de anime” executam a ferramenta local ChatTools.generate_image, que envia POST /v1/images/generations com prompt, n=1, response_format=b64_json. A identidade interna temporária tem permissão apenas para essa rota e é revogada ao terminar. O provedor de imagens configurado na PIA continua responsável pela geração. Falhas do provedor são exibidas como erro, sem afirmar que a imagem foi criada.

A resposta é validada como PNG/JPEG/WebP e guardada em data/chat-images. O texto da mensagem contém um link Markdown de imagem para /api/pia/chat/assets/<id>.<ext>. GET nessa rota usa a mesma sessão local do chat e retorna o arquivo com seu MIME. Os anexos persistem no histórico e nos forks, sem depender do TTL do cache de /v1/images/files. A API externa mantém seu contrato e os clientes continuam escolhendo instruções e formatos próprios.

POST /api/pia/logs/clear com {name:"arquivo.log"} esvazia um log; com {all:true}, esvazia todos os .log da pasta logs. Não remove os arquivos abertos pelos handlers; logs novos continuam sendo gravados. A ação exige sessão e origem local como as demais alterações da interface.

Plugins sem variáveis de ambiente são omitidos da lista de configurações. Cada app tem Home e uma engrenagem no título para sua configuração funcional.

## Bot e captura

A secretária fornece seu próprio painel em Plugins/Bot/secretaria/web/panel.js e avatar em avatar.svg. O SVG tem grupos de corpo, olhos e estrelas animados, com cores --bot-primary, --bot-accent e --bot-eyes. As três cores são personalizáveis no painel. Animações respeitam a preferência de movimento reduzido. O seletor de e-mails traduz opções legíveis para filtros do Gmail, mantendo busca avançada opcional e compatibilidade com configurações antigas.

Excluir uma captura individual exige dois cliques no ícone, com estado vermelho temporário, como no chat. O editor exibe uma aura e estrelas animadas durante a captura; esses elementos são sobreposições da interface e não entram no arquivo exportado.

## Verificação local da ferramenta de imagem

tests/test_chat_tools.py valida contratos, arquivos persistidos, filtros, configurações e limpeza de logs com fixtures. tests/desktop_smoke.py testa o HTML/Qt e o caminho HTTP local com imagens sintéticas.

Para executar o cliente HTTP real contra uma simulação Postman salva, use o Python da PIA para rodar tests/simulate_chat_images.py. Requer Postman CLI 1.70 ou superior; o script inicia postman/simulations/chat-images.sim.yaml na porta 4903, verifica a geração e um erro 503 pelos eventos de requisição e encerra os processos que iniciou. Não chama provedores reais nem publica recursos no Postman.


## Recuperação automática de repetições na transcrição

A PIA considera suspeita uma palavra ou frase curta repetida seis vezes seguidas, ignorando caixa, acentos e pontuação. A detecção continua entre segmentos do mesmo arquivo, cobrindo casos como uma faixa de participante com vários “aham”. É uma heurística: repetição real também pode acioná-la; o limite é configurável.

O Whisper local solicita timestamps de palavras para arquivos enviados. Ao encontrar um ciclo, o gerador é interrompido, preservando o conteúdo anterior. Se o alinhamento das palavras for válido, preserva inclusive o texto bom dentro do segmento afetado. Sem esse alinhamento, refaz o segmento inteiro. Não estima o instante da repetição pela quantidade de caracteres ou pela duração média de palavras.

A região restante é recortada diretamente nas amostras do áudio original e retranscrita em janelas de até 60 segundos. As emendas usam fins de palavras ou segmentos reais e deixam uma margem na borda para refazer a última fala incompleta. Cada resultado recebe o deslocamento real do seu recorte; a duração total do arquivo permanece a original, inclusive pausas e silêncio final. O texto repetitivo não é reaproveitado como prompt de contexto.

As novas tentativas usam contexto de janela independente, VAD, timestamps de palavras e ajustes de decodificação do faster-whisper. Não há uma substituição textual que simplesmente apague palavras repetidas. Veja os [parâmetros oficiais](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py). Whisper remoto/Groq usa a mesma detecção e recomposição, reenviando WAV dos trechos afetados; se não conseguir recuperar, a cadeia existente tenta o próximo provedor disponível. Texto sem timestamps não é convertido em silêncio nem recebe tempos inventados.

Limites em config/.env (também disponíveis na tela de configurações):

- STT_RECOVERY_ENABLED=true
- STT_RECOVERY_REPETITIONS=6
- STT_RECOVERY_MAX_PHRASE_WORDS=8
- STT_RECOVERY_MAX_RETRIES=3 por ponto de reinício
- STT_RECOVERY_MAX_REPAIRS=12 por arquivo
- STT_RECOVERY_WINDOW_SECONDS=60

Há também uma proteção global contra excesso de janelas e contra geradores que ficam emitindo segmentos. Se os limites forem atingidos ou não houver uma emenda segura, a transcrição falha com uma mensagem clara; um resultado parcial não é devolvido como se fosse completo. O tempo limite OPENAI_COMPAT_TIMEOUT_SECONDS continua valendo para a requisição inteira e precisa comportar o áudio longo e suas tentativas.

O podcast valida caches de transcrição antes de reutilizá-los. Cache inválido ou repetitivo é reconstruído pela PIA quando a sessão for reprocessada, com substituição atômica após sucesso; os resumos derivados desse cache são invalidados para não reutilizar texto baseado no erro. Sessões já publicadas não são republicadas automaticamente por essa mudança.

Os testes cobrem repetições dentro e entre segmentos, frases repetidas, preservação de prefixo, recortes em amostras, pausas, emendas de janelas, silêncio, timestamps inválidos, limites de recuperação, fallback e caches. São testes determinísticos com modelo/provedor simulado; não medem a qualidade de reconhecimento do áudio real de uma sessão.


Consulte [Interface, configurações e extensões](EXTENSIONS.md) para o inspetor, campos tipados, uploads de credenciais, manifestos e idiomas.


A interface atual usa React/Mantine. Consulte [Workspace React e progresso do podcast](REACT_WORKSPACE.md) para o build, navegação, cache, reinício e transcrição local medium.
