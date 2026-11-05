# Workspace web

Valem também os AGENTS.md da raiz e de `src/`. Leia [ui-guidelines.md](../../docs/ui-guidelines.md) e [REACT_WORKSPACE.md](../../docs/REACT_WORKSPACE.md).

- Edite `frontend/` e fontes dos painéis de plugins; não edite `assets/workspace.js` manualmente.
- Reutilize api, shared, Settings, componentes Mantine, ícones e traduções existentes. Não crie outro sistema de toast, formulário ou jobs sem necessidade.
- Serviço/API deve funcionar sem Qt. Operações nativas usam ponte e informam indisponibilidade no navegador.
- Loading não bloqueia navegação. Reanexe ao job ao reabrir tela, libere watchers no unmount e evite polling/reconstrução contínua sem mudança de estado.
- Preserve dirty state, feedback de salvar/erro, acessibilidade dos ícones, tooltips e histórico sem efeitos colaterais. Markdown deve ser renderizado sem permitir HTML arbitrário não confiável.
- Teste com `npm --prefix src/pia/frontend test` e gere `npm --prefix src/pia/frontend run build` a partir da raiz. Inclua os assets gerados no resultado da mudança.
