"use client";

import { TriangleAlert } from "lucide-react";

/** Last-resort boundary: a crash inside a page shows this instead of a blank screen. */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="page-x grid min-h-[60dvh] place-items-center py-16">
      <div className="max-w-sm text-center">
        <span className="mx-auto mb-4 grid size-12 place-items-center rounded-xl bg-err-soft text-err"><TriangleAlert className="size-6" /></span>
        <h1 className="text-xl font-semibold tracking-tight">Something went wrong</h1>
        <p className="mt-1.5 text-sm text-muted">This page hit an unexpected problem. Your data is safe. Try again, and if it keeps happening tell an administrator.</p>
        {error.digest && <p className="mt-2 font-mono text-[11px] text-faint">Reference {error.digest}</p>}
        <button onClick={reset} className="btn mt-6 inline-flex h-9 items-center rounded-md bg-accent px-4 text-sm font-medium text-on-accent shadow-sm hover:bg-accent-strong">Try again</button>
      </div>
    </div>
  );
}
