# Skills de execução da PIA

Valem as instruções da raiz e de Plugins. Leia [docs/SKILLS.md](../../docs/SKILLS.md) e o exemplo existente antes de alterar o contrato.

- Estas são skills de voz/execução da PIA, não arquivos SKILL.md de um agente programador. Não misture os dois formatos.
- Use APIs injetadas e serviços compartilhados; respeite cancelamento e lifecycle do runtime. Não acople a skill diretamente a widgets ou a segredos de contas.
- Apps podem declarar voz no próprio plugin.toml; não duplique o app aqui.
- Chamadas `piaTools` usam o registro/schema comum; não crie caminhos alternativos que ignorem validação, autenticação ou seleção de conta.
- Documente entradas, saídas, recursos acessados e dependências no README da skill; teste sem microfone/contas reais quando possível.
