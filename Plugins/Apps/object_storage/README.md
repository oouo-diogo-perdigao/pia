# App Object Storage

As contas aparecem como botões no app e em Configurações → Conectores → Object Storage. A selecionada usa fundo preenchido, a cor da conta e um check. No app, trocar de conta reinicia bucket e caminho; durante transferências a seleção fica bloqueada. Nas configurações, clicar na conta abre seu formulário de edição.

O caminho é navegável: `bucket / pasta / pasta atual`. A primeira linha de uma
subpasta é **.. / Voltar**; é também destino de arraste. Arraste arquivos ou
seleções para uma pasta, Voltar ou um ancestral no caminho para movê-los dentro
do bucket. O servidor recusa mover uma pasta para si própria ou descendentes e
verifica conflitos antes de copiar; não substitui destinos existentes nessa ação.
Movimentação S3 é cópia seguida de exclusão, não uma transação: cancelamento ou
erro preserva os objetos que já terminaram. Para outras contas/buckets use Transferir.

Trocar de conta limpa bucket, pasta, lista e seleção antes de consultar a nova
conta; respostas atrasadas da anterior são ignoradas. A cor da conta aparece nas
bordas do painel e da listagem. A coluna **Modificado em** usa `LastModified`:
S3 não fornece data de criação universal em `ListObjectsV2`, conforme a
[referência do SDK](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/list_objects_v2.html).

Clicar em arquivo oferece **Abrir**, **Link**, **Navegador** e **Cancelar**.
Abrir baixa em job e usa o aplicativo padrão do sistema, somente no desktop.
Link copia a URL pública da conta e Navegador abre essa URL; é necessário configurar
`public_url` e permitir acesso ao objeto. Nenhuma dessas opções muda permissões.
Baixar continua disponível com URL assinada temporária para objetos privados.

Para copiar ao Explorer/área de trabalho, clique primeiro no ícone de arraste do
arquivo para prepará-lo. Quando pronto, segure esse ícone e arraste para o destino:
o adaptador Qt oferece o arquivo local com ação Copy, sem remover o objeto remoto.
A preparação evita iniciar um arraste antes de o arquivo estar disponível. Esse
fluxo precisa da janela desktop e do suporte do gerenciador de arquivos do SO;
no navegador use Baixar. Downloads preparados aceitam até 2 GiB e ficam em
`cache/Apps/object_storage/downloads`, com handles de sessão válidos por seis horas;
o conteúdo é cache recuperável e pode ser removido quando não estiver em uso.
O frontend nunca escolhe um caminho arbitrário para abrir/arrastar.

Novas operações da API local autenticada: `public-link`, `prepare-local` (job),
`open-local`, `drag-local` (token retornado pelo job) e `move-many` (`keys`, `target`).
Cancelar desaparece após conclusão/erro. Uploads em lote aguardam cada transferência.

Gerenciador HTML integrado à PIA: múltiplas contas, buckets, navegação por prefixos, pastas, listagem paginada, detalhes, download por URL assinada, upload de arquivos/pastas e arraste, fila de transferências com progresso/cancelamento, copiar, renomear/mover e excluir arquivos/pastas.

O app usa exclusivamente `Plugins/Connectors/object_storage` para credenciais e acesso. Configure o bucket padrão em contas restritas que não tenham permissão de listar buckets. A URL pública é necessária para publicar podcasts; o download do gerenciador funciona com URLs assinadas temporárias.

Arquivos são enviados do navegador à PIA em partes de 4 MiB (até 100 GiB por arquivo), depois ao storage com transferências gerenciadas. Uploads incompletos expiram após seis horas e são limpos no próximo início de upload. Cancelamento de uma operação com vários objetos preserva os já concluídos. A página pode baixar os arquivos pelo navegador padrão.

Padrão para novos apps: `plugin.toml` com `[web] entrypoint="index.html"` e `api="web_api.py"`; assets somente em `web/`. Importe `/pia/sdk.js` para `session`, `appApi`, `watchJob`, `settingsLink`, e `/pia/ui.js` para ícones, alertas, tooltips e cópia. `handle(action,data,context)` recebe o serviço da PIA; trabalhos assíncronos usam `Job`, eventos de progresso e `context.jobs`. Nunca exponha credenciais pelo frontend.


## Manifesto e idioma

Os metadados desta extensão ficam em `pia.json` e os textos em `lang/pt-BR.json`. Consulte o [padrão de extensões e variáveis tipadas](../../../docs/EXTENSIONS.md) para criar telas, campos de configuração e integrações compartilhadas.


A tela atual usa React/Mantine. Consulte [o guia do workspace React](../../../docs/REACT_WORKSPACE.md). Componentes dos apps/bots ficam em `web/Panel.jsx`; os painéis de conectores são apresentados por `src/pia/frontend/Settings.jsx`.
