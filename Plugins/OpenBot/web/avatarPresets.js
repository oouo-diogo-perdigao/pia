export const COLOR_PRESETS = [
  // Fileira 1
  {
    id: "coral_red",
    name: "Vermelho Coral",
    colors: { primary: "#E8483F", accent: "#FF9E80", eyes: "#FFF8F6" },
  },
  {
    id: "tomato_red",
    name: "Vermelho Tomate",
    colors: { primary: "#E03E36", accent: "#FFD166", eyes: "#FFF9F5" },
  },
  {
    id: "orange",
    name: "Laranja",
    colors: { primary: "#F08A24", accent: "#FFE066", eyes: "#FFFDF7" },
  },
  {
    id: "gold_yellow",
    name: "Amarelo Ouro",
    colors: { primary: "#F0B429", accent: "#FFF3B0", eyes: "#1F1924" },
  },
  {
    id: "lime_green",
    name: "Verde Lima",
    colors: { primary: "#8ECE34", accent: "#D9F99D", eyes: "#162615" },
  },
  {
    id: "emerald_green",
    name: "Verde Esmeralda",
    colors: { primary: "#3ECF8E", accent: "#A7F3D0", eyes: "#0F2922" },
  },
  {
    id: "turquoise",
    name: "Verde Água",
    colors: { primary: "#2FBFA0", accent: "#99F6E4", eyes: "#F2FFFC" },
  },
  {
    id: "sky_cyan",
    name: "Azul Céu",
    colors: { primary: "#38BDF8", accent: "#BAE6FD", eyes: "#0F2438" },
  },
  {
    id: "royal_blue",
    name: "Azul Royal",
    colors: { primary: "#3B93F0", accent: "#93C5FD", eyes: "#F5FAFF" },
  },
  // Fileira 2
  {
    id: "indigo_blue",
    name: "Azul Índigo",
    colors: { primary: "#34479C", accent: "#818CF8", eyes: "#F5F7FF" },
  },
  {
    id: "violet_blue",
    name: "Azul Violeta",
    colors: { primary: "#5D67EE", accent: "#A5B4FC", eyes: "#F8FAFF" },
  },
  {
    id: "vibrant_purple",
    name: "Roxo Vibrante",
    colors: { primary: "#8B5CF6", accent: "#65D9FF", eyes: "#FAF4FF" },
  },
  {
    id: "magenta_orchid",
    name: "Magenta Orquídea",
    colors: { primary: "#E152B0", accent: "#F9A8D4", eyes: "#FFF5FB" },
  },
  {
    id: "flamingo_pink",
    name: "Rosa Flamingo",
    colors: { primary: "#F27BA5", accent: "#FECDD3", eyes: "#2B1420" },
  },
  {
    id: "crimson_wine",
    name: "Vinho Carmim",
    colors: { primary: "#A8324E", accent: "#FDA4AF", eyes: "#FFF5F7" },
  },
  {
    id: "caramel_brown",
    name: "Marrom Caramelo",
    colors: { primary: "#8B5E3C", accent: "#FCD34D", eyes: "#FFFBEB" },
  },
  {
    id: "sand_beige",
    name: "Bege Areia",
    colors: { primary: "#D6B98C", accent: "#FFFBEB", eyes: "#261E17" },
  },
  {
    id: "neutral_gray",
    name: "Cinza Neutro",
    colors: { primary: "#A3A3A3", accent: "#E5E5E5", eyes: "#18181B" },
  },
];

export const DEFAULT_BOT_COLORS = { ...COLOR_PRESETS[11].colors };

function normalizeHex(hex) {
  return String(hex || "")
    .trim()
    .toLowerCase();
}

export function findMatchingColorPreset(colors) {
  if (!colors || typeof colors !== "object") return null;
  const p = normalizeHex(colors.primary);
  const a = normalizeHex(colors.accent);
  const e = normalizeHex(colors.eyes);
  return (
    COLOR_PRESETS.find(
      (preset) =>
        normalizeHex(preset.colors.primary) === p &&
        normalizeHex(preset.colors.accent) === a &&
        normalizeHex(preset.colors.eyes) === e,
    ) || null
  );
}

