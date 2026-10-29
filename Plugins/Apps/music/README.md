# Música

App React/Mantine com Principal e Sobre. O manifesto `pia.json` identifica o app; `web_api.py` oferece jobs de instalação e geração, cancelamento da espera e biblioteca. Arquivos ficam em `data/music`, motor/modelos em `cache/Apps/music` e logs em `logs/plugins/Apps/music-engine.log`.

## Local

Instale Git e uv. Na Principal, use **Instalar motor local (vários GB)**. A PIA prepara ACE-Step 1.5 em Python 3.12 separado do Whisper/TTS, em revisão fixada no serviço. O primeiro início baixa pesos. GPU, memória e duração afetam o desempenho; não há promessa de equivalência de qualidade ao Suno. Também é possível configurar um servidor ACE-Step já instalado em HTTP loopback, com chave opcional. Não exponha esse motor diretamente à rede.

## Google

Gemini/Lyria utiliza a chave Gemini existente da PIA e o modelo configurável `MUSIC_GEMINI_MODEL`. Depende da disponibilidade e cotas da API. Login OAuth Gmail/Drive e assinatura Gemini não substituem a chave da API. Flow Music permite copiar o pedido e abrir o site oficial usando a conta do navegador; não há automação de geração via cookies.

Cancelar encerra a espera e evita salvar o resultado, mas não garante cancelamento do processamento já iniciado no provedor. A duração informada é solicitada, não duração medida.

## Criar apps

Inclua `pia.json`, `plugin.toml`, `lang/pt-BR.json`, página Principal e Sobre. Use `appApi`/`watchJob` e componentes compartilhados em `src/pia/frontend`, retornando jobs para operações longas. Configurações e segredos pertencem à tela de configurações; não devem ser embutidos no JavaScript. Ferramentas de agente são registradas em `src/tool_registry.py` com schema e despacho explícito.
