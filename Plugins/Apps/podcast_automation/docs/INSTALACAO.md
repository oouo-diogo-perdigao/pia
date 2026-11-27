# Configurar e usar o app Podcast Automation na PIA

## Ambiente

Execute `bash install.sh` na raiz da PIA. Ele prepara Python, FFmpeg/SoX e os
extras do podcast e abre o desktop. Depois use `bash start.sh` para reabrir.
O app usa a `.venv` da PIA. Não mantenha outro clone nem instale dependências
separadamente nesta pasta. Não existem Dockerfiles, contêineres ou scripts de
instalação próprios do podcast.

## Configuração

Abra o **Podcast Automation** e vá a **Configurações**. Em **Origem das
gravações**, escolha **Google Drive** e selecione a conta e a pasta, ou escolha
**Pasta local** e informe o caminho. Caminhos locais relativos partem de
`Documentos/pia/apps/podcast_automation`. A prévia informa o caminho consultado.

Na mesma tela, configure os formatos de saída, o destino, os anúncios, o
monitoramento e as opções de publicação. Use **Salvar opções** para aplicar as
mudanças ao processamento. As preferências ficam no SQLite do perfil. As
credenciais e contas são gerenciadas nos respectivos conectores.

A hora local usa o relógio e o fuso do sistema. Metadados de origem preservam seu
horário e as datas do RSS são serializadas em UTC.

No editor de campanhas, configure nomes, participantes e chaves RSS por campanha.
Preserve os objetos `nomes_reais`, `campaign_details`, `publication`, `audio` e
`processing`. O arquivo `docs/examples/config.example.json` contém um exemplo.

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
