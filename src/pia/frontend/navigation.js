export class ScreenHistory {
  constructor(limit = 50, entries = []) {
    this.limit = limit;
    this.entries = entries.slice(-limit);
    this.index = this.entries.length - 1;
  }
  push(route) {
    const entry = {
      key: globalThis.crypto.randomUUID(),
      route: structuredClone(route),
    };
    this.entries = this.entries.slice(0, this.index + 1);
    this.entries.push(entry);
    this.entries = this.entries.slice(-this.limit);
    this.index = this.entries.length - 1;
    return entry;
  }
  select(key) {
    const index = this.entries.findIndex((entry) => entry.key === key);
    if (index >= 0) this.index = index;
    return this.entries[Math.max(0, this.index)];
  }
}
