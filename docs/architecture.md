# Arquitetura da PIA

Este documento descreve responsabilidades atuais e limites que devem ser preservados. Mudanças arquiteturais devem atualizar este mapa e, quando alterarem uma decisão duradoura, acrescentar um ADR.

## Entradas e núcleo

`install.sh` prepara o ambiente e inicia a aplicação por padrão. `start.sh` reabre a instalação. `src/launcher.py` é a entrada Python. Scripts de instalação são compartilhados entre Linux e Windows nativo via Git Bash.

`src/HTTPServer.py` concentra as rotas de IA e ações; `src/pia/http.py` adapta HTTP ao workspace. `src/pia/service.py` fornece jobs, serviços e carregamento de apps. `src/desktop_backend.py` compartilha ações do desktop e respostas do chat; `src/workspace_store.py` mantém estado local. Antes de acrescentar uma rota, examine os mecanismos de autenticação já usados pelo handler.

## Interface

`src/pia/frontend/` contém o shell React/Mantine, chat, configurações, navegação e componentes comuns. Vite gera `src/pia/assets/`; navegador e janela Chromium/Qt consomem o mesmo bundle. `src/desktop_ui.py` trata a janela e a ponte nativa. Não construa um segundo chat em widgets Qt.

`src/piamini/` contém a companheira flutuante e seus controles. A Mini é independente da janela completa e da execução em bandeja; ocultá-la não encerra a aplicação.

## Extensões

| Categoria | Responsabilidade |
|---|---|
| `Plugins/Apps` | Fluxos interativos, UI Principal/Sobre e jobs próprios |
| `Plugins/Bot` | Comportamentos persistentes locais, como a secretária |
| `Plugins/Connectors` | Contas, autenticação e operações de serviços compartilhados |
| `Plugins/Skills` | Comandos e composição de capacidades usando APIs injetadas |
| `Plugins/Browser` | Integrações específicas de navegador |

`pia.json` fornece metadados de apresentação; `plugin.toml` define entradas executáveis. O núcleo importa extensões e oferece infraestrutura; regras específicas de um bot/app permanecem no plugin. Apps podem declarar voz no próprio manifesto técnico, sem duplicação em Skills.

## IA, áudio e ferramentas

STT/TTS e gerenciamento de provedores ficam no núcleo. Podcast Automation usa a rota de transcrição da PIA, incluindo local/medium, sem configurar seu próprio Whisper. Preserve duração, segmentos reais, recuperação de repetição e offsets de trechos; consulte os testes e REACT_WORKSPACE.md antes de alterar esse pipeline.

`src/tool_registry.py` centraliza schemas e despacho de ferramentas para skills/agentes. `src/interop.py` adapta MCP e AG-UI. Não declare suporte integral a um protocolo quando o adaptador oferece apenas um perfil. Conector `agents` usa CLIs autenticados em diretório separado; não controla a janela do Codex. Música local usa ambiente separado do Torch da PIA.

## Dados e ciclo de vida

- `config/`: arquivos nativos; plugins mantêm configuração local e exemplos em suas pastas.
- `data/`: banco, histórico e resultados que não podem desaparecer com limpeza de cache.
- `cache/main/<capacidade>` e `cache/<categoria>/<plugin>`: modelos e conteúdo recuperável conforme os caminhos existentes.
- `logs/`: diagnóstico; capturas temporárias em `logs/screenshots`, removidas após salvamento bem-sucedido.

Uma tela observa jobs; não é dona da duração deles. Cancelar uma espera não implica cancelar processamento já enviado a um provedor. Estado concluído exige sucesso real das etapas obrigatórias, inclusive publicação e atualização de feeds no podcast.
