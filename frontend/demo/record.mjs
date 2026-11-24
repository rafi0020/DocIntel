// Records the demo fixtures from a running stack.
//
//   cd frontend && node demo/record.mjs demo/record.config.mjs
//
// For every demo account it signs in through the real login form in a real browser, visits the pages and runs the
// journeys named in the config, and keeps each /api response (and each server-sent event stream) it saw. The result
// is demo/fixtures.json, which demo/runtime.js replays in the browser on the static GitHub Pages build.
import { createRequire } from "node:module";

// Playwright comes from this project's node_modules; PLAYWRIGHT_FROM (a path to any package.json that can resolve
// @playwright/test) is the fallback for a project that does not depend on it.
let chromium;
try { ({ chromium } = await import("@playwright/test")); }
catch { ({ chromium } = createRequire(process.env.PLAYWRIGHT_FROM)("@playwright/test")); }
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const configPath = path.resolve(process.argv[2] ?? "demo/record.config.mjs");
const config = (await import(pathToFileURL(configPath).href)).default;
const out = path.resolve(path.dirname(configPath), "fixtures.json");
const MAX_REPLAY_MS = 20_000;

/** Same normalisation as runtime.js, so recorded keys and replayed keys agree. */
function keyOf(urlString) {
  const url = new URL(urlString);
  const i = url.pathname.indexOf("/api/");
  if (i < 0) return null;
  const p = url.pathname.slice(i);
  const q = [...url.searchParams.entries()].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : 1)).map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
  return { path: p, key: q ? `${p}?${q}` : p };
}

const settle = async (page, ms = 900) => {
  await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(ms);
};

function newState() {
  return { routes: new Map(), writes: new Map(), sse: new Map(), sockets: [], bins: new Map(), login: null, t0: Date.now(), muted: false };
}

async function openContext(browser, state) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, baseURL: config.baseUrl });
  await context.exposeFunction("__demoSse", (u, t, type, data, id, done) => {
    const k = keyOf(new URL(u, config.baseUrl).href);
    if (!k) return;
    let rec = state.sse.get(k.path);
    if (!rec || t === 0) { rec = { events: [], first: Date.now() }; state.sse.set(k.path, rec); }
    if (!done) rec.events.push({ t, type, data, id });
  });
  await context.addInitScript(() => {
    const Native = window.EventSource;
    window.EventSource = class extends Native {
      constructor(u, o) {
        super(u, o);
        const t0 = Date.now();
        window.__demoSse(String(u), 0, "", "", "", true);
        const wrap = (type, fn) => (e) => { window.__demoSse(String(u), Date.now() - t0, type, e.data, e.lastEventId || "", false); fn.call(this, e); };
        const add = this.addEventListener.bind(this);
        this.addEventListener = (type, fn, opts) => add(type, wrap(type, fn), opts);
      }
    };
  });
  const page = await context.newPage();
  // WebSockets: keep the text frames (JSON messages) in order, with their timing. Binary audio frames are not kept.
  page.on("websocket", (socket) => {
    const k = keyOf(socket.url().replace(/^ws/, "http"));
    if (!k) return;
    const rec = { raw: k.path, path: k.path.replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g, "*"), t0: Date.now(), frames: [] };
    state.sockets.push(rec);
    const keep = (dir) => (e) => { if (typeof e.payload === "string") rec.frames.push({ dir, t: Date.now() - rec.t0, data: e.payload }); };
    socket.on("framesent", keep("s"));
    socket.on("framereceived", keep("r"));
  });
  page.on("response", async (res) => {
    const req = res.request();
    if (!["fetch", "xhr", "image", "document"].includes(req.resourceType())) return;
    const k = keyOf(res.url());
    if (!k) return;
    const contentType = res.headers()["content-type"] ?? "";
    if (contentType.includes("event-stream")) return;
    // Images and PDFs (page renders, thumbnails) are kept as they are, so the demo can show the same documents.
    if (/^(image\/|application\/pdf)/.test(contentType)) {
      const buf = await res.body().catch(() => null);
      if (buf && buf.length <= (config.maxBinaryBytes ?? 900_000) && res.status() === 200) state.bins.set(k.key, { type: contentType.split(";")[0], b64: buf.toString("base64") });
      return;
    }
    let text = "";
    try { text = await res.text(); } catch { return; }
    let body = null;
    if (text) { try { body = JSON.parse(text); } catch { return; } }
    const method = req.method();
    if (method === "GET") {
      if (state.muted) return;
      const list = state.routes.get(k.key) ?? [];
      list.push({ t: Date.now() - state.t0, status: res.status(), body });
      state.routes.set(k.key, list);
    } else {
      let reqBody = null;
      try { reqBody = req.postDataJSON(); } catch { reqBody = null; } // file uploads (multipart) are not kept
      if (k.path === config.loginApi) { state.login = { status: res.status(), body }; return; }
      const wk = `${method} ${k.path}`;
      const list = state.writes.get(wk) ?? [];
      list.push({ req: reqBody, status: res.status(), body });
      state.writes.set(wk, list);
    }
  });
  return { context, page };
}