export const AVATAR_PRESETS = [
  // 1. Órbita PIA (Existente)
  {
    id: "orb",
    name: "Órbita PIA",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: center; animation: orbPulse 0.42s ease-in-out infinite paused; }
    @keyframes orbPulse { 0%, 100% { transform: scaleY(0.75); } 50% { transform: scaleY(1.25); } }
  </style>
  <circle cx="60" cy="60" r="52" fill="var(--bot-primary, #8B5CF6)" fill-opacity="0.16" stroke="var(--bot-accent, #65D9FF)" stroke-width="3" />
  <circle cx="60" cy="60" r="40" fill="var(--bot-primary, #8B5CF6)" />
  <circle cx="45" cy="52" r="6" fill="var(--bot-eyes, #FAF4FF)" />
  <circle cx="75" cy="52" r="6" fill="var(--bot-eyes, #FAF4FF)" />
  <path d="M 46 72 Q 60 80 74 72" fill="none" stroke="var(--bot-eyes, #FAF4FF)" stroke-width="4" stroke-linecap="round" opacity="0.55" />
  <g class="enable-mouth">
    <rect class="animation-talking" x="45" y="68" width="30" height="10" rx="5" fill="var(--bot-eyes, #FAF4FF)" />
  </g>
</svg>`,
  },

  // 2. Visor Cibernético (Existente)
  {
    id: "visor",
    name: "Visor Cibernético",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: center; animation: visorWave 0.36s ease-in-out infinite paused; }
    @keyframes visorWave { 0%, 100% { transform: scaleX(0.8); } 50% { transform: scaleX(1.15); } }
  </style>
  <line x1="60" y1="10" x2="60" y2="24" stroke="var(--bot-accent, #65D9FF)" stroke-width="4" stroke-linecap="round" />
  <circle cx="60" cy="10" r="5" fill="var(--bot-accent, #65D9FF)" />
  <rect x="20" y="24" width="80" height="74" rx="22" fill="var(--bot-primary, #8B5CF6)" />
  <rect x="30" y="38" width="60" height="24" rx="10" fill="#18122b" stroke="var(--bot-accent, #65D9FF)" stroke-width="2" />
  <ellipse cx="46" cy="50" rx="6" ry="5" fill="var(--bot-eyes, #FAF4FF)" />
  <ellipse cx="74" cy="50" rx="6" ry="5" fill="var(--bot-eyes, #FAF4FF)" />
  <line x1="44" y1="78" x2="76" y2="78" stroke="var(--bot-eyes, #FAF4FF)" stroke-width="4" stroke-linecap="round" opacity="0.5" />
  <g class="enable-mouth">
    <rect class="animation-talking" x="40" y="73" width="40" height="10" rx="5" fill="var(--bot-accent, #65D9FF)" />
  </g>
</svg>`,
  },

  // 3. Coruja Analítica (Existente)
  {
    id: "owl",
    name: "Coruja Analítica",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: center; animation: beakTalk 0.34s ease-in-out infinite paused; }
    @keyframes beakTalk { 0%, 100% { transform: scaleY(0.82); } 50% { transform: scaleY(1.25); } }
  </style>
  <polygon points="26,34 38,16 48,30" fill="var(--bot-accent, #65D9FF)" />
  <polygon points="94,34 82,16 72,30" fill="var(--bot-accent, #65D9FF)" />
  <circle cx="60" cy="64" r="40" fill="var(--bot-primary, #8B5CF6)" />
  <circle cx="44" cy="54" r="14" fill="#1d1832" stroke="var(--bot-accent, #65D9FF)" stroke-width="2.5" />
  <circle cx="76" cy="54" r="14" fill="#1d1832" stroke="var(--bot-accent, #65D9FF)" stroke-width="2.5" />
  <circle cx="44" cy="54" r="6" fill="var(--bot-eyes, #FAF4FF)" />
  <circle cx="76" cy="54" r="6" fill="var(--bot-eyes, #FAF4FF)" />
  <polygon points="53,68 67,68 60,78" fill="var(--bot-accent, #65D9FF)" opacity="0.7" />
  <g class="enable-mouth">
    <polygon class="animation-talking" points="51,68 69,68 60,84" fill="var(--bot-eyes, #FAF4FF)" />
  </g>
