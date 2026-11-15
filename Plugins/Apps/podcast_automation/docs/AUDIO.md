# Edição de áudio

O filtro anterior removia repetidamente silêncio abaixo de **−20 dB**, inclusive pausas de meio segundo. Falas suaves e finais de palavras podiam ficar nessa faixa. Além disso, o áudio encurtava enquanto as legendas continuavam na linha do tempo original.

A edição agora detecta pausas no mix original, antes da normalização, com `silencedetect`. O exemplo usa **−40 dB**, silêncio mínimo de **1,5 segundo** e preserva **0,6 segundo** de cada pausa longa (0,3 antes e 0,3 depois). Pausas menores são mantidas. Fades de 5 ms nas bordas ajudam a evitar estalos. A mixagem e o intermediário são PCM/WAV; o MP3 é codificado uma vez ao final, com compressor e normalização.

Em `config/config.json`, objeto `audio`:

| Propriedade | Efeito |
|---|---|
| `remove_silence` | `false` mantém a duração original; compressor/normalização continuam ativos |
| `silence_threshold_db` | Mais negativo (ex.: −45) protege mais falas baixas; mais próximo de zero corta mais |
| `minimum_silence_seconds` | Só pausas acima dessa duração podem ser encurtadas |
| `keep_silence_seconds` | Quanto sobra da pausa; deve ser menor que a pausa mínima |
| `fade_seconds` | Suavização nas bordas; 0 desativa, máximo 0,05 s |
| `compressor_threshold_db`, `compressor_ratio` | Limiar e intensidade da compressão |
| `compressor_attack_ms`, `compressor_release_ms` | Tempos de ataque e recuperação |
| `loudness_lufs`, `loudness_range`, `true_peak_db` | Alvos do `loudnorm` (exemplo: −16 LUFS, LRA 11, −1,5 dBTP) |

Um `.timeline.json` ao lado do MP3 registra os intervalos originais mantidos. SRT e VTT são regenerados usando esse mapa; transcrições JSON individuais conservam os tempos originais para reutilização. Trechos integralmente removidos não geram legendas de duração zero. Alterar a edição exige regenerar o áudio final e seus derivados a partir de uma cópia das fontes: resultados prontos são reaproveitados para retomar processamentos interrompidos.

Não há configuração universal: ruído de fundo pode impedir a detecção e fala muito baixa pode ainda ser classificada como silêncio. Compare uma gravação curta com `remove_silence=false`, ouça início/fim de palavras e ajuste primeiro o limiar e a margem. O teste automatizado usa tons baixos e pausas sintéticas; ele não substitui escuta das suas gravações.

Sugestões para próximos ajustes:

- Medir o ruído por participante e tratar cada canal **antes** do mix; não aplicar redução agressiva que crie voz metálica.
- Considerar corte baseado em VAD unido de todos os participantes, sempre com margens de fala e um mapa único para áudio/legendas.
- Para distribuição, avaliar loudnorm de duas passagens e checar loudness/true peak do MP3 final. A normalização atual continua em uma passagem.
- Guardar fontes, mapa de edição e resultados para comparar configurações e reverter cortes.

Uma sessão longa gera WAVs grandes e grafos com muitos intervalos; planeje espaço em disco. GPU acelera transcrição, não elimina esse custo de edição.