async function signIn(page, state, [email, password]) {
  await page.goto(config.loginPath);
  await settle(page);
  await page.locator("input[type=email], input[name=email], #email").first().fill(email);
  const pw = page.locator("input[type=password]").first();
  await pw.fill(password);
  const done = page.waitForResponse((r) => r.url().includes(config.loginApi) && r.request().method() === "POST");
  await pw.press("Enter");
  const response = await done;
  if (response.status() >= 400) throw new Error(`sign-in failed for ${email}: ${response.status()}`);
  // The page navigates away as soon as this arrives, so read the body here rather than in the shared listener.
  state.login = { status: response.status(), body: await response.json().catch(() => null) };
  await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 15000 });
  await settle(page);
  // The sign-in response cannot be read once the page has navigated, so rebuild what the app uses from /api/auth/me.
  const me = await (await page.request.get(new URL(config.loginApi.replace(/login$/, "me"), config.apiBase ?? config.baseUrl).href)).json();
  state.login.body = { csrf_token: me.csrf_token, user: me.user };
}

/** Click through each tab and the first few table rows, so the detail views the page opens are recorded too. */
async function poke(page, target) {
  const tabs = page.locator('[role="tab"]');
  const tabCount = Math.min(await tabs.count(), 8);
  for (let i = 0; i < tabCount; i++) {
    await tabs.nth(i).click({ timeout: 2000 }).catch(() => {});
    await settle(page, 500);
  }
  const rowCount = Math.min(await page.locator("table tbody tr").count(), config.pokeRows ?? 3);
  for (let i = 0; i < rowCount; i++) {
    const before = page.url();
    await page.locator("table tbody tr").nth(i).locator("td").first().click({ timeout: 2000 }).catch(() => {});
    await settle(page, 700);
    if (page.url() !== before) { await page.goto(target).catch(() => {}); await settle(page, 500); }
    else await page.keyboard.press("Escape").catch(() => {});
  }
}

/** Open every handle in an Evidence table (a drawer or dialog) so each figure's detail is recorded. */
async function openEvidence(page) {
  const buttons = page.getByRole("table").last().getByRole("button");
  const n = Math.min(await buttons.count(), 30);
  for (let i = 0; i < n; i++) {
    await buttons.nth(i).click().catch(() => {});
    const dialog = page.getByRole("dialog");
    const opened = await dialog.waitFor({ timeout: 6000 }).then(() => true, () => false);
    await settle(page, 600);
    if (opened) {
      const close = dialog.getByRole("button", { name: "Close" });
      if (await close.count()) await close.first().click().catch(() => {}); else await page.keyboard.press("Escape");
    }
  }
}

/** Visit the start page, then every same-site link found on it, breadth first. */
async function crawl(page, start, max = config.crawlMax ?? 30) {
  const seen = new Set();
  const queue = [start, ...(config.crawlSeeds ?? [])];
  while (queue.length && seen.size < max) {
    const target = queue.shift();
    if (seen.has(target)) continue;
    seen.add(target);
    await page.goto(target).catch(() => {});
    await settle(page);
    if (config.poke) await poke(page, target);
    const hrefs = await page.$$eval("a[href]", (as) => as.map((a) => a.getAttribute("href")));
    for (const href of hrefs) {
      if (!href || !href.startsWith("/") || href.startsWith("//") || href.includes("#")) continue;
      if (/^\/(api|signup|logout)|\/login/.test(href)) continue;
      if (config.crawlSkip?.test(href)) continue;
      if (!seen.has(href) && !queue.includes(href)) queue.push(href);
    }
  }
  return [...seen];
}

