# 0002 — Limites entre plugins e núcleo

Status: Aceita; registro da arquitetura existente em 2026-10-30.

## Contexto

A PIA agrega apps, bots, skills e serviços de várias contas. Duplicar autenticação, STT/LLM ou lógica de bot no núcleo e em plugins dificulta manutenção e produz configurações conflitantes.

## Decisão

Apps concentram fluxos/UI; bots concentram automações persistentes; conectores gerenciam serviços e contas; skills compõem capacidades. O núcleo fornece infraestrutura comum. Metadados ficam em `pia.json` e entradas técnicas em `plugin.toml`. Apps podem expor comandos de voz sem uma cópia em Skills. Podcast Automation reside integralmente em Apps e consome transcrição da PIA e conectores compartilhados.

Configuração nativa pertence a `config/`; configuração de extensão à pasta da extensão; segredos usam os mecanismos privados existentes. Ferramentas compartilham registro/schema; protocolos adaptam esse registro, sem duplicar operações.

## Consequências

Novas integrações reutilizam contas explicitamente selecionadas. Mudanças podem exigir migração compatível sem sobrescrever dados. Motores com dependências conflitantes, como ACE-Step, usam ambiente isolado. Referências: [arquitetura](../architecture.md), [configuração](../configuration.md).
