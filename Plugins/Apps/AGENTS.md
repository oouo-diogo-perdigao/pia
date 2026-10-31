# Apps

Valem as instruções da raiz e de Plugins. Leia as diretrizes de UI antes de alterar painéis.

- Apps oferecem Principal e Sobre em HTML/React, com metadados públicos em pia.json e entradas em plugin.toml. Reutilize o bundle e componentes do workspace.
- Contas/credenciais são configuradas em Conectores; app seleciona conta, pasta, bucket ou canal com nomes compreensíveis e caminhos. Engrenagem de configuração fica na mesma linha do seletor.
- Operações longas são jobs independentes de navegação. Exiba progresso separado dos logs, erros reais e links apenas para resultados existentes.
- Podcast usa o serviço de transcrição da PIA, local/medium quando solicitado pelo fluxo atual; não reintroduza pipeline Whisper, Docker ou cópia em Skills. Preserve artefatos e origem em falhas de publicação. Processamento automático e desligamento ao concluir são mutuamente exclusivos.
- Capturas usam screen-all; não adicione envio por e-mail. Temporários ficam em logs/screenshots e são removidos após salvamento bem-sucedido, não antes.
- Música local tem ambiente separado e instalação explícita; não prometa disponibilidade de geração Google com base apenas em login OAuth.