function compact(state, user) {
  const routes = {};
  for (const [key, list] of state.routes) {
    const sequenced = config.sequence?.some((re) => re.test(key.split("?")[0]));
    if (sequenced && list.length > 1) {
      const seq = [];
      let last = "";
      for (const entry of list) {
        const sig = JSON.stringify(entry.body);
        if (sig === last) continue;
        last = sig;
        seq.push({ t: entry.t - list[0].t, status: entry.status, body: entry.body });
      }
      const span = seq[seq.length - 1].t;
      routes[key] = seq.length > 1 ? { seq: seq.slice(0, 60), scale: span > MAX_REPLAY_MS ? MAX_REPLAY_MS / span : 1 } : { status: seq[0].status, body: seq[0].body };
    } else {
      const entry = list[list.length - 1];
      routes[key] = { status: entry.status, body: entry.body };
    }
  }
  const writes = {};
  for (const [key, list] of state.writes) writes[key] = list.slice(-8);
  const sse = {};
  for (const [p, rec] of state.sse) {
    if (!rec.events.length) continue;
    const span = rec.events[rec.events.length - 1].t;
    sse[p] = { events: rec.events, scale: span > MAX_REPLAY_MS ? MAX_REPLAY_MS / span : 1 };
  }
  // Each recorded socket becomes a session: what the server said on connecting, then its reply to each message sent.
  const ws = {};
  for (const rec of state.sockets) {
    const parse = (f) => { try { return JSON.parse(f.data); } catch { return {}; } };
    const session = { id: rec.raw.split("/").pop(), open: [], turns: [], end: [] };
    let current = null;
    for (const f of rec.frames) {
      const m = parse(f);
      if (f.dir === "s") {
        if (m.type === "text") { current = { send: m.text, frames: [], t0: f.t }; session.turns.push(current); }
        else if (m.type === "end") { current = { frames: [], t0: f.t }; session.end = current.frames; }
        else current = current && current.send === undefined ? current : null;
      } else {
        const frame = { t: current ? f.t - current.t0 : f.t, data: f.data };
        (current ? current.frames : session.open).push(frame);
      }
    }
    if (session.turns.length) (ws[rec.path] = ws[rec.path] ?? { sessions: [] }).sessions.push(session);
  }
  const bin = {};
  for (const [key, value] of state.bins) bin[key] = value;
  return { password: user.password, label: user.label, login: state.login, routes, writes, sse, ws, bin };
}

// DEMO_ONLY=after: keep the existing fixtures and only run each account's `after` step, merging what it records.
const previous = process.env.DEMO_ONLY === "after" ? JSON.parse(fs.readFileSync(out, "utf8")) : null;
const fixtures = { meta: { project: config.project, recordedAt: new Date().toISOString() }, login: { path: config.loginApi, logout: config.logoutApi }, anon: { routes: {} }, users: {} };
// CHROME_PATH lets a machine without Playwright's own browsers use an installed Chrome.
const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});

// Signed-out pages (login screen, public settings).
{
  const state = newState();
  const { context, page } = await openContext(browser, state);
  await page.goto(config.loginPath);
  await settle(page);
  fixtures.anon.routes = compact(state, {}).routes;
  await context.close();
}

for (const user of config.users) {
  console.log(`recording ${user.email}`);
  const state = newState();
  const { context, page } = await openContext(browser, state);
  await signIn(page, state, [user.email, user.password]);
  const helpers = { settle: (ms) => settle(page, ms), mute: async (fn) => { state.muted = true; try { await fn(); } finally { state.muted = false; } }, crawl: (start, max) => crawl(page, start, max), openEvidence: () => openEvidence(page), state,
    // Fetch an image or PDF the pages did not happen to load, and keep it like any other recorded image.
    fetchBinary: async (apiPath) => {
      const res = await page.request.get(new URL(apiPath, config.apiBase ?? config.baseUrl).href);
      const type = (res.headers()["content-type"] ?? "").split(";")[0];
      const buf = await res.body();
      if (res.status() === 200 && /^(image\/|application\/pdf)/.test(type) && buf.length <= (config.maxBinaryBytes ?? 900_000)) state.bins.set(apiPath, { type, b64: buf.toString("base64") });
    },
    getJson: async (apiPath) => (await page.request.get(new URL(apiPath, config.apiBase ?? config.baseUrl).href)).json(), };
  const before = previous ? null : config.journeys?.[user.email];
  if (before) await before(page, helpers);
  if (!previous && !config.journeysOnly?.includes(user.email)) {
    const visited = await crawl(page, config.crawlStart);
    console.log(`  ${visited.length} pages`);
  }
  const after = config.after?.[user.email];
  if (after) await after(page, helpers);
  if (previous) {
    const kept = previous.users[user.email.toLowerCase()];
    for (const [key, value] of Object.entries(kept.bin ?? {})) if (typeof value === "string") kept.bin[key] = previous.bin[value];
    for (const [key, value] of state.bins) kept.bin[key] = value;
    fixtures.users[user.email.toLowerCase()] = kept;
  } else fixtures.users[user.email.toLowerCase()] = compact(state, user);
  await context.close();
}
await browser.close();

// The same page image is seen by every account: keep each one once, and let accounts point at it.
{
  const shared = {};
  const ids = new Map();
  for (const u of Object.values(fixtures.users)) {
    for (const [key, value] of Object.entries(u.bin ?? {})) {
      if (typeof value !== "object") continue;
      if (!ids.has(value.b64)) { ids.set(value.b64, `b${ids.size}`); shared[ids.get(value.b64)] = value; }
      u.bin[key] = ids.get(value.b64);
    }
  }
  fixtures.bin = shared;
  if (previous) { fixtures.anon = previous.anon; fixtures.meta = previous.meta; }
}

fs.writeFileSync(out, JSON.stringify(fixtures));
const size = fs.statSync(out).size;
console.log(`wrote ${out} (${(size / 1024).toFixed(0)} KB)`);
