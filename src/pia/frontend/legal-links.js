export const DEFAULT_LEGAL_SERVER = "https://pia.travelrpg.com";
export const LEGAL_PAGES = ["privacidade", "termos"];

function httpsBase(server) {
  if (typeof server !== "string" || !server.trim()) return null;
  let url;
  try {
    url = new URL(server.trim());
  } catch {
    return null;
  }
  if (url.protocol !== "https:" || !url.hostname) return null;
  return url.origin;
}

export function legalServer(...candidates) {
  for (const candidate of candidates) {
    const base = httpsBase(candidate);
    if (base) return base;
  }
  return DEFAULT_LEGAL_SERVER;
}

export function legalUrl(server, page) {
  if (!LEGAL_PAGES.includes(page))
    throw new Error("Página legal desconhecida: " + page);
  return legalServer(server) + "/" + page;
}

export function legalLinks(...candidates) {
  const base = legalServer(...candidates);
  return {
    privacidade: legalUrl(base, "privacidade"),
    termos: legalUrl(base, "termos"),
  };
}
