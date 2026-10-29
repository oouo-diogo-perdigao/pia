# App Object Storage

Gerenciador HTML integrado à PIA: múltiplas contas, buckets, navegação por prefixos, pastas, listagem paginada, detalhes, download por URL assinada, upload de arquivos/pastas e arraste, fila de transferências com progresso/cancelamento, copiar, renomear/mover e excluir arquivos/pastas.

O app usa exclusivamente `Plugins/Connectors/object_storage` para credenciais e acesso. Configure o bucket padrão em contas restritas que não tenham permissão de listar buckets. A URL pública é necessária para publicar podcasts; o download do gerenciador funciona com URLs assinadas temporárias.

Arquivos são enviados do navegador à PIA em partes de 4 MiB (até 100 GiB por arquivo), depois ao storage com transferências gerenciadas. Uploads incompletos expiram após seis horas e são limpos no próximo início de upload. Cancelamento de uma operação com vários objetos preserva os já concluídos. A página pode baixar os arquivos pelo navegador padrão.

Padrão para novos apps: `plugin.toml` com `[web] entrypoint="index.html"` e `api="web_api.py"`; assets somente em `web/`. Importe `/pia/sdk.js` para `session`, `appApi`, `watchJob`, `settingsLink`, e `/pia/ui.js` para ícones, alertas, tooltips e cópia. `handle(action,data,context)` recebe o serviço da PIA; trabalhos assíncronos usam `Job`, eventos de progresso e `context.jobs`. Nunca exponha credenciais pelo frontend.


## Manifesto e idioma

Os metadados desta extensão ficam em `pia.json` e os textos em `lang/pt-BR.json`. Consulte o [padrão de extensões e variáveis tipadas](../../../docs/EXTENSIONS.md) para criar telas, campos de configuração e integrações compartilhadas.


A tela atual usa React/Mantine. Consulte [o guia do workspace React](../../../docs/REACT_WORKSPACE.md). Componentes dos apps/bots ficam em `web/Panel.jsx`; os painéis de conectores são apresentados por `src/pia/frontend/Settings.jsx`.
