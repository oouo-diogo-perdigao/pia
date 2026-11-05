# Conectores

Valem as instruções da raiz e de Plugins. Consulte [configuration.md](../../docs/configuration.md).

- Conectores concentram autenticação, contas e operações compartilhadas. Não migre regras de processamento/publicação de apps para o conector.
- Suporte seleção explícita entre contas. Não escolha a primeira silenciosamente quando a intenção for ambígua. IDs internos devem ser apresentados com nomes úteis na UI.
- Use cofre, OAuth e serviços existentes; não leia/copie cookies ou tokens de CLIs para simular uma API. Mantenha caminhos de obtenção de credenciais na interface.
- Preserve autorização e restrições de administrador do Discord, proteção de callbacks e escopos. Uma rota local continua precisando de autenticação.
- Respostas e logs não devem divulgar credenciais. Use timeouts e erros compreensíveis; testes simulam serviços externos.
- Agentes externos usam executáveis permitidos, argv explícito, stdin e diretório separado. Preserve read-only/plan; não acrescente escrita ou execução arbitrária sem um contrato explícito.
