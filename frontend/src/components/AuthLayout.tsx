import type { ReactNode } from "react";
import { Logo } from "./AppShell";

/** Sign-in and sign-up: a centred card on a quiet background. No marketing copy. */
export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center overflow-hidden bg-bg px-5 py-10">
      <div aria-hidden className="pointer-events-none absolute inset-0 opacity-[0.5] [background-image:radial-gradient(var(--color-line)_1px,transparent_1px)] [background-size:22px_22px] [mask-image:radial-gradient(ellipse_at_center,black_30%,transparent_75%)]" />
      <main className="enter relative w-full max-w-[400px]">
        <div className="mb-7 flex flex-col items-center gap-3 text-center">
          <Logo size={44} />
          <span className="text-[19px] font-semibold tracking-tight">DocIntel</span>
        </div>
        <div className="rounded-2xl border border-line bg-card p-7 shadow-[var(--shadow-lift)] sm:p-8">{children}</div>
      </main>
    </div>
  );
}
