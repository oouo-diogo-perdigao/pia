# Configurar e usar o app Podcast Automation na PIA

## Ambiente

Execute `bash install.sh` na raiz da PIA. Ele prepara Python, FFmpeg/SoX e os
extras do podcast e abre o desktop. Depois use `bash start.sh` para reabrir.
O app usa a `.venv` da PIA. Não mantenha outro clone nem instale dependências
separadamente nesta pasta. Não existem Dockerfiles, contêineres ou scripts de
instalação próprios do podcast.

## Configuração

No desktop, clique no botão do Podcast à esquerda e depois em Configurações.
Edite `.env` e `config/config.json` do próprio app. Os exemplos distribuídos ficam
em `docs/examples/.env.example` e `docs/examples/config.example.json`.

Configure nomes, campanhas, participantes e chaves RSS por campanha. Preserve os
objetos `nomes_reais`, `campaign_details`, `publication`, `audio` e `processing`.
Os caminhos relativos são resolvidos a partir desta pasta do app; dados de
trabalho e caches ficam em `data/`.

Para origem local, use `DRIVE_PROCESS=false` e configure `LOCAL_DRIVE_FOLDER`.
Para origem Google Drive, configure a credencial e pasta indicadas no exemplo.
Publicação S3/R2 exige endpoint, bucket, chaves e URL pública. Os links para obter
credenciais aparecem na tela de configuração. A transcrição usa a API da PIA por
padrão; `TRANSCRIPTION_PROVIDER=whisper` seleciona o fallback local do processador.

## Painel

- Processar sessões: verifica uma vez por padrão; marque monitoramento contínuo se desejado.
- Unir SRT/VTT: escolha dois arquivos e uma saída diferente dos originais.
- Reconstruir feeds: atualiza RSS e páginas no armazenamento configurado.
- Parar tarefa: interrompe o processo, preservando arquivos de trabalho.

Processamento/publicação pede confirmação no painel. Fechar a PIA encerra os
processos que ela iniciou. Arquivos já publicados não são desfeitos ao interromper.

## Voz

A seção `[voice]` de `plugin.toml` registra os comandos diretamente deste app.
Diga **comando podcast** e depois **iniciar**, **status**, **parar processamento**,
**abrir RSS**, **abrir transcrições** ou **finalizar**. A ativação não inicia
publicações; **iniciar** processa pendências uma vez. **finalizar** encerra a
interação e interrompe o processamento iniciado por ela.

O código da integração fica em `voice/`. Não há cópia em `Plugins/Skills`, caminho
para repositório externo, instalação de skill ou ambiente uv independente.

Veja também [edição e sincronização](AUDIO.md) e [publicação e RSS](PUBLICACAO.md).
