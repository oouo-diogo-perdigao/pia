// Estados finais do WorkProgress: a barra para de animar e ganha cor própria.
// `interrupted` vem do job do Suno (T4) quando a geração para no meio do lote.
export const FINAL_PROGRESS_STATES = ["completed", "error", "interrupted"];
const PROGRESS_COLORS = { error: "red", interrupted: "yellow" };

export function isFinalProgressState(state) {
  return FINAL_PROGRESS_STATES.includes(state);
}

export function progressColor(state) {
  return PROGRESS_COLORS[state] || "violet";
}
