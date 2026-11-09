"use client";

import { useEffect, useState } from "react";
import { Kbd, Modal } from "./ui";

const GROUPS: { title: string; rows: [string[], string][] }[] = [
  { title: "Anywhere", rows: [[["Ctrl", "K"], "Quick find: invoices, suppliers, numbers"], [["?"], "Show this cheat-sheet"], [["Esc"], "Close menus and dialogs"]] },
  { title: "Reviewing a record", rows: [[["J"], "Next record in the document"], [["K"], "Previous record"], [["Ctrl", "S"], "Save corrections and re-check"], [["Ctrl", "↵"], "Approve and go to the next item"]] },
];

/** Opens from the user card, or by pressing ? outside a text field. */
export function ShortcutsDialog() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const show = () => setOpen(true);
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key === "?" && !["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) && !t.isContentEditable) { e.preventDefault(); setOpen(true); }
    };
    window.addEventListener("open-shortcuts", show);
    window.addEventListener("keydown", key);
    return () => { window.removeEventListener("open-shortcuts", show); window.removeEventListener("keydown", key); };
  }, []);
  return (
    <Modal open={open} onClose={() => setOpen(false)} title="Keyboard shortcuts" description="Work through the review queue without leaving the keyboard.">
      <div className="space-y-5 pb-3">
        {GROUPS.map((g) => (
          <section key={g.title}>
            <h3 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-faint">{g.title}</h3>
            <dl className="divide-y divide-line rounded-lg border border-line">
              {g.rows.map(([keys, what]) => (
                <div key={what} className="flex items-center justify-between gap-4 px-3 py-2.5 text-sm">
                  <dt className="text-ink-2">{what}</dt>
                  <dd className="flex shrink-0 gap-1">{keys.map((k) => <Kbd key={k}>{k}</Kbd>)}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </Modal>
  );
}