</svg>`,
  },

  // 4. Núcleo Prisma (Existente)
  {
    id: "spark",
    name: "Núcleo Prisma",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: center; animation: prismPulse 0.4s ease-in-out infinite paused; }
    @keyframes prismPulse { 0%, 100% { transform: scale(0.88); } 50% { transform: scale(1.16); } }
  </style>
  <polygon points="60,12 104,40 104,84 60,108 16,84 16,40" fill="var(--bot-primary, #8B5CF6)" stroke="var(--bot-accent, #65D9FF)" stroke-width="3" stroke-linejoin="round" />
  <polygon points="60,24 92,45 92,77 60,96 28,77 28,45" fill="#18122b" fill-opacity="0.45" />
  <circle cx="45" cy="54" r="5.5" fill="var(--bot-eyes, #FAF4FF)" />
  <circle cx="75" cy="54" r="5.5" fill="var(--bot-eyes, #FAF4FF)" />
  <rect x="44" y="72" width="32" height="5" rx="2.5" fill="var(--bot-accent, #65D9FF)" opacity="0.6" />
  <g class="enable-mouth">
    <rect class="animation-talking" x="42" y="68" width="36" height="12" rx="6" fill="var(--bot-eyes, #FAF4FF)" />
  </g>
</svg>`,
  },

  // 5. Raposa Astuta (Novo)
  {
    id: "fox",
    name: "Raposa Astuta",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: 60px 84px; animation: foxYip 0.34s ease-in-out infinite paused; }
    @keyframes foxYip { 0%, 100% { transform: scaleY(0.7); } 50% { transform: scaleY(1.35); } }
  </style>
  <polygon points="22,52 18,14 50,36" fill="var(--bot-primary, #8B5CF6)" stroke="var(--bot-accent, #65D9FF)" stroke-width="2.5" stroke-linejoin="round" />
  <polygon points="98,52 102,14 70,36" fill="var(--bot-primary, #8B5CF6)" stroke="var(--bot-accent, #65D9FF)" stroke-width="2.5" stroke-linejoin="round" />
  <polygon points="26,46 24,22 44,36" fill="var(--bot-accent, #65D9FF)" fill-opacity="0.75" />
  <polygon points="94,46 96,22 76,36" fill="var(--bot-accent, #65D9FF)" fill-opacity="0.75" />
  <polygon points="18,54 60,28 102,54 88,92 60,106 32,92" fill="var(--bot-primary, #8B5CF6)" />
  <polygon points="24,62 60,82 60,104 32,92" fill="#18122b" fill-opacity="0.28" />
  <polygon points="96,62 60,82 60,104 88,92" fill="#18122b" fill-opacity="0.28" />
  <ellipse cx="43" cy="58" rx="7" ry="4.5" transform="rotate(14 43 58)" fill="var(--bot-eyes, #FAF4FF)" />
  <ellipse cx="77" cy="58" rx="7" ry="4.5" transform="rotate(-14 77 58)" fill="var(--bot-eyes, #FAF4FF)" />
  <polygon points="54,74 66,74 60,82" fill="var(--bot-accent, #65D9FF)" />
  <path d="M 50 86 Q 60 92 70 86" fill="none" stroke="var(--bot-eyes, #FAF4FF)" stroke-width="3" stroke-linecap="round" opacity="0.65" />
  <g class="enable-mouth">
    <ellipse class="animation-talking" cx="60" cy="87" rx="11" ry="6" fill="var(--bot-eyes, #FAF4FF)" />
  </g>
