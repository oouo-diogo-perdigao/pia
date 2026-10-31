# 0001 — Interface web compartilhada

Status: Aceita; registro da arquitetura existente em 2026-10-30.

## Contexto

A PIA precisa oferecer o mesmo chat e apps no navegador e na janela desktop, com inspeção HTML/CSS/JS e componentes visuais consistentes. Uma segunda implementação em widgets Qt duplicaria comportamento e correções.

## Decisão

Usar React/Mantine e Vite para o workspace e telas integradas; servir o bundle localmente. Qt fornece janela, Chromium incorporado, bandeja e capacidades nativas. Mini PIA permanece em `src/piamini`; componentes web gerais ficam em `src/pia`. Node é ferramenta de build, não servidor obrigatório de produção.

## Consequências

Alterações frontend exigem build dos assets versionados. O navegador continua suportado mesmo sem ponte nativa; operações exclusivamente nativas devem informar sua disponibilidade. Design e interação usam componentes compartilhados. Referências: [arquitetura](../architecture.md), [workspace React](../REACT_WORKSPACE.md).
