# Publicação e RSS

O processador envia MP3, SRT, VTT, roteiro TXT e resumo JSON ao armazenamento configurado. Depois solicita atualização do RSS/transcrições e renomeia o ZIP como processado. Confira permissões e URL pública no [guia de instalação](INSTALACAO.md).

## Preparação ou publicação direta

- `PUBLICAR_DIRETO=false` (padrão): arquivos ficam em `<publication.unpublished_prefix>/<Campanha>/`, normalmente `unpublish/Minha Mesa/`. Revise e mova/copie os arquivos para a pasta final indicada pelo `rss_key` da mesa. Depois reconstrua os feeds.
- `PUBLICAR_DIRETO=true`: usa diretamente a pasta que contém o `rss_key` (por exemplo `campaigns/Minha Mesa/`). O episódio passa a integrar o feed quando ele é atualizado.

O aviso PIA ocorre após upload dos arquivos; no modo preparação isso significa upload para revisão, não que o episódio já esteja no RSS público.

## Reconstruir feeds

Use o botão **Reconstruir feeds** no painel do app da PIA.

O utilitário consulta somente as mesas em `campaign_details` do `config/config.json`, usando a pasta de cada `rss_key`, e atualiza `rss.xml` e a página `TRANSCRIPTS_FILE` (padrão `transcripts.html`). Essa operação escreve no bucket. `SKIP_CLOSED=true` mantém o comportamento de ignorar podcasts fechados; `false` permite atualizar também mesas fechadas que estejam configuradas. Podcasts ausentes da configuração nunca são consultados ou alterados, mesmo quando uma pasta é passada explicitamente. Não há mais leitura de `details.json` remoto; título, descrição, link, autor e estado `closed` vêm da configuração local. Alterações apenas nesses metadados também atualizam os derivados; conteúdo idêntico não é reenviado. Subpastas não são tratadas como episódios da mesa pai.

O feed inclui `OWNER_EMAIL`, nome e idioma configurados, links públicos da conta selecionada no plugin Object Storage e metadados dos episódios. [rss.xml](examples/rss.xml) é um exemplo ilustrativo preservado do projeto anterior. Confira acessibilidade dos links e valide o RSS antes de cadastrar em agregadores.

Não é necessário implantar Lambda/Worker para usar o atual atualizador Python. O documento anterior descrevia um `index.js` ausente deste repositório; a manutenção agora é feita pelo utilitário e pelo processador.

## Reconstrução incremental

Na primeira execução, o programa lê os episódios e grava um cache local em `data/cache/feeds` (ou `FEED_CACHE_DIR`). Nas seguintes, compara uma assinatura dos metadados locais e a listagem de versões dos arquivos remotos (`ETag`, tamanho e data de alteração). Se tudo estiver igual, pula a mesa sem reler resumos, roteiros ou consultar durações com `ffprobe`.

O cache de durações é separado: mudar apenas o título ou descrição da mesa não exige consultar novamente os áudios. Substituir um áudio invalida sua duração. Arquivos novos, removidos ou modificados e derivados apagados/alterados também invalidam o cache da mesa. Buckets/endpoints/URLs públicas diferentes usam caches separados. Podcasts não configurados e mesas fechadas continuam respeitando as regras acima.

Depois de uma reconstrução, uma nova listagem confirma as versões dos derivados e que as fontes não mudaram durante o processamento. Erros de leitura/escrita ou duração não são registrados como reconstrução concluída. Se o cache estiver ausente, corrompido ou sem permissão de gravação, o programa volta ao caminho de reconstrução. Um provedor que não informe versões dos arquivos não habilita a dispensa de leituras.

Para forçar a renderização e comparação, defina `FEED_FORCE_REBUILD=true` no `.env`. Para descartar também as durações, apague a pasta `FEED_CACHE_DIR` com o programa parado. O cache é ignorado pelo Git e não precisa ser enviado ao bucket; o caminho padrão fica em `data/` do app.

## Recuperação

ZIPs `-ok.zip` e `-ok-omitido.zip` não voltam à fila. O processamento reaproveita dados locais para retomar. Se falhar depois de um upload parcial, confira os logs, objetos já enviados e a pasta de trabalho antes de tentar novamente. Upload de vários arquivos, atualização do RSS e rename do ZIP não formam uma transação atômica.
