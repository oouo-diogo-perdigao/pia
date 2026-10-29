# Workspace React e processamento do podcast

A interface do navegador e da janela Qt compartilha o mesmo bundle **React + Mantine**, compilado localmente com Vite. Os arquivos entregues ficam em `src/pia/assets/`; não há dependência de CDN ou de um servidor Node em produção. O Qt continua responsável pela janela, bandeja, Mini PIA e operações nativas. O compositor HTML da Mini e os controles do editor de capturas também usam React/Mantine; a geometria de desenho e os pixels continuam no motor Canvas.

## Código e build

- `src/pia/frontend/`: shell, chat, configurações, navegação e componentes compartilhados.
- `Plugins/Apps/<app>/web/Panel.jsx`: tela React de cada aplicativo.
- `Plugins/Bot/secretaria/web/Panel.jsx`: preferências da secretária.
- `src/pia/frontend/Settings.jsx`: apresentação dos conectores, usando as APIs dos plugins.
- `src/pia/lang/`: traduções da interface geral.

```powershell
npm --prefix src/pia/frontend ci
npm --prefix src/pia/frontend run build
npm --prefix src/pia/frontend test
```

O build inclui source maps para facilitar a inspeção de JSX no DevTools. Abra **Exibir → Inspecionar HTML / CSS / JS**, ou F12 na janela nativa. Os HTMLs de entrada dos apps carregam o mesmo bundle. Uma extensão HTML externa continua podendo usar `/pia/sdk.js`; os apps internos fornecem componentes React registrados no shell.

Botões preenchidos representam ações. Botões de navegação usam a variante sutil com estado selecionado; ações rotineiras usam ícones com tooltip. O link de ajuda de cada variável é um ícone de link externo. `PODCAST_CONFIG` não aparece no editor de variáveis: o arquivo é editado em Podcast Automation → Principal/Campanhas.

## Navegação e preferências

Arraste os ícones dos apps na barra esquerda para mudar sua ordem. A ordem fica no banco local do workspace. A navegação usa `history.pushState` e `popstate`, funciona com voltar/avançar e mantém as últimas **50 telas**. As entradas guardam somente a tela e seus identificadores, nunca callbacks ou ações: voltar ao podcast não inicia processamento ou publicação. Criar chat, salvar, capturar e processar exigem a ação correspondente.

Ao salvar variáveis, a PIA solicita o próprio reinício e reabre a janela. O ambiente herdado da instância antiga é limpo das variáveis gerenciadas para que o novo processo leia os valores recém-salvos. Havendo jobs em execução no workspace, o reinício aguarda sua conclusão; o aviso não bloqueia a navegação. O navegador acompanha o retorno da API. Uma sessão exclusivamente HTTP, sem a sessão gráfica nativa, informa que o reinício exige o launcher.

## Podcast Automation

**Processar sessões** começa imediatamente. As etapas mostram aguardando, em execução, concluída, dispensada ou falha. FFmpeg e STT emitem eventos estruturados consumidos por uma barra separada; as barras de terminal são desativadas no modo gráfico. O log mantém somente mensagens de diagnóstico, com botão de limpar. Todos os visualizadores React de log acompanham o final até o usuário rolar para cima, retomando quando ele volta ao final.

O app exibe links para os arquivos efetivamente enviados e, após atualizar o feed, para RSS e transcrições. As últimas sessões mantêm seus links durante o job. Uma falha preserva o erro específico e não é apresentada como publicação concluída. O download dos utilitários de união de SRT/VTT continua disponível.

As engrenagens ficam na linha dos respectivos seletores. Os anúncios de voz/Discord usam toggles em linhas inteiras. O Discord mantém uma lista de canais vinculados por `/link`, com nomes de servidor e canal; o podcast usa um seletor múltiplo. A proteção original de servidor e de Administrador é preservada. Um canal legado explícito é removido da configuração quando a nova seleção é salva; seleção vazia usa o padrão do conector. O app não pede IDs na interface nova.

### Transcrição local medium e progresso

O podcast envia o arquivo inteiro para `POST /v1/audio/transcriptions` com `model=local/medium` e `response_format=verbose_json`. A PIA escolhe o worker local medium para essa requisição, sem mudar o modelo configurado para o microfone. Modelos diferentes usam diretórios próprios. O primeiro uso pode precisar baixar o modelo.

