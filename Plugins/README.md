# Projetos de plugins

- `Skills/`: skills Python de voz com `execute` e APIs injetadas.
- `Browser/`: integrações de navegador, em projetos separados.

Veja [o contrato e o exemplo](../docs/SKILLS.md).

- `Connectors/`: conectores com múltiplas contas e recursos compartilhados, incluindo Google/Microsoft, Discord e Object Storage.
- `Bot/`: tarefas locais persistentes; a primeira é a secretária de agenda/Gmail.
- `Apps/podcast_automation/`: código completo do Podcast Automation incorporado à PIA,
  incluindo testes, utilitários e licença; nenhum clone externo é necessário na instalação.

Veja [Desktop e integrações](../docs/DESKTOP.md). Tokens OAuth ficam no cofre do
sistema. Configurações de cada plugin ficam em sua própria pasta.

Apps podem declarar `[voice]` no próprio `plugin.toml`. Não duplique o app em `Skills/` para expor comandos.
