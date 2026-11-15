# Secretária PIA


## Avatar e interface

avatar.svg é um personagem vetorial animado com corpo, olhos, calendário e estrelas. web/Panel.jsx é o componente React incluído no bundle da PIA, com navegação e controles Mantine compartilhados. O painel consulta a API local e o shell apresenta o avatar no cabeçalho e na barra lateral.

Cores persistidas: avatar_primary, avatar_accent e avatar_eyes, sempre em #RRGGBB. O componente injeta essas cores como variáveis CSS no SVG; os grupos secretary-body, secretary-eyes e secretary-star permitem futuras animações e estados. Há suporte a prefers-reduced-motion.

Os filtros legíveis de Gmail são compilados pelo próprio bot. email_filter aceita important_unread, all_unread, inbox_unread, starred_unread ou custom. email_query continua compatível e só é mostrado no painel ao selecionar Personalizado. Prefira expor novas preferências aqui em vez de colocar código de bot na interface principal.


## Manifesto e idioma

Os metadados desta extensão ficam em `pia.json` e os textos em `lang/pt-BR.json`. Consulte o [padrão de extensões e variáveis tipadas](../../../docs/EXTENSIONS.md) para criar telas, campos de configuração e integrações compartilhadas.


A tela atual usa React/Mantine. Consulte [o guia do workspace React](../../../docs/REACT_WORKSPACE.md). Componentes dos apps/bots ficam em `web/Panel.jsx`; os painéis de conectores são apresentados por `src/pia/frontend/Settings.jsx`.
