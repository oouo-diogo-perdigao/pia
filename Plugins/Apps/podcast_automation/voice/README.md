# Comandos de voz do app

Carregados pela seção `[voice]` de `../plugin.toml`. Esta pasta pertence ao app;
não é instalada nem copiada para `Plugins/Skills`.

- **comando podcast**: inicia a interação.
- **iniciar**: processa as pendências uma vez, podendo publicar conforme a configuração.
- **status**: informa etapa e percentual.
- **parar processamento**: interrompe a tarefa.
- **abrir RSS** / **abrir transcrições**: abre o último link publicado na execução.
- **finalizar**: fecha a interação e interrompe a tarefa iniciada por ela.

O processo usa `sys.executable`, isto é, o Python da PIA, e o `.env` do app.
Os logs completos ficam em `../data/logs/`. O bloqueio do processador impede
processamentos simultâneos da mesma origem pelo painel e pela voz.
