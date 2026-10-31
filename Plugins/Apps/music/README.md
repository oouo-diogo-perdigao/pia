# Música

App React/Mantine com Principal e Sobre. O manifesto `pia.json` identifica o app; `web_api.py` oferece jobs de instalação e geração, cancelamento da espera e biblioteca. Arquivos ficam na pasta Música do sistema/PIA por padrão; `MUSIC_OUTPUT_DIR__PATH` seleciona outro destino. A biblioteca ainda consulta `data/music` para arquivos antigos. Motor/modelos ficam em `cache/Apps/music` e logs em `logs/plugins/Apps/music-engine.log`.

Escolha de 1 a 10 músicas por pedido, agrupadas em um card. Percentual indica faixas concluídas; o provedor não fornece percentual confiável da inferência individual. O player é compartilhado da PIA e continua ao navegar. A conclusão publica uma notificação e rola até o card se a tela Principal estiver aberta.

O ícone **Reutilizar prompt** do card preenche descrição, letra, provedor, duração solicitada e quantidade de versões, e retorna ao formulário. Ele não inicia uma nova geração automaticamente. Arquivos antigos sem algum desses metadados usam os padrões do formulário.

A PIA solicita o encerramento do processo do motor local ao terminar cada geração; um servidor externo já iniciado não é encerrado. No Windows, processos filhos do interpretador podem sobreviver ao processo principal: a liberação completa de VRAM ainda precisa de correção e validação com hardware. A próxima geração pode demorar para recarregar os modelos.

## Local

Instale Git e uv. Na Principal, use **Instalar motor local (vários GB)**. A PIA prepara ACE-Step 1.5 em Python 3.12 separado do Whisper/TTS, em revisão fixada no serviço. O primeiro início baixa pesos. GPU, memória e duração afetam o desempenho; não há promessa de equivalência de qualidade ao Suno. Também é possível configurar um servidor ACE-Step já instalado em HTTP loopback, com chave opcional. Não exponha esse motor diretamente à rede.

## Google

Gemini/Lyria utiliza a chave Gemini existente da PIA e o modelo configurável `MUSIC_GEMINI_MODEL`. Depende da disponibilidade e cotas da API. Login OAuth Gmail/Drive e assinatura Gemini não substituem a chave da API. Flow Music permite copiar o pedido e abrir o site oficial usando a conta do navegador; não há automação de geração via cookies.

Cancelar encerra a espera e evita salvar o resultado, mas não garante cancelamento do processamento já iniciado no provedor. A duração informada é solicitada, não duração medida.

## Criar apps

Inclua `pia.json`, `plugin.toml`, `lang/pt-BR.json`, página Principal e Sobre. Use `appApi`/`watchJob` e componentes compartilhados em `src/pia/frontend`, retornando jobs para operações longas. Configurações e segredos pertencem à tela de configurações; não devem ser embutidos no JavaScript. Ferramentas de agente são registradas em `src/tool_registry.py` com schema e despacho explícito.