Uploads comuns ainda aceitam `whisper-1` e os formatos existentes. Se os provedores remotos falharem ou rejeitarem o tamanho, o fluxo de arquivo tenta o local. O prazo de arquivo é `STT_FILE_TIMEOUT_SECONDS__INT` (padrão: 86400 segundos), independente do timeout de chat. A duração e os segmentos continuam sendo tempos reais; nenhum timestamp é inventado. Recuperações de repetição reduzem a janela nas tentativas seguintes. Se não houver recuperação válida, a API retorna erro e a etapa falha.

A recuperação local inclui até dois segundos de contexto anterior e usa outra temperatura de decodificação. O contexto é descartado apenas em limites reais de palavras; se uma palavra atravessa a emenda, o trecho é decodificado novamente sem esse contexto. Repetições curtas podem ser mantidas após nova leitura do áudio, com alinhamento válido e intervalos positivos por palavra; sequências longas e palavras de duração zero continuam acionando a recuperação. Pausas superiores a três segundos interrompem a sequência do detector. O cache de cada participante recebe um certificado de validação vinculado ao SHA-256 do JSON, para não rejeitar novamente uma fala já recuperada nem reutilizar um certificado após alterar o arquivo.

O Podcast Automation só marca o ZIP de origem como processado e limpa os temporários depois que a campanha tiver o RSS e a página de transcrições atualizados com sucesso. Erros nessa etapa preservam a origem e os arquivos locais para outra tentativa. Para publicações antigas cujos arquivos já foram enviados, use **Reconstruir feeds** para atualizar o RSS e a página sem retranscrever o áudio.

O acompanhamento é opcional e não muda a resposta OpenAI-compatible. Informe um identificador aleatório, de 16 a 80 caracteres, em `X-PIA-Transcription-ID`:

```bash
curl http://localhost:8762/v1/audio/transcriptions \
  -H 'Authorization: Bearer local' \
  -H 'X-PIA-Transcription-ID: minha-transcricao-20261025-001' \
  -F 'file=@audio.flac' \
  -F 'model=local/medium' \
  -F 'response_format=verbose_json'
```

Em outra conexão, com a mesma autenticação:

```bash
curl http://localhost:8762/v1/audio/transcriptions/progress/minha-transcricao-20261025-001 \
  -H 'Authorization: Bearer local'
```

```json
{"id":"minha-transcricao-20261025-001","state":"transcribing","percent":42.0,"processed":420,"duration":1000}
```

Pode haver `queued`, `preparing`, `transcribing`, `recovering`, `completed` ou `error`. Antes de o POST chegar ao processamento, a consulta pode retornar 404. Os registros ficam isolados por credencial, são limitados a 1000 e expiram após 24h sem atualização. Apps carregados usam sua capability interna nas duas rotas. Sem o header, clientes existentes recebem exatamente o contrato normal de transcrição.

## Arquivos temporários e cache

Capturas brutas ficam em `logs/screenshots`; depois de salvar com sucesso, o PNG bruto e o registro em memória são removidos. Cancelar também descarta a captura atual. Um erro de salvamento preserva o bruto para nova tentativa. Capturas antigas de `data/screenshots/raw` são migradas para uma subpasta legada em `logs/screenshots` ao abrir o app.

```text
cache/
  main/
    tts/kokoro/
    stt/<modelo>/
    images/{models,output}/
    wakeword/
    models/huggingface/
    actions/
  Apps/
    podcast_automation/{transcription,feeds}/
    object_storage/uploads/
```

O launcher migra os caminhos legados conhecidos no próximo início, sem sobrescrever destinos existentes. Pesos antigos sem identificação ficam em `main/stt/legacy`, evitando misturá-los com medium. Caminhos externos personalizados são preservados; aliases dos caminhos antigos padrão são normalizados.

## Verificação

```powershell
$env:PYTHONPATH='.;Plugins/Apps/podcast_automation/src'
.venv/Scripts/python.exe -m pytest tests Plugins/Apps/podcast_automation/tests -q
.venv/Scripts/python.exe tests/react_desktop_smoke.py
```

Os testes gráficos carregam o bundle de produção no Chromium/Qt com áudio, imagens, processos e contas simulados. Não publicam podcasts, não enviam mensagens reais e não capturam a tela do usuário. A validação de uma sessão real de várias horas continua dependendo da execução do modelo e das contas configuradas.


