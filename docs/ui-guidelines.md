# Interface e interação

Estas são convenções de produto para novas telas e correções. Confira componentes compartilhados antes de criar controles.

## Estrutura e visual

- React/Mantine, tema dark com roxo e azul; reutilize tokens, componentes e ícones Lucide existentes.
- Barra esquerda inspirada no VS Code: conversas, bots, conectores, configurações e botões próprios dos apps; conteúdo abre à direita. Preserve ordem personalizada dos apps.
- Chat com interação semelhante ao ChatGPT: Markdown renderizado, texto enviado limpo do compositor e mensagem inserida imediatamente enquanto aguarda resposta.
- Título identifica a tela/conversa/bot atual; não repita títulos, avatares ou descrições desnecessariamente. Use instruções curtas e contextuais.
- Apps oferecem Principal e Sobre. Ajuda extensa fica em Sobre; contas são geridas no conector correspondente.
- Conectores ficam dentro de Configurações, em árvore expansível, sem entrada independente na barra de atividades. Variáveis gerais usam abas por capacidade e nome/valor na mesma linha.
- Português é o padrão; interface geral oferece português/inglês. Use o mecanismo de tradução existente; novas extensões incluem `lang/pt-BR.json`.

## Controles e feedback

- Ações rotineiras usam ícones com tooltip e nome acessível. Ações pouco comuns podem usar texto. Navegação deve ser visualmente distinta de execução.
- Salvar só fica habilitado quando o estado difere do persistido. Reverter as alterações deve desabilitar o botão novamente. Sucesso em salvar produz toast.
- Erros: alerta vermelho por cerca de 20 segundos, pausa ao passar o mouse e cópia do erro completo ao clicar. Não exponha segredos no erro.
- Tooltips desaparecem ao sair do alvo ou desmontar/alterar a ação. Não deixe tooltip órfão após arquivar/desarquivar ou trocar de tela.
- Exclusão individual de mensagem/captura: primeiro clique arma confirmação visual vermelha, segundo exclui. Exclusão em massa usa seleção explícita, cancelar e confirmação única pela lixeira, sem outro diálogo.
- Copiar/tocar apresentam confirmação verde por dois segundos somente após a ação ter sido aceita com sucesso.
- Renomear conversa e editar mensagem acontecem no próprio local, sem modal. Renomeação: Enter conclui, Esc cancela.
- Seletor de pasta/bucket deve mostrar nomes/caminhos, não apenas IDs; reutilize navegação em árvore, conta explícita e diálogo de seleção.

## Estado e operações longas

Voltar/avançar restaura telas (até 50 entradas), sem repetir ações. Mudar de tela não interrompe processamento. Separe progresso estruturado de logs; exiba tempos legíveis, velocidade e contagem quando disponíveis. Logs seguem o final até rolagem manual para cima e retomam ao retornar ao final.

Logs oferecem recolhimento, busca e abertura do arquivo completo. A tela de inspeção agrupa por categoria/plugin, inicia com últimas 100 linhas e preserva os incrementos recebidos na sessão do visualizador. Notificações e reprodução musical são serviços compartilhados da plataforma; apps não mantêm sistemas paralelos. Preferências de leitura automática e silenciamento por origem pertencem à central de notificações.

Conversas preservam ramificações de edição/regeneração, usando apenas o caminho atual no contexto. Fork cria outro chat. Preserve pastas, retorno à lista sem pasta, pin, arquivo e seleção em massa. Microfone do compositor é ditado, não início de conversa de voz.

## Mini e capturas

Mini sempre acima das janelas, com passagem de cliques no corpo e arraste por área própria do menu. Compositor conserva rascunho ao perder foco. Menu mantém os intervalos existentes de exibição/cooldown; reações aleatórias não devem piscar continuamente. Fechar Mini apenas oculta essa interface.

Capturas usam `/action/screen-all`, sem ocultar a Mini, menu, compositor ou janela principal e sem espera artificial para ocultá-los. A Mini pode aparecer na imagem capturada. Editor sobre a imagem, zoom por Ctrl+scroll, recorte pelo botão esquerdo e anotação pelo direito; botão oposto cancela gesto. Nova captura reinicia posição/zoom. Salvar por padrão no destino e clipboard; remova temporário só após sucesso. Biblioteca em grade com carregamento progressivo, sem reconstrução contínua das seções. Não acrescente integração de e-mail ao app de capturas.

Notificações: silenciamento no menu de botão direito de cada app/bot; leitura automática no menu de botão direito do sino. Não acrescente esses toggles ao corpo da central. Contadores vermelhos indicam mensagens/avisos não visualizados; Bots e Conversas agregam os contadores de seus filhos. Logs começam expandidos, preservando a opção de recolher.