</svg>`,
  },

  // 6. Astronauta Estelar (Novo)
  {
    id: "astro",
    name: "Astronauta Estelar",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: 60px 84px; animation: astroComms 0.36s ease-in-out infinite paused; }
    @keyframes astroComms { 0%, 100% { transform: scaleX(0.75) scaleY(0.85); } 50% { transform: scaleX(1.2) scaleY(1.25); } }
  </style>
  <rect x="10" y="48" width="10" height="24" rx="5" fill="var(--bot-accent, #65D9FF)" />
  <rect x="100" y="48" width="10" height="24" rx="5" fill="var(--bot-accent, #65D9FF)" />
  <rect x="18" y="18" width="84" height="84" rx="38" fill="var(--bot-primary, #8B5CF6)" stroke="var(--bot-accent, #65D9FF)" stroke-width="3" />
  <rect x="28" y="30" width="64" height="44" rx="20" fill="#141126" stroke="var(--bot-accent, #65D9FF)" stroke-width="2" />
  <path d="M 36 38 Q 48 33 62 36" fill="none" stroke="#ffffff" stroke-width="2.5" stroke-linecap="round" opacity="0.35" />
  <circle cx="46" cy="52" r="6" fill="var(--bot-eyes, #FAF4FF)" />
  <circle cx="74" cy="52" r="6" fill="var(--bot-eyes, #FAF4FF)" />
  <rect x="44" y="82" width="32" height="6" rx="3" fill="#141126" opacity="0.55" />
  <g class="enable-mouth">
    <rect class="animation-talking" x="40" y="79" width="40" height="11" rx="5.5" fill="var(--bot-accent, #65D9FF)" />
  </g>
</svg>`,
  },

  // 7. Gato Guardião (Novo)
  {
    id: "neko",
    name: "Gato Guardião",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: 60px 77px; animation: nekoMeow 0.35s ease-in-out infinite paused; }
    @keyframes nekoMeow { 0%, 100% { transform: scale(0.8); } 50% { transform: scale(1.25); } }
  </style>
  <polygon points="24,48 22,16 50,34" fill="var(--bot-primary, #8B5CF6)" />
  <polygon points="96,48 98,16 70,34" fill="var(--bot-primary, #8B5CF6)" />
  <polygon points="28,44 27,23 45,35" fill="var(--bot-accent, #65D9FF)" />
  <polygon points="92,44 93,23 75,35" fill="var(--bot-accent, #65D9FF)" />
  <ellipse cx="60" cy="64" rx="40" ry="35" fill="var(--bot-primary, #8B5CF6)" />
  <circle cx="44" cy="56" r="6.5" fill="var(--bot-eyes, #FAF4FF)" />
  <circle cx="76" cy="56" r="6.5" fill="var(--bot-eyes, #FAF4FF)" />
  <line x1="14" y1="62" x2="28" y2="64" stroke="var(--bot-accent, #65D9FF)" stroke-width="2.5" stroke-linecap="round" />
  <line x1="14" y1="70" x2="28" y2="70" stroke="var(--bot-accent, #65D9FF)" stroke-width="2.5" stroke-linecap="round" />
  <line x1="106" y1="62" x2="92" y2="64" stroke="var(--bot-accent, #65D9FF)" stroke-width="2.5" stroke-linecap="round" />
  <line x1="106" y1="70" x2="92" y2="70" stroke="var(--bot-accent, #65D9FF)" stroke-width="2.5" stroke-linecap="round" />
  <path d="M 50 74 Q 55 80 60 74 Q 65 80 70 74" fill="none" stroke="var(--bot-eyes, #FAF4FF)" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" />
  <g class="enable-mouth">
    <ellipse class="animation-talking" cx="60" cy="77" rx="10" ry="7" fill="var(--bot-accent, #65D9FF)" />
  </g>
