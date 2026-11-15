import { api } from "./client";

export const mcpApi = {
  listServers: () => api("/mcp/servers"),
  getServer: (id) => api(`/mcp/servers/${encodeURIComponent(id)}`),
  createServer: (payload) => api("/mcp/servers", payload, { method: "POST" }),
  updateServer: (id, payload) =>
    api(`/mcp/servers/${encodeURIComponent(id)}`, payload, { method: "PUT" }),
  deleteServer: (id) =>
    api(`/mcp/servers/${encodeURIComponent(id)}`, {}, { method: "DELETE" }),
  getTools: (id) => api(`/mcp/servers/${encodeURIComponent(id)}/tools`),
  inspectServer: (id) =>
    api(
      `/mcp/servers/${encodeURIComponent(id)}/inspect`,
      {},
      { method: "POST" },
    ),
  startOAuth: (id, payload) =>
    api(`/mcp/servers/${encodeURIComponent(id)}/oauth/start`, payload, {
      method: "POST",
    }),
};

export const pluginsApi = {
  list: () => api("/plugins"),
  toggle: (id, enabled) =>
    api(`/plugins/${encodeURIComponent(id)}/toggle`, { enabled }),
};

export const skillsApi = {
  list: () => api("/skills"),
  create: (payload) => api("/skills", payload, { method: "POST" }),
  update: (id, payload) =>
    api(`/skills/${encodeURIComponent(id)}`, payload, { method: "PUT" }),
  toggle: (id, enabled) =>
    api(`/skills/${encodeURIComponent(id)}/toggle`, { enabled }),
  remove: (id) =>
    api(`/skills/${encodeURIComponent(id)}`, {}, { method: "DELETE" }),
  execute: (id, payload = {}) =>
    api(`/skills/${encodeURIComponent(id)}/execute`, payload, {
      method: "POST",
    }),
};
