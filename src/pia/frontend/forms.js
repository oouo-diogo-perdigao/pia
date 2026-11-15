// Canonical comparison also notices returning a field to its original value.
export function fingerprint(value) {
  if (Array.isArray(value)) return "[" + value.map(fingerprint).join(",") + "]";
  if (value && typeof value === "object")
    return (
      "{" +
      Object.keys(value)
        .sort()
        .map((key) => JSON.stringify(key) + ":" + fingerprint(value[key]))
        .join(",") +
      "}"
    );
  return JSON.stringify(value);
}
export function formatTime(value) {
  const seconds = Math.max(0, Math.floor(Number(value) || 0));
  return [
    Math.floor(seconds / 3600),
    Math.floor(seconds / 60) % 60,
    seconds % 60,
  ]
    .map((n) => String(n).padStart(2, "0"))
    .join(":");
}