</svg>`,
  },

  // 8. Sentinela Escudo (Novo)
  {
    id: "knight",
    name: "Sentinela Escudo",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: 60px 80px; animation: knightVoice 0.38s ease-in-out infinite paused; }
    @keyframes knightVoice { 0%, 100% { transform: scaleY(0.75); } 50% { transform: scaleY(1.3); } }
  </style>
  <polygon points="52,10 68,10 64,26 56,26" fill="var(--bot-accent, #65D9FF)" />
  <path d="M 24 24 L 96 24 L 96 64 Q 96 96 60 108 Q 24 96 24 64 Z" fill="var(--bot-primary, #8B5CF6)" stroke="var(--bot-accent, #65D9FF)" stroke-width="3" stroke-linejoin="round" />
  <polygon points="32,42 60,52 88,42 84,62 60,70 36,62" fill="#161228" />
  <polygon points="38,48 54,54 52,60 38,56" fill="var(--bot-eyes, #FAF4FF)" />
  <polygon points="82,48 66,54 68,60 82,56" fill="var(--bot-eyes, #FAF4FF)" />
  <line x1="48" y1="80" x2="72" y2="80" stroke="var(--bot-accent, #65D9FF)" stroke-width="3.5" stroke-linecap="round" opacity="0.65" />
  <g class="enable-mouth">
    <rect class="animation-talking" x="44" y="74" width="32" height="12" rx="4" fill="var(--bot-eyes, #FAF4FF)" />
  </g>
</svg>`,
  },

  // 9. Mente Zen (Novo)
  {
    id: "lotus",
    name: "Mente Zen",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: 60px 76px; animation: lotusChant 0.44s ease-in-out infinite paused; }
    @keyframes lotusChant { 0%, 100% { transform: scale(0.82); } 50% { transform: scale(1.22); } }
  </style>
  <polygon points="60,10 68,24 52,24" fill="var(--bot-accent, #65D9FF)" />
  <polygon points="38,16 50,26 36,28" fill="var(--bot-accent, #65D9FF)" opacity="0.75" />
  <polygon points="82,16 70,26 84,28" fill="var(--bot-accent, #65D9FF)" opacity="0.75" />
  <circle cx="60" cy="64" r="38" fill="var(--bot-primary, #8B5CF6)" />
  <circle cx="60" cy="40" r="4" fill="var(--bot-accent, #65D9FF)" />
  <path d="M 36 56 Q 44 48 52 56" fill="none" stroke="var(--bot-eyes, #FAF4FF)" stroke-width="4" stroke-linecap="round" />
  <path d="M 68 56 Q 76 48 84 56" fill="none" stroke="var(--bot-eyes, #FAF4FF)" stroke-width="4" stroke-linecap="round" />
  <path d="M 50 75 Q 60 81 70 75" fill="none" stroke="var(--bot-eyes, #FAF4FF)" stroke-width="3.5" stroke-linecap="round" opacity="0.65" />
  <g class="enable-mouth">
    <circle class="animation-talking" cx="60" cy="76" r="8" fill="var(--bot-accent, #65D9FF)" />
  </g>
</svg>`,
  },

  // 10. Arcade Retrô (Novo)
  {
    id: "pixel",
    name: "Arcade Retrô",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: 60px 76px; animation: pixelBeep 0.3s steps(2, end) infinite paused; }
    @keyframes pixelBeep { 0%, 100% { transform: scaleY(0.65); } 50% { transform: scaleY(1.35); } }
  </style>
  <rect x="18" y="18" width="84" height="84" rx="14" fill="var(--bot-primary, #8B5CF6)" stroke="var(--bot-accent, #65D9FF)" stroke-width="3" />
  <rect x="28" y="28" width="64" height="64" rx="8" fill="#141126" />
  <rect x="38" y="42" width="12" height="12" fill="var(--bot-eyes, #FAF4FF)" />
  <rect x="70" y="42" width="12" height="12" fill="var(--bot-eyes, #FAF4FF)" />
  <rect x="42" y="72" width="36" height="6" fill="var(--bot-accent, #65D9FF)" opacity="0.7" />
  <g class="enable-mouth">
    <rect class="animation-talking" x="38" y="68" width="44" height="14" fill="var(--bot-eyes, #FAF4FF)" />
  </g>
</svg>`,
  },

  // 11. Chama Criativa (Novo)
  {
    id: "flame",
    name: "Chama Criativa",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: 60px 79px; animation: flameFlare 0.36s ease-in-out infinite paused; }
    @keyframes flameFlare { 0%, 100% { transform: scale(0.8) translateY(1px); } 50% { transform: scale(1.25) translateY(-2px); } }
  </style>
  <path d="M 60 10 C 78 30 100 48 96 74 C 92 96 76 108 60 108 C 44 108 28 96 24 74 C 20 48 42 30 60 10 Z" fill="var(--bot-primary, #8B5CF6)" stroke="var(--bot-accent, #65D9FF)" stroke-width="2.5" />
  <path d="M 60 24 C 72 38 84 52 82 72 C 80 88 70 98 60 98 C 50 98 40 88 38 72 C 36 52 48 38 60 24 Z" fill="var(--bot-accent, #65D9FF)" fill-opacity="0.22" />
  <circle cx="46" cy="60" r="6" fill="var(--bot-eyes, #FAF4FF)" />
  <circle cx="74" cy="60" r="6" fill="var(--bot-eyes, #FAF4FF)" />
  <path d="M 48 78 Q 60 85 72 78" fill="none" stroke="var(--bot-eyes, #FAF4FF)" stroke-width="3.5" stroke-linecap="round" opacity="0.65" />
  <g class="enable-mouth">
    <ellipse class="animation-talking" cx="60" cy="79" rx="12" ry="7" fill="var(--bot-eyes, #FAF4FF)" />
  </g>
