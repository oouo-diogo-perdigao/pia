# Bots

Valem as instruções da raiz e de Plugins.

- Toda lógica específica do bot fica na sua pasta; o núcleo carrega e utiliza o bot, sem manter uma segunda implementação.
- Bots persistentes rodam localmente e não dependem da tela aberta. Evite timers duplicados, notificações repetidas e tarefas sobrevivendo indevidamente ao shutdown.
- Use conectores e conta explicitamente selecionada para agenda/e-mail. Preserve permissões e não envie mensagens em testes comuns.
- Configurações usam formulário compartilhado, dirty state e toast. Para secretária, antecipação de Meet é configurável em minutos; filtro de e-mail deve ter opções compreensíveis.
- Avatar SVG animável, cores personalizáveis e compacto no layout. Cabeçalho identifica `Bots / avatar / nome` sem repetir avatar e descrição no corpo desnecessariamente.
- Mantenha logs identificados pelo bot sem conteúdo sensível de mensagens/credenciais por padrão.
