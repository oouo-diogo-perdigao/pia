# Skill de exemplo

Ative dizendo **comando exemplo de skill**. A PIA fala as opções e mantém a interação aberta. Depois diga **imagem**, **piscar**, **olhar** ou **finalizar**. `fechar` também encerra esta skill.

A imagem local é aberta no visualizador padrão. A fala termina antes de aceitar os próximos textos. Palavras globais de encerramento são filtradas pela PIA antes de chamar o listener.

## Desenvolvimento independente

```powershell
cd Plugins/Skills/exemplo
uv run python -m unittest discover -s tests -v
```

O teste injeta mocks; não abre imagens, não reproduz áudio e não precisa importar o servidor. Copie o projeto para uma pasta nova, altere `plugin.toml` e implemente `execute`. Consulte [o contrato das APIs](../../../docs/SKILLS.md).