</svg>`,
  },

  // 12. Onda Acústica (Novo)
  {
    id: "sonar",
    name: "Onda Acústica",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: 60px 76px; animation: sonarWave 0.36s ease-in-out infinite paused; }
    @keyframes sonarWave { 0%, 100% { transform: scaleX(0.75) scaleY(0.8); } 50% { transform: scaleX(1.25) scaleY(1.25); } }
  </style>
  <path d="M 22 40 A 44 44 0 0 1 98 40" fill="none" stroke="var(--bot-accent, #65D9FF)" stroke-width="4" stroke-linecap="round" />
  <rect x="12" y="44" width="12" height="28" rx="6" fill="var(--bot-accent, #65D9FF)" />
  <rect x="96" y="44" width="12" height="28" rx="6" fill="var(--bot-accent, #65D9FF)" />
  <circle cx="60" cy="62" r="36" fill="var(--bot-primary, #8B5CF6)" />
  <circle cx="46" cy="54" r="8" fill="#161228" stroke="var(--bot-accent, #65D9FF)" stroke-width="2" />
  <circle cx="74" cy="54" r="8" fill="#161228" stroke="var(--bot-accent, #65D9FF)" stroke-width="2" />
  <circle cx="46" cy="54" r="4" fill="var(--bot-eyes, #FAF4FF)" />
  <circle cx="74" cy="54" r="4" fill="var(--bot-eyes, #FAF4FF)" />
  <rect x="46" y="73" width="28" height="6" rx="3" fill="var(--bot-accent, #65D9FF)" opacity="0.65" />
  <g class="enable-mouth">
    <rect class="animation-talking" x="40" y="70" width="40" height="12" rx="6" fill="var(--bot-eyes, #FAF4FF)" />
  </g>
</svg>`,
  },
];

export const BOT_TOOL_OPTIONS = [
  {
    value: "pia_accounts",
    label: "Contas e agendas conectadas (pia_accounts)",
  },
  {
    value: "pia_resources",
    label: "Arquivos e recursos locais (pia_resources)",
  },
  { value: "pia_camera", label: "Câmera e visão (pia_camera)" },
  { value: "pia_image", label: "Geração de imagens (pia_image)" },
  { value: "pia_music", label: "Controle de música (pia_music)" },
  {
    value: "delegate_to_bot",
    label: "Delegar para outros bots (delegate_to_bot)",
  },
];

export const LLM_TIER_OPTIONS = [
  { value: "free", label: "Padrão (Seleção automática)" },
  { value: "fast", label: "Rápido (Baixa latência)" },
  { value: "pro", label: "Avançado (Maior raciocínio)" },
];

