# Taverns (Tav.gg)

1. Instale seu bot na taverna de destino e conceda acesso de leitura e envio no canal.
2. Em **Configurações → Conectores → Taverns**, salve o token do bot.
3. Clique em **Carregar canais**, escolha um canal e clique em **Enviar mensagem de teste**.
4. Em **Podcast Automation → Integrações**, selecione os canais Tav.gg e habilite o anúncio.

O token fica no cofre da PIA. O anúncio publica texto com os links do episódio, sem anexar os arquivos. A seleção do Discord é independente da seleção da Tav.gg.

O conector publica via HTTP, por isso o bot pode aparecer offline na lista de membros. Se a Tav.gg responder `AGE_VERIFICATION_REQUIRED`, confira a classificação da taverna e do canal. Caso a classificação esteja correta ou o bloqueio pareça indevido, consulte o suporte sobre o acesso de bots. [Controles de conteúdo adulto na Tav.gg](https://tav.gg/docs/safety#control-sensitive-content).

As rotas locais `POST /api/pia/integrations/taverns/channels` e `POST /api/pia/integrations/taverns/test` usam a sessão local da PIA. A primeira retorna `configured` e opções `channels` com `value` e `label`. A segunda recebe `destination` com o `value` da opção e retorna o ID da mensagem. Não é necessário manter um gateway conectado para publicar. [Portal do bot](https://tav.gg/developers/home) · [SDK oficial da Taverns](https://github.com/Tav-gg/taverns.js).
