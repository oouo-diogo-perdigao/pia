# Mini PIA

Valem também as instruções da raiz e de `src/`. Esta pasta concentra a companheira e controles nativos; não mova chat completo para widgets Qt.

- Corpo permite passagem de cliques; interação e arraste acontecem nas áreas próprias do menu. Preserve compatibilidade Windows/Linux e always-on-top.
- Ocultar Mini não encerra PIA nem remove a bandeja. A janela completa tem visibilidade independente.
- Preserve rascunho do compositor ao fechar/perder foco e evite desaparecimento durante interação.
- Menu tem atraso de recolhimento e cooldown de três segundos. Reações de hover são aleatórias, sem nova tentativa em menos de cinco segundos; não dispare animação a cada polling.
- Não bloqueie a thread Qt com gravação, STT, rede ou espera de job. Preserve cancelamento da resposta anterior no modo conversação; ditado é outro fluxo.
- Capturas não ocultam a Mini, menu ou compositor; preserve a visibilidade atual sem espera artificial. Não capture a tela/câmera real em testes comuns.
