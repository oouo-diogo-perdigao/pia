# PIA

Leia `AGENTS.md` na raiz e os `AGENTS.md` aplicáveis ao caminho dos arquivos antes de editar. Eles são a fonte principal de instruções do projeto. Consulte `docs/architecture.md`, `docs/development.md` e `docs/testing.md` conforme a tarefa. Links são referências; não assuma leitura automática.

A PIA é local, Windows/Linux, com workspace React/Mantine compartilhado pelo navegador e janela Qt; não crie outro chat em widgets. Apps, bots e conectores concentram implementação e configuração nas respectivas pastas. Preserve autenticação, contas explícitas, jobs independentes da tela e timestamps reais de transcrição.

Verifique comandos no repositório, rode validação proporcional e atualize documentação afetada. Ao mudar fontes frontend, regenere os assets versionados. Não exponha segredos, publique em contas reais ou confunda mocks com validação física. Não faça commit/push/merge ou desligamento por padrão.
