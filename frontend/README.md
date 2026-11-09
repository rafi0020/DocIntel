# DocIntel web UI

Next.js 15 (App Router, static export), Tailwind CSS 4 and SWR. The UI talks to the API at `NEXT_PUBLIC_API_URL`
(default `http://localhost:8000`) and authenticates with an HttpOnly session cookie.

```bash
npm install
npm run dev       # http://localhost:3000
npm run build     # static site in ./out, served by nginx in docker-compose
npx tsc --noEmit && npx eslint src
```

## Routes

| Route | Screen | Access |
|---|---|---|
| `/login`, `/signup` | Sign in, create an account | public |
| `/` | Dashboard: KPIs, volumes, review outcomes, suppliers, issues, team activity | signed in |
| `/documents` | Documents: live processing progress, bulk actions, export | signed in |
| `/review` | Review queue; `/review?doc=<id>&rec=<id>` opens the review workspace | signed in |
| `/search` | Hybrid, keyword and semantic search with filters and export | signed in |
| `/compare` | Cross-verification of invoices against a ledger or another PDF | signed in |
| `/settings` | Profile, security, models and API (admin), system status | signed in |
| `/admin/users`, `/admin/audit` | User management, audit log | admin |

## Keyboard shortcuts

`Ctrl/⌘ K` quick find · `?` shortcut list · `J` / `K` next and previous record · `Ctrl S` save corrections ·
`Ctrl ↵` approve and continue.
