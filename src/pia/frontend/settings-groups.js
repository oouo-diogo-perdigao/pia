export function fieldGroup(field) {
  const name = field.base || field.name;
  if (/^STT_/.test(name)) return "STT";
  if (/^TTS_/.test(name)) return "TTS";
  if (/^ICE_/.test(name)) return "Imagens · ICE";
  if (/^(LLM_|AGE_|GEMINI_|GROQ_|OPENROUTER_|CLOUDFLARE_)/.test(name))
    return "LLMs";
  if (/^(OVE_|WAKE|AUDIO_|START_SOUND|END_SOUND)/.test(name))
    return "Voz e áudio";
  return "Geral";
}
