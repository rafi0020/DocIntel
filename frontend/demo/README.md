# DocIntel: demo build

The GitHub Pages site at https://rafi0020.github.io/DocIntel/ is the real web interface of this project with its API answered in the browser
from recorded responses. It is a demonstration, not a deployment: there is no server, database or model behind it.

| File | Purpose |
|---|---|
| `fixtures.json` | Every API response and event stream recorded from the running system, per demo account |
| `runtime.js` | Loaded first on each page; answers `/api/...` requests and event streams from `fixtures.json` |
| `inject.mjs` | Adds `runtime.js` and the fixtures to the static export (run by the Pages workflow) |
| `record.mjs`, `record.config.mjs` | Records `fixtures.json` from a running stack |
| `demo.json` | Site address and name used by the demo note |

What the demo does: signing in checks the recorded demo accounts; pages show what the system returned when it was
recorded; a run replays at the pace it ran, with the real model's trail, answer and evidence; actions that would change
data are acknowledged and not stored. A small note on every page says so.

## Recording again

With the stack running (see the main README, including a model if the project uses one):

```bash
cd frontend
npm ci
node demo/record.mjs demo/record.config.mjs      # set CHROME_PATH to use an installed Chrome
```

Review `fixtures.json` before committing it: it holds everything the demo shows. It should contain no keys or other
secrets; the recorder keeps only responses the web interface itself received.

## Building locally

```bash
cd frontend
NEXT_PUBLIC_BASE_PATH=/DocIntel NEXT_PUBLIC_API_URL=https://rafi0020.github.io/DocIntel npm run build
node demo/inject.mjs
```

Serve `out/` below `/DocIntel/` to try it. The architecture diagram is added at `/diagram/` by the workflow and is
linked from the README only; the application does not link to it.
