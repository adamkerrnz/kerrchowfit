/* KerrChow Fit, self-hosted: stands in for the claude.ai runtime (window.claude) so index.html runs unchanged.
 * db          -> /api/db/*   (SQLite on the server; polled for changes so phone and desktop stay in sync)
 * mcp         -> /api/mcp/*  (Strava and Garmin answered by the server)
 * user        -> one owner who can edit (protect the site with the stack's login or your network)
 * permissions -> always granted
 */
(function () {
  "use strict";
  const POLL_MS = 20000;

  async function api(url, init) {
    const r = await fetch(url, Object.assign({ credentials: "same-origin", headers: { "Content-Type": "application/json" } }, init));
    if (!r.ok) {
      const err = new Error(`HTTP ${r.status}`);
      err.code = r.status === 401 || r.status === 403 ? "permission_denied" : "unavailable";
      throw err;
    }
    return r.json();
  }

  // ---------- live updates: every listener re-reads on a timer, when the tab returns, and after any local write ----------
  const listeners = new Set();
  let epoch = 0; // bumped by every local write, so a read that started before the write can't overwrite it
  const refreshAll = () => { epoch++; listeners.forEach((fn) => fn()); };
  const pollAll = () => listeners.forEach((fn) => fn());
  setInterval(() => { if (!document.hidden) pollAll(); }, POLL_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) pollAll(); });

  function watch(read, cb, onError) {
    let last = null, stopped = false;
    const tick = () => { const started = epoch; return read().then((snap) => {
      if (stopped || started !== epoch) return; // stale: a write landed while this read was in flight
      const key = JSON.stringify(snap.__key);
      if (key !== last) { last = key; cb(snap); }
    }, (e) => { if (!stopped && onError) onError(e); }); };
    listeners.add(tick);
    tick();
    return () => { stopped = true; listeners.delete(tick); };
  }

  // ---------- db ----------
  const q = (path) => `path=${encodeURIComponent(path)}`;
  function docRef(path) {
    const id = path.split("/").pop();
    const ref = {
      id, path,
      async get() {
        const r = await api(`/api/db/doc?${q(path)}`);
        return { id, ref, exists: !!r.exists, data: () => r.data, __key: [r.exists, r.data] };
      },
      async set(data) { await api(`/api/db/doc?${q(path)}`, { method: "PUT", body: JSON.stringify(data) }); refreshAll(); },
      async update(data) { await api(`/api/db/doc?${q(path)}`, { method: "PATCH", body: JSON.stringify(data) }); refreshAll(); },
      async delete() { await api(`/api/db/doc?${q(path)}`, { method: "DELETE" }); refreshAll(); },
      onSnapshot(cb, onError) { return watch(ref.get, cb, onError); },
    };
    return ref;
  }
  function collectionRef(path) {
    const ref = {
      id: path.split("/").pop(), path,
      doc: (id) => docRef(`${path}/${id}`),
      async get() {
        const r = await api(`/api/db/collection?${q(path)}`);
        const docs = r.docs.map((d) => ({ id: d.id, exists: true, ref: docRef(`${path}/${d.id}`), data: () => d.data }));
        return { docs, size: docs.length, empty: !docs.length, metadata: { fromCache: false }, __key: r.docs };
      },
      onSnapshot(cb, onError) { return watch(ref.get, cb, onError); },
    };
    return ref;
  }
  const db = Object.freeze({ doc: docRef, collection: collectionRef });

  // ---------- mcp ----------
  async function callTool(server, tool, input, options) {
    const refresh = !!(options && options.cache && options.cache.refresh);
    let r;
    try {
      r = await api("/api/mcp/call", { method: "POST", body: JSON.stringify({ server, tool, input: input ?? {}, refresh }) });
    } catch (e) {
      throw { code: "server_unavailable", server, message: `The KerrChow Fit server didn't answer (${e.message}).`, retryable: true, retryAfterMs: 3000 };
    }
    if (r.error) throw Object.assign({ server }, r.error);
    const result = { content: [{ type: "text", text: JSON.stringify(r.payload) }], payload: r.payload };
    if (r.storedAt) result.cache = { storedAt: r.storedAt, revalidating: false };
    return result;
  }
  async function listTools(server) {
    const r = await api("/api/mcp/servers");
    return { servers: server ? r.servers.filter((s) => s.server === server) : r.servers };
  }
  function watchTool(server, tool, input, handler, options) {
    let stopped = false;
    const run = () => callTool(server, tool, input).then(
      (result) => { if (!stopped) handler({ type: "data", result }); },
      (error) => { if (!stopped) handler({ type: "error", error }); });
    Promise.resolve().then(run);
    const every = options && options.refetchInterval ? Math.max(30000, options.refetchInterval) : 0;
    const timer = every ? setInterval(() => { if (!document.hidden) run(); }, every) : null;
    return () => { stopped = true; if (timer) clearInterval(timer); };
  }
  async function server(name) {
    const { servers } = await listTools(name);
    if (!servers.length) throw { code: "server_not_connected", server: name, message: `${name} isn't set up on this server.` };
    const handle = {};
    for (const t of servers[0].tools) handle[t.name] = (input, options) => callTool(name, t.name, input, options).then((r) => r.payload);
    return Object.freeze(handle);
  }
  const mcp = Object.freeze({
    callTool, listTools, watchTool, server,
    invalidate: async () => {},
    describeTool: async () => { throw { code: "bad_request", message: "No schemas on the self-hosted server." }; },
  });

  // ---------- user + permissions ----------
  const user = Object.freeze({
    isOwner: () => true, canEdit: () => true, can: () => true,
    id: async () => "owner", me: async () => ({ id: "owner", name: "", guest: false }),
    profiles: async () => ({}), search: async () => [],
  });
  const permissions = Object.freeze({
    state: async (name) => (typeof name === "string" ? "granted" : {}),
    request: async () => ({}),
    manage: async () => {},
  });

  const caps = { db, mcp, user, permissions };
  window.claude = Object.freeze({ use: (name) => Promise.resolve(caps[name] || null) });
})();
