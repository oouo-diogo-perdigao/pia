# Plugin Discord

Guarda a configuração do bot no `.env` deste plugin, migrada do podcast. `DISCORD_BOT_ID`, `DISCORD_BOT_PUBLIC_KEY`, `DISCORD_BOT_TOKEN`, `DISCORD_BOT_PERMISSIONS`, `DISCORD_BOT_URL` e `DISCORD_LINK` pertencem aqui. `DISCORD_CHANNEL_ID` escolhe o canal padrão de notificações.

A URL OAuth do bot instala/autoriza o bot; ela não é uma URL de webhook. `Discord().send(text,channel=None)` usa o token de bot na API oficial de mensagens, com menções automáticas desabilitadas. `public()` retorna somente metadados e o estado de configuração. O bot precisa das permissões de visualizar e enviar mensagens no canal.

Skills: `piaPlugins('discord','status')` e `piaPlugins('discord','message.send',text='texto',channel='ID')`. O podcast só envia quando a opção de notificação estiver habilitada. A PIA não envia uma mensagem de teste durante a migração.

Configure em Configurações → Discord. [Portal de desenvolvedores](https://discord.com/developers/applications), [documentação oficial de mensagens](https://docs.discord.com/developers/resources/message#create-message).

## Diagnóstico e teste

Salve o token e as variáveis antes de usar o painel. **Verificar conexão** consulta a identidade da aplicação e o canal, sem enviar mensagem. **Enviar mensagem de teste** envia uma mensagem identificada como teste para o canal informado; vazio usa `DISCORD_CHANNEL_ID`. O log é exibido na mesma tela e fica em `logs/discord.log`, com rotação e tokens ocultados. Erros incluem HTTP, código, mensagem e detalhes retornados pelo Discord; erros locais também são registrados. Sucesso no diagnóstico confirma autenticação/acesso, mas somente o envio confirma permissão efetiva para publicar.

## /link e execução local

Use **Registrar /link e conectar**. O registro cria/atualiza somente esse comando, preservando os demais comandos da aplicação. O token é usado na API oficial; não é necessário abrir o portal para registrar comandos. Com `discord.py` instalado e `DISCORD_LINK_ENABLED__BOOL=true`, a PIA abre uma conexão de saída com o Gateway do Discord. O SDK gerencia heartbeat e reconexão. Não há servidor público, túnel, porta aberta no roteador ou necessidade dos intents privilegiados de conteúdo/membros.

Com a PIA aberta e o painel indicando **Conectado**, use `/link` no canal de texto ou anúncios desejado. A resposta é privada, informa `DISCORD_CHANNEL_ID=<id>` e salva o valor no `.env` deste conector imediatamente. O histórico do vínculo (servidor, canal, autor e horário) fica no `config.json` privado. O painel mostra o ID com botão de copiar e atualiza o campo de configuração; não é necessário reiniciar para publicar no novo canal. No Podcast Automation, deixe o canal específico vazio para seguir o padrão do conector; um canal específico continua tendo prioridade.

O comando tem `default_member_permissions=8` (Administrador), fica disponível somente em servidores e valida a permissão novamente ao executar, mesmo se alguém mudar as permissões de comandos no Discord. DMs e membros sem Administrador são rejeitados. O bot precisa poder ver e enviar mensagens no canal. O primeiro vínculo fixa o servidor; administradores de outro servidor não podem redirecionar essa instalação. **Remover vínculo local** permite trocar de servidor. As restrições opcionais são:

- `DISCORD_GUILD_ID`: restringir a um servidor específico, inclusive antes do primeiro vínculo.
- `DISCORD_ADMIN_USER_IDS`: IDs de usuários separados por vírgula; se preenchido, somente esses usuários **e** com Administrador podem vincular.

Desativar o listener não impede envios de publicação. Ao fechar a PIA por completo, o bot fica offline para `/link`; o canal salvo permanece. Ao reiniciar a PIA, o listener inicia se estiver habilitado. Se trocar token/variáveis, use **Reconectar** após salvar. Rode novamente `install.sh` para instalar a nova dependência `discord.py>=2.6,<3` em outra instalação.

Se a aplicação já tiver um **Interactions Endpoint URL**, o registro mostra um erro: Discord entrega interações por HTTP ou pelo Gateway. A PIA não remove automaticamente esse endpoint, para preservar uma eventual integração existente. Para adotar o listener local, remova o endpoint no portal e registre novamente. O comando global pode levar alguns instantes para aparecer; a instalação deve incluir os escopos `bot` e `applications.commands`.

Referências: [comandos e permissões](https://docs.discord.com/developers/interactions/application-commands), [recebimento de interações](https://docs.discord.com/developers/interactions/receiving-and-responding).


## Manifesto e idioma

Os metadados desta extensão ficam em `pia.json` e os textos em `lang/pt-BR.json`. Consulte o [padrão de extensões e variáveis tipadas](../../../docs/EXTENSIONS.md) para criar telas, campos de configuração e integrações compartilhadas.


A tela atual usa React/Mantine. Consulte [o guia do workspace React](../../../docs/REACT_WORKSPACE.md). Componentes dos apps/bots ficam em `web/Panel.jsx`; os painéis de conectores são apresentados por `src/pia/frontend/Settings.jsx`.