export const BOT_TEMPLATES = [
  {
    id: "assistant",
    name: "Assistente Focado",
    description:
      "Responde perguntas e organiza tarefas de forma direta e objetiva.",
    instructions:
      "# Papel\nVocê é um assistente especialista objetivo e confiável.\n\n# Regras\n- Responda em português claro.\n- Vá direto ao ponto antes de detalhar.\n- Se faltar contexto essencial, peça apenas o mínimo necessário.",
    llm_tier: "free",
    tool_ids: ["pia_resources"],
    presetId: "orb",
    avatar_colors: { ...COLOR_PRESETS[11].colors },
  },
  {
    id: "reviewer",
    name: "Revisor de Código",
    description:
      "Analisa arquitetura, bugs, segurança e legibilidade em trechos de código.",
    instructions:
      "# Papel\nVocê é um revisor técnico sênior.\n\n# Diretrizes\n- Aponte riscos reais de bug, regressão ou segurança antes de estilo.\n- Sugira correções enxutas e testáveis.\n- Nunca invente resultados de execução que não observou.",
    llm_tier: "pro",
    tool_ids: ["pia_resources"],
    presetId: "visor",
    avatar_colors: { ...COLOR_PRESETS[10].colors },
  },
  {
    id: "researcher",
    name: "Pesquisador & Resumo",
    description:
      "Sintetiza documentos, notas e compromissos com clareza executiva.",
    instructions:
      "# Papel\nVocê sintetiza informações complexas em resumos acionáveis.\n\n# Estrutura\n- Comece com a conclusão principal.\n- Liste pontos-chave em tópicos curtos.\n- Separe fatos confirmados de inferências.",
    llm_tier: "fast",
    tool_ids: ["pia_accounts", "pia_resources"],
    presetId: "owl",
    avatar_colors: { ...COLOR_PRESETS[6].colors },
  },
];

export function validateClientSvg(rawText) {
  if (typeof rawText !== "string" || !rawText.trim()) {
    return { ok: false, error: "Arquivo SVG vazio." };
  }
  if (rawText.length > 256 * 1024) {
    return { ok: false, error: "O SVG excede o limite de 256 KiB." };
  }
  const lower = rawText.toLowerCase();
  if (!lower.includes("<svg")) {
    return { ok: false, error: "O arquivo precisa conter um elemento <svg>." };
  }
  if (
    /<script\b|<foreignobject\b|<!doctype|<!entity|\son[a-z]+\s*=/i.test(
      rawText,
    )
  ) {
    return {
      ok: false,
      error: "O SVG contém tags ou atributos de script não permitidos.",
    };
  }
  return { ok: true, error: null };
}

export function buildBotPayload(form, options = {}) {
  const payload = {
    name: String(form.name || "").trim(),
    description: String(form.description || "").trim(),
    instructions: String(form.instructions || ""),
    enabled: Boolean(form.enabled ?? true),
    speak_replies: Boolean(form.speak_replies ?? true),
    llm_tier: String(form.llm_tier || "free").trim() || "free",
    avatar_colors: {
      primary: form.avatar_colors?.primary || DEFAULT_BOT_COLORS.primary,
      accent: form.avatar_colors?.accent || DEFAULT_BOT_COLORS.accent,
      eyes: form.avatar_colors?.eyes || DEFAULT_BOT_COLORS.eyes,
    },
    tool_ids: Array.isArray(form.tool_ids) ? form.tool_ids : [],
    delegation_targets: Array.isArray(form.delegation_targets)
      ? form.delegation_targets
      : [],
    voice: form.voice
      ? {
          mode: form.voice.mode === "custom" ? "custom" : "inherit",
          profile:
            form.voice.mode === "custom" ? form.voice.profile || null : null,
          ...(form.voice.revision !== undefined
            ? { revision: form.voice.revision }
            : {}),
        }
      : { mode: "inherit", profile: null },
  };
  if (options.avatarId !== undefined) {
    payload.avatar_id = options.avatarId;
  } else if (form.avatar_id !== undefined) {
    payload.avatar_id = form.avatar_id;
  }
  if (options.isEdit && form.revision !== undefined) {
    payload.revision = form.revision;
  }
  return payload;
}