## Configurações e conectores

Botões de salvar comparam o formulário com a última versão carregada/salva. Reverter os campos desabilita o botão novamente. Isso vale para a Secretaria, variáveis, contas de storage, preferências de captura e opções/campanhas do podcast. `frontend/forms.js` fornece a comparação canônica compartilhada. Novos formulários devem registrar sua referência depois de carregar e somente depois de uma gravação bem-sucedida.

Os endpoints de gravação (`save`, `save-*`), preferências e Secretaria emitem um toast de sucesso. **Exibir / Histórico de notificações** mostra até 200 mensagens, inclusive erros, armazenadas localmente neste perfil do navegador. O histórico permanece disponível após recarregar a janela.

**Conectores** tem sua própria navegação, com Google, Microsoft, Object Storage e Discord separados. As contas OAuth Google são reutilizadas para Gmail, Agenda e Drive; `GOOGLE_APPLICATION_CREDENTIALS__FILE` deixou de ser exposto e utilizado pelo Drive. Arquivos antigos permanecem no disco para recuperação manual.

No Podcast Automation, abra **Pasta de gravações**, selecione a conta, expanda a árvore do Meu Drive e escolha a pasta. O seletor de **Bucket de destino** também permite escolher a conta e o bucket em uma janela. Confirme em **Salvar opções**; a mensagem de alterações pendentes desaparece ao concluir. Salvar campanhas preserva a última seleção de contas, pasta, bucket e formatos. Acompanhamento de transcrição usa `hh:mm:ss`, velocidade média em múltiplos do tempo real (Speed) e contagem de arquivos concluídos/total, incluindo caches reutilizados.

Cada extensão tem um arquivo em `logs/plugins/<categoria>/<id>.log`, apresentado em **Inspeção e logs**. Operações não registram credenciais nem corpos de solicitações. O podcast também registra a saída do processo, a Secretaria registra os ciclos e os conectores registram suas operações. A limpeza individual aceita apenas caminhos relativos contidos na pasta de logs.

## Transcrições publicadas

### Segmentos de duração zero e resposta preservada

A rota de transcrição e o podcast usam a mesma validação. Um marcador produzido pelo provedor com `start == end` recebe uma extensão técnica de até **20 ms**, sem mover seu início e sem retranscrever o áudio. O próximo início distinto limita essa extensão. No final exato do arquivo, o marcador pode terminar até 20 ms após a duração medida, dentro da tolerância de codec de 100 ms já aceita; `duration` continua sendo a duração real do áudio. Esse pequeno intervalo é uma convenção de apresentação, não um novo alinhamento estimado de palavras. `verbose_json` inclui `timestamp_adjustments` somente quando houve correção, com o final original e o ajustado. Trechos positivos e pausas existentes permanecem inalterados. Tempos negativos, invertidos, fora de ordem ou fora da tolerância continuam inválidos, com índice e valores no erro.

O Podcast Automation preserva o JSON completo da resposta antes de validá-lo em `cache/Apps/podcast_automation/transcription-responses/`. A chave combina SHA-256 do conteúdo enviado, modelo e idioma. Reexecutar a tarefa reutiliza essa resposta sem chamar o STT, inclusive depois de uma falha na validação. Alterar o áudio ou o modelo gera outra chave. Para solicitar uma nova transcrição do mesmo áudio, remova o arquivo de resposta indicado no log. Falhas HTTP não são guardadas como transcrições. Respostas de execuções anteriores à implantação dessa proteção não podem ser recuperadas retroativamente.

A página `transcripts.html` é um arquivo autossuficiente com visual escuro roxo/azul, busca sem distinção de acentos, índice lateral e cópia de uma ou várias sessões. Todos os textos estão em elementos HTML no corpo, inclusive quando um filtro os oculta; não há busca remota nem carregamento preguiçoso de transcrições. CSS e JavaScript ficam em `Plugins/Apps/podcast_automation/web/transcripts/` e são incorporados ao publicar. **Reconstruir feeds** aplica o novo leitor às campanhas existentes. A versão do cache foi incrementada para evitar reaproveitar a renderização anterior.

Notificações do Discord incluem os links realmente publicados: MP3, TXT (se habilitado), RSS e página geral de transcrições. Mensagens longas são divididas entre linhas para preservar os links completos.
