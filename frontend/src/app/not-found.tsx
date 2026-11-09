import { Compass } from "lucide-react";
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="page-x grid min-h-[60dvh] place-items-center py-16">
      <div className="max-w-sm text-center">
        <span className="mx-auto mb-4 grid size-12 place-items-center rounded-xl bg-surface text-muted"><Compass className="size-6" /></span>
        <h1 className="text-xl font-semibold tracking-tight">Page not found</h1>
        <p className="mt-1.5 text-sm text-muted">The page you are looking for does not exist or has moved.</p>
        <Link href="/" className="btn mt-6 inline-flex h-9 items-center rounded-md bg-accent px-4 text-sm font-medium text-on-accent shadow-sm hover:bg-accent-strong">Back to dashboard</Link>
      </div>
    </div>
  );
}
