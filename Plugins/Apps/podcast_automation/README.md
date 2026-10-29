# Podcast Automation · app da PIA

Este aplicativo existe exclusivamente dentro da PIA. A instalação, o ambiente
Python e as dependências são preparados por `bash install.sh` na raiz da PIA.
O instalador já abre a PIA. Para reabrir depois, use `bash start.sh`.

Abra o botão Podcast na barra esquerda. Processamento, união de SRT/VTT, feeds,
saída das tarefas e configurações ficam no painel à direita. Não há instalador,
ambiente virtual, interface gráfica avulsa ou contêiner próprios deste app.

```text
plugin.toml              # registro do app e da integração de voz
voice/                   # comandos PIA e acompanhamento do processamento
src/podcast_automation/  # processamento e integrações
utilities/               # operações usadas pelo painel
tests/                   # testes offline
docs/                    # guias e exemplos
config/config.json       # configuração pessoal, ignorada no Git
.env                     # variáveis deste app, ignoradas no Git
```

Configure campanhas e formatos no painel do app; as credenciais ficam nas seções dos plugins em Configurações. Exemplos ficam em
`docs/examples/`. Não use `Plugins/Skills/podcast_automation`: o carregador lê a
seção `[voice]` deste `plugin.toml`, sem cópia instalada em outra pasta.

Voz: **comando podcast**, depois **iniciar**, **status**, **parar processamento**,
**abrir RSS**, **abrir transcrições** ou **finalizar**. Processar pode publicar no
armazenamento configurado e marcar ZIPs; apenas ativar a interação não inicia isso.

[Configuração e uso](docs/INSTALACAO.md) · [Áudio](docs/AUDIO.md) · [Publicação](docs/PUBLICACAO.md)

## Integrações na PIA

O app usa o modelo padrão, a transcrição e a voz da PIA. Não configure LLM_*, PIA_* ou WHISPER_* no app. O processo iniciado pela PIA recebe automaticamente uma identidade interna temporária; não precisa de API key. Essa identidade só autoriza as rotas necessárias em loopback, não aceita Origin de navegador e é revogada quando o processo termina. Execução manual não recebe dispensa de autenticação.

Credenciais Google, Discord e Object Storage são migradas do .env do podcast para `Plugins/Connectors/<integração>/.env`. A migração é idempotente e não sobrescreve configurações conflitantes já existentes. Novas contas de storage podem usar o cofre do sistema. Não há comunicação com esses serviços durante a migração.

No painel, escolha a conta e a pasta do Google Drive, a conta/bucket do Object Storage e as notificações opcionais do Discord/voz. As contas e pastas são retornadas pelos plugins compartilhados. Formatos padrão: MP3 (obrigatório), resumo.json, SRT, TXT e VTT (opcionais, inicialmente habilitados). Somente os selecionados são publicados; MP3 sozinho dispensa transcrição e LLM. Quando só resumo.json precisa do texto, o roteiro é temporário e não é exportado.


## Manifesto e idioma

Os metadados desta extensão ficam em `pia.json` e os textos em `lang/pt-BR.json`. Consulte o [padrão de extensões e variáveis tipadas](../../../docs/EXTENSIONS.md) para criar telas, campos de configuração e integrações compartilhadas.


A tela atual usa React/Mantine. Consulte [o guia do workspace React](../../../docs/REACT_WORKSPACE.md). Componentes dos apps/bots ficam em `web/Panel.jsx`; controles compartilhados ficam em `src/pia/frontend`.


As contas Google são autorizadas em **Conectores / Google**, sem arquivo `GOOGLE_APPLICATION_CREDENTIALS__FILE`. Abra o seletor de pasta, expanda a árvore do Drive, escolha as gravações e confirme em **Salvar opções**. O bucket tem um seletor equivalente por conta. Alterações pendentes habilitam o botão; o toast confirma a gravação. O editor de campanhas preserva essas escolhas.

Na tela Principal, **Desligar o computador ao concluir todos os arquivos** é uma opção da execução, alternativa a **Monitorar novas sessões continuamente**. Ativar uma desativa a outra. Só uma execução única concluída sem erros e sem cancelamento agenda o desligamento para 60 segundos depois. É possível usar **Cancelar desligamento** nessa espera. Windows e Linux usam os comandos de energia do sistema, sem forçar o fechamento dos aplicativos; no Linux o usuário precisa ter permissão para desligar a sessão. Utilitários de legendas e reconstrução de feeds não desligam o computador.

Ao abrir o app, **Gravações pendentes** consulta os ZIPs da pasta e mostra a quantidade e os nomes, sem baixar mídia nem iniciar processamento. ZIPs `-ok.zip` e `-ok-omitido.zip` aparecem na contagem de já processados. Cada ZIP representa uma sessão, que pode conter várias faixas de participantes. A consulta acompanha mudanças de conta/pasta e pode ser atualizada pelo ícone ao lado do título. A pasta é apresentada por seu caminho de nomes no Drive; novas escolhas guardam também esse caminho junto ao ID usado internamente.

Use **Reconstruir feeds** para aplicar o leitor de transcrições às publicações existentes: busca, índice de sessões e cópia individual ou em lote, com todos os textos no corpo do HTML para LLMs. As notificações opcionais do Discord incluem MP3, TXT (quando gerado), RSS e transcrições gerais.
