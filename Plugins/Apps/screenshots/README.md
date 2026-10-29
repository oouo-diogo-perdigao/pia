# Capturas de tela

`web/Panel.jsx` apresenta a galeria e preferências em React/Mantine. `web/CaptureEditor.jsx` fornece os controles React do editor; `capture.js` e `image-tools.js` contêm o motor Canvas para seleção e anotação. `native.py` conecta os comandos à sessão gráfica e usa `/action/screen-all` para obter a captura. Não há upload ou integração de e-mail.

Capturas são salvas na pasta configurada e copiadas para a área de transferência por padrão. Arquivos temporários ficam em `logs/screenshots`; o original bruto é descartado depois do salvamento bem-sucedido ou cancelamento. Imagens da galeria podem ser vistas com zoom e copiadas; Esc fecha a prévia.

Use o [guia do workspace React](../../../docs/REACT_WORKSPACE.md) para criar aplicativos com os componentes compartilhados, APIs, navegação e build. `pia.json` declara o nome, descrição e páginas; `lang/pt-BR.json` declara os metadados traduzíveis.
