# 0004 — Apps de servidor da PIA

Status: Proposta. A captura Tav.gg depende de validação do contrato de voz do provedor.

## Contexto

O desktop Windows ou Ubuntu administra o aplicativo. Um serviço sem interface gráfica mantém a operação no servidor quando os clientes estão fechados. O primeiro caso é gravar sessões de voz da Tav.gg em faixas separadas e entregá-las ao Podcast Automation por meio do Google Drive.

O conector atual usa o token do bot para listar canais e publicar mensagens. A documentação pública e o SDK mostram um gateway e um intent de voz, mas ainda não estabelecem como um bot entra na chamada e recebe mídia separada por participante. O suporte da Tav.gg precisa indicar como essa operação funciona em chamadas com criptografia de ponta a ponta.

## Decisão proposta

- O servidor é dono das regras, do estado das gravações e das credenciais. Desktop e futuro celular usam uma API administrativa autenticada por HTTPS para consultar estado, configurar e operar o serviço.
- Cada regra seleciona canais de voz pelo ID, participantes que podem ativar a gravação, quantidade mínima de pessoas e tempo de espera após o canal esvaziar. A gravação fica desligada por padrão e o bot avisa os participantes no início.
- Uma sessão ativa por canal. Cada participante tem uma faixa na mesma linha do tempo, inclusive quem entrar depois. A captura depende de um ingresso oficial na chamada, autorização de mídia, identidade por faixa e timestamps do transporte.
- O servidor guarda as faixas e a fila de upload em armazenamento persistente. Quando a sessão termina, envia o pacote para uma pasta privada escolhida no Drive, com credenciais próprias do servidor. Retentativas preservam os arquivos locais e evitam duplicação no destino.
- O Podcast Automation continua responsável por editar, transcrever e publicar. O formato de entrada precisa ser validado com o leitor atual, que lista ZIPs e procura faixas FLAC ou MP3. Um pacote nativo da PIA deve identificar a origem e usar identificadores estáveis para mapear participantes, sem fingir que foi gerado pelo Craig.

## Critério para começar a captura

Confirme com a Tav.gg o evento oficial de entrada e saída de voz, a autorização para bots receberem mídia e a forma de receber duas faixas distintas e sincronizadas. Valide primeiro em um canal de teste com dois participantes cientes da gravação. Depois valide upload privado e importação no Podcast Automation.

[SDK de bots da Tav.gg](https://github.com/Tav-gg/taverns.js) · [Documentação de chamadas e criptografia](https://tav.gg/docs/audio-video).
