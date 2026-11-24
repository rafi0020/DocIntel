// What to record for the DocIntel demo. Run with the stack up and the sample documents loaded:
//   docker compose up --build -d && python scripts/seed_demo.py
import path from "node:path";

const user = (role) => `${role}@docintel.demo`;
const PASSWORDS = { admin: "Admin#Demo2026", reviewer: "Reviewer#Demo2026", viewer: "Viewer#Demo2026" };
const UPLOAD = path.resolve("../samples/inv_003.jpg");

async function step(name, fn) {
  try { await fn(); } catch (e) { console.log(`  step "${name}" skipped: ${String(e.message).split("\n")[0]}`); }
}

export default {
  project: "docintel",
  baseUrl: process.env.DEMO_BASE_URL ?? "http://localhost:3000",
  apiBase: process.env.DEMO_API_URL ?? "http://localhost:8000",
  loginPath: "/login/",
  loginApi: "/api/auth/login",
  logoutApi: "/api/auth/logout",
  crawlStart: "/",
  crawlMax: 40,
  poke: true,
  pokeRows: 4,
  maxBinaryBytes: 1_800_000,
  users: [
    { email: user("reviewer"), password: PASSWORDS.reviewer, label: "Reviewer" },
    { email: user("admin"), password: PASSWORDS.admin, label: "Administrator" },
    { email: user("viewer"), password: PASSWORDS.viewer, label: "Viewer" },
  ],
  // After each account's pages, also keep every document's page images, so any document opens with its picture.
  after: Object.fromEntries(["reviewer", "admin", "viewer"].map((role) => [user(role), async (page, h) => {
    const list = await h.getJson("/api/documents?limit=200");
    for (const doc of list.documents ?? list.items ?? list) {
      for (let n = 1; n <= Math.min(doc.page_count ?? 1, 3); n++) await h.fetchBinary(`/api/documents/${doc.id}/pages/${n}/image`);
    }
  }])),
  journeys: {
    [user("reviewer")]: async (page, h) => {
      await step("upload a photo", async () => {
        await page.goto("/documents/");
        await h.settle(800);
        await page.getByRole("button", { name: /upload/i }).first().click({ timeout: 8000 });
        await page.getByLabel("Choose files to upload").setInputFiles(UPLOAD);
        await h.settle(12_000);
      });
      await step("cross-verify the invoices against the ledger", async () => {
        await page.goto("/compare/");
        await h.settle(800);
        await page.locator("select").nth(0).selectOption({ index: 1 });
        const ledger = await page.locator("select").nth(1).locator("option", { hasText: "ledger_ap_2026.csv" }).first().getAttribute("value");
        await page.locator("select").nth(1).selectOption(ledger);
        await page.getByRole("button", { name: /compare/i }).last().click({ timeout: 8000 });
        await h.settle(5000);
      });
      await step("search", async () => {
        await page.goto("/search/");
        await h.settle(800);
        await page.getByPlaceholder(/Try/).fill("hospital bed rental over 500");
        await h.settle(3000);
      });
    },
  },
};
