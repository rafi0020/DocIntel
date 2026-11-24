/*
 * Demo runtime. Injected into the GitHub Pages build only; the real deployment never loads it.
 *
 * The page talks to the same /api/... URLs it always does. This script answers those requests in the browser
 * from fixtures.json, which was recorded from the real system (API, database, worker and model) by record.mjs.
 * Sign-in is checked against the recorded demo accounts, runs and events are replayed with their original
 * timing, and anything that would change data is acknowledged but not stored.
 */
(function () {
  "use strict";
  var cfg = window.__DEMO__ || {};
  var BASE = cfg.base || "";
  var USER_KEY = "demo.user";
  var realFetch = window.fetch.bind(window);
  var fixtures = null;
  // The fixtures are one file; if the host hiccups (a 503 now and then), try again rather than leave the page dead.
  function load(attempt) {
    return realFetch(BASE + "/demo/fixtures.json").then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).catch(function (e) {
      if (attempt >= 5) throw e;
      return new Promise(function (done) { setTimeout(done, 400 * (attempt + 1)); }).then(function () { return load(attempt + 1); });
    });
  }
  var ready = load(0).then(function (f) { fixtures = f; return f; });
  var seqStart = {};

  function store(get, set) {
    try { return get ? localStorage.getItem(USER_KEY) : set === null ? localStorage.removeItem(USER_KEY) : localStorage.setItem(USER_KEY, set); } catch (e) { return null; }
  }
  function currentUser() { var u = store(true); return u && fixtures.users[u] ? u : null; }

  /** "/x/api/runs?b=2&a=1" -> {path: "/api/runs", key: "/api/runs?a=1&b=2"}; null when it is not an API call. */
  function parse(input) {
    var url;
    try { url = new URL(typeof input === "string" ? input : input.url, location.href); } catch (e) { return null; }
    var i = url.pathname.indexOf("/api/");
    if (i < 0) return null;
    var path = url.pathname.slice(i);
    var params = Array.from(url.searchParams.entries()).sort(function (a, b) { return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : 1; });
    var query = params.map(function (p) { return encodeURIComponent(p[0]) + "=" + encodeURIComponent(p[1]); }).join("&");
    return { path: path, key: query ? path + "?" + query : path };
  }

  function respond(status, body, extra) {
    var headers = { "Content-Type": "application/json" };
    if (extra) for (var k in extra) headers[k] = extra[k];
    if (status === 204 || status === 205) return new Response(null, { status: status });
    return new Response(JSON.stringify(body === undefined ? null : body), { status: status, headers: headers });
  }
  function delay(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  /** A recorded GET may be one body or a timeline of bodies (a run that was still working when first read).
      If the recording also holds an action on the same item (an "investigate" button), the timeline starts when
      the visitor takes that action, and the first state is shown until then. */
  var armedAt = {};
  function relatedWrite(path) {
    var scopes = sources();
    for (var i = 0; i < scopes.length; i++) {
      var writes = scopes[i].writes || {};
      for (var k in writes) { var p = k.slice(k.indexOf(" ") + 1); if (p === path || p.indexOf(path + "/") === 0) return true; }
    }
    return false;
  }
  function arm(path) {
    var parts = path.split("/");
    for (var n = parts.length; n > 2; n--) armedAt[parts.slice(0, n).join("/")] = Date.now();
  }
  function pick(entry, id, path) {
    if (!entry) return null;
    if (!entry.seq) return entry;
    var start;
    if (relatedWrite(path)) { start = armedAt[path]; if (!start) return entry.seq[0]; }
    else { if (!seqStart[id]) seqStart[id] = Date.now(); start = seqStart[id]; }
    var elapsed = (Date.now() - start) / (entry.scale || 1) + (armedAt[path] ? 3000 : 0); // head start: the page refreshes on the run's last event
    var chosen = entry.seq[0];
    for (var i = 0; i < entry.seq.length; i++) if (entry.seq[i].t <= elapsed) chosen = entry.seq[i];
    return chosen;
  }

  function tokens(value) {
    return String(typeof value === "string" ? value : JSON.stringify(value || "")).toLowerCase().match(/[a-z0-9]{3,}/g) || [];
  }
  function similarity(a, b) {
    var ta = tokens(a), tb = tokens(b);
    if (!ta.length || !tb.length) return 0;
    var set = {}; tb.forEach(function (t) { set[t] = 1; });
    var hit = ta.filter(function (t) { return set[t]; }).length;
    return hit / Math.max(ta.length, tb.length);
  }
  function counter(name) {
    var n = 0;
    try { n = Number(sessionStorage.getItem("demo.n." + name) || 0); sessionStorage.setItem("demo.n." + name, String(n + 1)); } catch (e) {}
    return n;
  }
  /** The recorded write that best matches what was sent; equally good matches are used in turn, so asking again gives the next one. */
  function bestWrite(list, body, id) {
    var scored = list.map(function (w) { return { w: w, s: JSON.stringify(w.req) === JSON.stringify(body) ? 2 : similarity(w.req, body) }; });
    var top = Math.max.apply(null, scored.map(function (x) { return x.s; }));
    var ties = scored.filter(function (x) { return x.s === top; });
    return ties[counter(id) % ties.length].w;
  }

  /** Recorded images and PDFs, as blobs. */
  var blobs = {};
  function binary(req) {
    var scopes = sources();
    for (var i = 0; i < scopes.length; i++) {
      var bin = scopes[i].bin || {};
      var hit = bin[req.key] || bin[req.path];
      if (typeof hit === "string") hit = (fixtures.bin || {})[hit];
      if (hit) {
        var id = (currentUser() || "anon") + req.key;
        if (!blobs[id]) {
          var raw = atob(hit.b64), bytes = new Uint8Array(raw.length);
          for (var j = 0; j < raw.length; j++) bytes[j] = raw.charCodeAt(j);
          blobs[id] = new Blob([bytes], { type: hit.type });
        }
        return blobs[id];
      }
    }
    return null;
  }

  /** A key without its volatile parameters (timestamps change on every load), so "last 24 hours" still finds its recording. */
  function alias(key) {
    var i = key.indexOf("?");
    if (i < 0) return key;
    var kept = key.slice(i + 1).split("&").filter(function (p) {
      var v = decodeURIComponent(p.split("=")[1] || "");
      return !/^\d{4}-\d{2}-\d{2}T\d|^\d{10,13}$/.test(v);
    });
    return kept.length ? key.slice(0, i) + "?" + kept.join("&") : key.slice(0, i);
  }
  function lookup(scope, key, path) {
    var routes = scope.routes || {};
    if (routes[key]) return routes[key];
    if (!scope._alias) { scope._alias = {}; Object.keys(routes).forEach(function (k) { scope._alias[alias(k)] = routes[k]; }); }
    return scope._alias[alias(key)] || routes[path] || scope._alias[path] || null;
  }

  function sources() {
    var u = currentUser();
    return u ? [fixtures.users[u], fixtures.anon] : [fixtures.anon];
  }

  async function handle(method, req, init, input) {
    await ready;
    var login = fixtures.login || {};
    var body = null;
    if (init && typeof init.body === "string") { try { body = JSON.parse(init.body); } catch (e) { body = init.body; } }
    else if (input && typeof input !== "string" && input.clone && method !== "GET") { try { body = await input.clone().json(); } catch (e) { body = null; } }

    if (method === "POST" && req.path === login.path) {
      var email = String((body && (body.email || body.username)) || "").trim().toLowerCase();
      var account = fixtures.users[email];
      await delay(250);
      if (account && body && body.password === account.password) { store(false, email); return respond(account.login.status, account.login.body); }
      return respond(401, { detail: "Incorrect e-mail or password." });
    }
    if (method === "POST" && req.path === login.logout) { store(false, null); return respond(204); }
    if (req.path.indexOf("/auth/signup") > 0 && method === "POST") return respond(403, { detail: "Sign-up is turned off in the demo. Use one of the demo accounts." });

    await delay(40 + Math.random() * 60);
    var scopes = sources();

    if (method === "GET" || method === "HEAD") {
      var blob = binary(req);
      if (blob) return new Response(blob, { status: 200, headers: { "Content-Type": blob.type } });
      for (var i = 0; i < scopes.length; i++) {
        var hit = lookup(scopes[i], req.key, req.path);
        if (hit) { var chosen = pick(hit, (currentUser() || "anon") + req.key, req.path); return respond(chosen.status, chosen.body); }
      }
      // Not recorded for this account: another account's recording of the same page is better than nothing,
      // except for anything about who is signed in.
      if (currentUser() && req.path.indexOf("/auth/") < 0) {
        var names = Object.keys(fixtures.users);
        for (var n = 0; n < names.length; n++) {
          var other = lookup(fixtures.users[names[n]], req.key, req.path);
          if (other) { var picked = pick(other, names[n] + req.key, req.path); return respond(picked.status, picked.body); }
        }
      }
      if (!currentUser() && req.path.indexOf("/auth/") < 0) return respond(401, { detail: "Not signed in." });
      if (req.path.indexOf("/auth/me") > 0) return respond(401, { detail: "Not signed in." });
      console.warn("demo: not recorded", method, req.key);
      return respond(404, { detail: "That is not part of the recorded demo." });
    }

    arm(req.path);
    // An action recorded under one account (a call placed by the agent) also works for the others.
    var everyone = scopes.concat(Object.keys(fixtures.users).map(function (k) { return fixtures.users[k]; }));
    for (var j = 0; j < everyone.length; j++) {
      var list = (everyone[j].writes || {})[method + " " + req.path];
      if (list && list.length) { var w = bestWrite(list, body, method + req.path); return respond(w.status, w.body); }
    }
    if (!currentUser()) return respond(401, { detail: "Not signed in." });
    console.warn("demo: not recorded", method, req.path);
    return respond(200, { ok: true, demo: true });
  }

  window.fetch = function (input, init) {
    var req = parse(input);
    if (!req) return realFetch(input, init);
    var method = String((init && init.method) || (input && input.method) || "GET").toUpperCase();
    return handle(method, req, init, input);
  };

  /** Server-sent events: replay the recorded stream for the same path, at the pace it was recorded. */
  function DemoEventSource(url) {
    var self = this;
    this.url = String(url);
    this.readyState = 0;
    this.withCredentials = true;
    this.onopen = this.onmessage = this.onerror = null;
    this._listeners = {};
    this._timers = [];
    ready.then(function () {
      if (self.readyState === 2) return;
      var req = parse(self.url);
      var rec = null;
      var scopes = sources();
      var all = Object.keys(fixtures.users).map(function (k) { return fixtures.users[k]; });
      scopes.concat(all).forEach(function (s) { if (!rec && req && s.sse && s.sse[req.path]) rec = s.sse[req.path]; });
      self.readyState = 1;
      if (self.onopen) self.onopen(new Event("open"));
      if (!rec) return;
      rec.events.forEach(function (ev) {
        self._timers.push(setTimeout(function () {
          if (self.readyState === 2) return;
          self._emit(ev.type || "message", ev.data, ev.id);
        }, Math.round(ev.t * (rec.scale || 1))));
      });
    });
  }
  DemoEventSource.CONNECTING = 0; DemoEventSource.OPEN = 1; DemoEventSource.CLOSED = 2;
  DemoEventSource.prototype.addEventListener = function (type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); };
  DemoEventSource.prototype.removeEventListener = function (type, fn) { this._listeners[type] = (this._listeners[type] || []).filter(function (f) { return f !== fn; }); };
  DemoEventSource.prototype._emit = function (type, data, id) {
    var event = new MessageEvent(type, { data: data, lastEventId: id || "" });
    (this._listeners[type] || []).slice().forEach(function (fn) { fn.call(this, event); }, this);
    if (type === "message" && this.onmessage) this.onmessage(event);
  };
  DemoEventSource.prototype.close = function () { this.readyState = 2; this._timers.forEach(clearTimeout); };
  window.EventSource = DemoEventSource;

  /* XMLHttpRequest: only used for uploads with a progress bar. Pretend the upload ran, then answer as recorded. */
  var xhrOpen = XMLHttpRequest.prototype.open, xhrSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    var req = parse(String(url));
    this.__demo = req ? { method: String(method).toUpperCase(), req: req } : null;
    return xhrOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function (body) {
    var d = this.__demo;
    if (!d) return xhrSend.apply(this, arguments);
    var xhr = this;
    function set(key, value) { Object.defineProperty(xhr, key, { value: value, configurable: true }); }
    for (var i = 1; i <= 5; i++) (function (n) {
      setTimeout(function () {
        var e = new ProgressEvent("progress", { lengthComputable: true, loaded: n, total: 5 });
        if (xhr.upload && xhr.upload.onprogress) xhr.upload.onprogress(e);
      }, n * 150);
    })(i);
    setTimeout(function () {
      handle(d.method, d.req, {}, null).then(function (res) {
        return res.text().then(function (text) {
          set("readyState", 4); set("status", res.status); set("responseText", text); set("response", text);
          if (xhr.onreadystatechange) xhr.onreadystatechange(new Event("readystatechange"));
          if (xhr.onload) xhr.onload(new ProgressEvent("load"));
          if (xhr.onloadend) xhr.onloadend(new ProgressEvent("loadend"));
        });
      });
    }, 900);
  };

  /* <img src="/api/..."> does not go through fetch: swap in the recorded image once the fixtures are loaded. */
  var setAttr = Element.prototype.setAttribute;
  function swapImage(el, value, assign) {
    var req = parse(String(value));
    if (!req) { assign(value); return; }
    assign("data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7");
    ready.then(function () { var blob = binary(req); if (blob) assign(URL.createObjectURL(blob)); else console.warn("demo: not recorded", "image", req.key); });
  }
  Element.prototype.setAttribute = function (name, value) {
    if (this.tagName === "IMG" && String(name).toLowerCase() === "src") return swapImage(this, value, setAttr.bind(this, "src"));
    return setAttr.call(this, name, value);
  };
  var srcProp = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src");
  if (srcProp && srcProp.set) {
    Object.defineProperty(HTMLImageElement.prototype, "src", {
      configurable: true, enumerable: srcProp.enumerable, get: srcProp.get,
      set: function (value) { swapImage(this, value, function (v) { srcProp.set.call(this, v); }.bind(this)); },
    });
  }

  /* WebSocket: replay a recorded call. What the server said on connecting is sent at once; each message the page
     sends is answered with the recorded reply to the most similar message sent in that call. */
  function DemoWebSocket(url) {
    var self = this;
    this.url = String(url);
    this.readyState = 0;
    this.binaryType = "blob";
    this.onopen = this.onmessage = this.onclose = this.onerror = null;
    this._l = {};
    this._timers = [];
    this._used = {};
    ready.then(function () {
      var req = parse(self.url.replace(/^ws/, "http"));
      var general = req && req.path.replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g, "*");
      var rec = null;
      var scopes = sources().concat(Object.keys(fixtures.users).map(function (k) { return fixtures.users[k]; }));
      scopes.forEach(function (s) { if (!rec && general && s.ws && s.ws[general]) rec = s.ws[general]; });
      if (!rec) { self._close(1006); return; }
      var count = 0;
      try { count = Number(sessionStorage.getItem("demo.calls") || 0); sessionStorage.setItem("demo.calls", String(count + 1)); } catch (e) {}
      var wanted = req.path.split("/").pop();
      self._session = rec.sessions.filter(function (s) { return s.id === wanted; })[0] || rec.sessions[count % rec.sessions.length];
      self.readyState = 1;
      self._fire("open", new Event("open"));
      self._play(self._session.open, 0);
    });
  }
  DemoWebSocket.CONNECTING = 0; DemoWebSocket.OPEN = 1; DemoWebSocket.CLOSING = 2; DemoWebSocket.CLOSED = 3;
  DemoWebSocket.prototype.OPEN = 1;
  DemoWebSocket.prototype.addEventListener = function (type, fn) { (this._l[type] = this._l[type] || []).push(fn); };
  DemoWebSocket.prototype.removeEventListener = function (type, fn) { this._l[type] = (this._l[type] || []).filter(function (f) { return f !== fn; }); };
  DemoWebSocket.prototype._fire = function (type, event) {
    (this._l[type] || []).slice().forEach(function (fn) { fn.call(this, event); }, this);
    var handler = this["on" + type];
    if (handler) handler.call(this, event);
  };
  DemoWebSocket.prototype._play = function (frames, offset) {
    var self = this;
    var last = 0;
    (frames || []).forEach(function (f) {
      last = Math.min(f.t, last + 1500);
      self._timers.push(setTimeout(function () {
        if (self.readyState === 1) self._fire("message", new MessageEvent("message", { data: f.data }));
      }, (offset || 0) + last));
    });
    return last;
  };
  DemoWebSocket.prototype.send = function (data) {
    if (this.readyState !== 1 || typeof data !== "string" || !this._session) return;
    var msg;
    try { msg = JSON.parse(data); } catch (e) { return; }
    if (msg.type === "text") {
      var turns = this._session.turns, best = -1, score = -1, i;
      for (i = 0; i < turns.length; i++) { var s = this._used[i] ? -0.5 : similarity(turns[i].send, msg.text); if (s > score) { score = s; best = i; } }
      if (score < 0.15) for (i = 0; i < turns.length; i++) if (!this._used[i]) { best = i; break; }
      this._used[best] = true;
      this._play(turns[best].frames, 250);
    } else if (msg.type === "end") {
      var self = this, span = this._play(this._session.end, 100);
      this._timers.push(setTimeout(function () { self._close(1000); }, span + 400));
    }
  };
  DemoWebSocket.prototype._close = function (code) {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this._timers.forEach(clearTimeout);
    this._fire("close", new CloseEvent("close", { code: code || 1000 }));
  };
  DemoWebSocket.prototype.close = function () { this._close(1000); };
  var RealWebSocket = window.WebSocket;
  window.WebSocket = function (url, protocols) {
    var p = parse(String(url).replace(/^ws/, "http"));
    return p && p.path.indexOf("/api/") === 0 ? new DemoWebSocket(url) : new RealWebSocket(url, protocols);
  };
  window.WebSocket.CONNECTING = 0; window.WebSocket.OPEN = 1; window.WebSocket.CLOSING = 2; window.WebSocket.CLOSED = 3;

  /* ---- the pages link to "/ask/" and similar; on Pages the site lives under /<repository>/, so add that prefix ---- */
  function fixLinks() {
    if (!BASE) return;
    var links = document.querySelectorAll('a[href^="/"]');
    for (var i = 0; i < links.length; i++) {
      var h = links[i].getAttribute("href");
      if (h.indexOf("//") !== 0 && h !== BASE && h.indexOf(BASE + "/") !== 0) links[i].setAttribute("href", BASE + h);
    }
  }
  function watchLinks() {
    fixLinks();
    new MutationObserver(fixLinks).observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ["href"] });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", watchLinks); else watchLinks();

  /* Voice cannot be replayed (nothing recognises speech), so a demo of a voice product keeps the microphone off. */
  if (cfg.noMic && navigator.mediaDevices) {
    navigator.mediaDevices.getUserMedia = function () { return Promise.reject(new DOMException("The microphone is off in the demo.", "NotAllowedError")); };
  }

  /* ---- a small, dismissible note so nobody mistakes the demo for a live deployment ---- */
  function note() {
    if (document.getElementById("demo-note")) return;
    var box = document.createElement("div");
    box.id = "demo-note";
    box.setAttribute("role", "note");
    box.style.cssText = "position:fixed;left:12px;bottom:12px;z-index:2147483000;max-width:min(360px,calc(100vw - 24px));font:12px/1.45 system-ui,sans-serif;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:10px;padding:9px 30px 9px 12px;box-shadow:0 6px 24px rgba(0,0,0,.35)";
    var text = document.createElement("span");
    text.textContent = (cfg.title || "This") + " demo replays data recorded from the running system. Changes are not saved. " + (cfg.extra ? cfg.extra + " " : "");
    var link = document.createElement("a");
    link.href = cfg.repo || "#"; link.target = "_blank"; link.rel = "noopener";
    link.textContent = "Source on GitHub";
    link.style.cssText = "color:#7dd3fc;text-decoration:underline";
    var close = document.createElement("button");
    close.type = "button"; close.setAttribute("aria-label", "Dismiss"); close.textContent = "×";
    close.style.cssText = "position:absolute;top:4px;right:6px;border:0;background:transparent;color:#94a3b8;font-size:18px;cursor:pointer;line-height:1";
    close.onclick = function () { box.remove(); try { sessionStorage.setItem("demo.note", "off"); } catch (e) {} };
    box.appendChild(text); box.appendChild(link); box.appendChild(close);
    document.body.appendChild(box);
  }
  function start() { try { if (sessionStorage.getItem("demo.note") === "off") return; } catch (e) {} note(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
