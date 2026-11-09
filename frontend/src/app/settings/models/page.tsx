"use client";

import clsx from "clsx";
import { AlertTriangle, CheckCircle2, ChevronDown, Cpu, Eye, EyeOff, RotateCcw, ShieldCheck, XCircle, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Badge, Button, Card, ConfirmDialog, Field, Skeleton, useToast } from "@/components/ui";
import { api, fetcher, json, type ModelsConfig, type ModelsForm, type PingResult } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtAgo } from "@/lib/format";

const LABEL: Record<string, string> = { anthropic: "Anthropic (Claude)", gemini: "Google Gemini", groq: "Groq", openai: "OpenAI", ollama: "Ollama (local)", openai_compatible: "OpenAI-compatible gateway" };

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)}
      className={clsx("btn relative h-6 w-11 shrink-0 rounded-full transition-colors", checked ? "bg-accent" : "bg-line-strong")}>
      <span className={clsx("absolute top-0.5 size-5 rounded-full bg-card shadow transition-all", checked ? "left-[22px]" : "left-0.5")} />
    </button>
  );
}

function toForm(c: ModelsConfig): ModelsForm {
  return { enabled: c.enabled, provider: c.provider, model: c.model ?? "", base_url: c.base_url ?? "", api_key: "", clear_key: false, timeout_s: c.timeout_s, max_retries: c.max_retries,
    temperature: c.temperature, max_chars: c.max_chars, concurrency: c.concurrency, json_mode: c.json_mode, ocr_engine: c.ocr_engine };
}
const payload = (f: ModelsForm) => ({ ...f, api_key: f.api_key.trim() || undefined, model: f.model.trim() || null, base_url: f.base_url.trim() || null,
  timeout_s: +f.timeout_s, max_retries: +f.max_retries, temperature: +f.temperature, max_chars: +f.max_chars, concurrency: +f.concurrency });

export default function ModelsPage() {
  const { can } = useAuth();
  const toast = useToast();
  const { data: cfg, mutate } = useSWR<ModelsConfig>(can("admin") ? "/api/settings/models" : null, fetcher, { revalidateOnFocus: false });
  const [f, setF] = useState<ModelsForm | null>(null);
  const [showKey, setShowKey] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState<"" | "save" | "test" | "reset">("");
  const [test, setTest] = useState<{ sig: string; res: PingResult } | null>(null);
  const [warn, setWarn] = useState(false);
  const [resetting, setResetting] = useState(false);

  useEffect(() => { if (cfg) setF(toForm(cfg)); }, [cfg?.updated_at, cfg?.source]); // eslint-disable-line react-hooks/exhaustive-deps
  const preset = useMemo(() => cfg?.providers.find((p) => p.id === f?.provider), [cfg, f?.provider]);
  const sig = f ? JSON.stringify(payload(f)) : "";
  const dirty = !!(cfg && f && JSON.stringify(payload(toForm(cfg))) !== sig);

  if (!can("admin")) return <Card className="p-8 text-center text-sm text-muted">Only administrators can change model and API settings. The active model is shown in the status panel.</Card>;
  if (!cfg || !f) return <div className="space-y-4"><Skeleton className="h-48" /><Skeleton className="h-64" /></div>;
  const set = <K extends keyof ModelsForm>(k: K, v: ModelsForm[K]) => setF({ ...f, [k]: v });
  const pickProvider = (id: string) => {
    // a built-in provider brings its own URL and model; a generic gateway keeps whatever is already typed
    const next = cfg.providers.find((p) => p.id === id);
    setF({ ...f, provider: id, base_url: next?.base_url ?? f.base_url, model: next?.model ?? f.model });
  };
  const keyShown = f.clear_key ? "removed" : cfg.key_set ? cfg.key_hint : null;

  async function runTest() {
    setBusy("test");
    try { const res = await api<PingResult>("/api/settings/models/test", { method: "POST", ...json(payload(f!)) }); setTest({ sig, res }); }
    catch (e) { setTest({ sig, res: { ok: false, error: (e as Error).message } }); } finally { setBusy(""); }
  }
  async function save(force = false) {
    if (!force && test && test.sig === sig && test.res.ok === false) { setWarn(true); return; }
    setBusy("save"); setWarn(false);
    try { const v = await api<ModelsConfig>("/api/settings/models", { method: "PUT", ...json(payload(f!)) }); await mutate(v, { revalidate: false }); setF(toForm(v)); toast("ok", "Saved. It applies to the next document."); }
    catch (e) { toast("err", (e as Error).message); } finally { setBusy(""); }
  }
  async function reset() {
    setBusy("reset");
    try { const v = await api<ModelsConfig>("/api/settings/models", { method: "DELETE" }); await mutate(v, { revalidate: false }); setF(toForm(v)); setTest(null); toast("ok", "Back to the .env defaults"); }
    catch (e) { toast("err", (e as Error).message); } finally { setBusy(""); setResetting(false); }
  }
  const t = test && test.sig === sig ? test.res : null;

  return (
    <div className="space-y-5 pb-24">
      <Card className="flex flex-wrap items-center gap-4 p-5">
        <span className={clsx("grid size-11 place-items-center rounded-xl", cfg.enabled ? "bg-accent-soft text-accent" : "bg-surface text-muted")}><Cpu className="size-5" /></span>
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-[15px] font-semibold">{cfg.enabled ? <>{LABEL[cfg.provider] ?? cfg.provider}<span className="font-normal text-muted max-sm:hidden">·</span><span className="break-all font-mono text-[13px] font-normal">{cfg.model ?? preset?.model}</span></> : "Rule engine only"}
            <Badge tone={cfg.enabled ? "ok" : "muted"} dot>{cfg.enabled ? "AI model active" : "No model"}</Badge></p>
          <p className="mt-0.5 text-[12.5px] text-muted">{cfg.source === "ui" ? `Saved in the app${cfg.updated_by ? ` by ${cfg.updated_by}` : ""}${cfg.updated_at ? `, ${fmtAgo(cfg.updated_at)}` : ""}.` : "Using the defaults from the server's .env file. Save to override them here."}</p>
        </div>
      </Card>

      <Card className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div><h2 className="text-[15px] font-semibold">AI model for extraction</h2><p className="mt-1 max-w-xl text-[13px] text-muted">When on, an AI model reads every invoice alongside the rule engine. A value is kept only if it can be found on the page, so a wrong answer cannot invent data. When off, only the rule engine runs, which is faster and needs no key.</p></div>
          <Toggle checked={f.enabled} onChange={(v) => set("enabled", v)} label="Use an AI model" />
        </div>

        <div className={clsx("mt-6 grid gap-4 sm:grid-cols-2", !f.enabled && "pointer-events-none opacity-50")} aria-disabled={!f.enabled}>
          <Field label="Provider">
            <select className="field" value={f.provider} onChange={(e) => pickProvider(e.target.value)}>{cfg.providers.map((p) => <option key={p.id} value={p.id}>{LABEL[p.id] ?? p.id}</option>)}</select>
          </Field>
          <Field label="Model" hint={preset?.model ? `Suggested: ${preset.model}` : "The model name your gateway expects."}>
            <input className="field font-mono" value={f.model} onChange={(e) => set("model", e.target.value)} placeholder={preset?.model ?? "model-name"} spellCheck={false} />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Base URL" hint={preset?.base_url ? "Pre-filled for this provider. Change it only if you use a proxy." : "Required for a gateway, for example https://your-gateway.example.com/v1"}>
              <input className="field font-mono" value={f.base_url} onChange={(e) => set("base_url", e.target.value)} placeholder={preset?.base_url ?? "https://…/v1"} spellCheck={false} />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label="API key" hint={cfg.key_unreadable ? "The saved key can no longer be decrypted (the server secret changed). Enter it again." : "Stored encrypted on the server. It is never shown again, only replaced or removed."}>
              <span className="relative block">
                <input className="field pr-24 font-mono" type={showKey ? "text" : "password"} autoComplete="off" spellCheck={false} value={f.api_key}
                  onChange={(e) => setF({ ...f, api_key: e.target.value, clear_key: false })} placeholder={keyShown === "removed" ? "Key will be removed on save" : keyShown ? `${keyShown} saved. Type to replace` : "Paste a key (not needed for local Ollama)"} />
                <span className="absolute right-1.5 top-1.5 flex items-center gap-0.5">
                  <button type="button" onClick={() => setShowKey((s) => !s)} aria-label={showKey ? "Hide key" : "Show key"} className="btn grid size-7 place-items-center rounded text-muted hover:text-ink">{showKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}</button>
                  {cfg.key_set && !f.clear_key && <button type="button" onClick={() => setF({ ...f, api_key: "", clear_key: true })} className="btn h-7 rounded px-2 text-[12px] font-medium text-err hover:bg-err-soft">Remove</button>}
                  {f.clear_key && <button type="button" onClick={() => set("clear_key", false)} className="btn h-7 rounded px-2 text-[12px] font-medium text-accent hover:bg-accent-soft">Undo</button>}
                </span>
              </span>
            </Field>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-line pt-5">
          <Button icon={busy === "test" ? undefined : <Zap className="size-4" />} loading={busy === "test"} onClick={runTest} disabled={!f.enabled}>Test connection</Button>
          <p className="text-[12.5px] text-muted">Sends one tiny request with the values above. Nothing is saved.</p>
        </div>
        {t && (
          <div role="status" className={clsx("enter mt-4 flex items-start gap-3 rounded-lg border px-4 py-3 text-sm", t.ok ? "border-ok/30 bg-ok-soft" : "border-err/30 bg-err-soft")}>
            {t.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-err" />}
            <div className="min-w-0">
              {t.ok ? <><p className="font-medium">Connected{t.latency_ms != null && <span className="font-normal text-ink-2"> · {t.latency_ms} ms</span>}</p><p className="truncate text-[12.5px] text-ink-2">{t.model} replied {t.reply}</p></>
                : <><p className="font-medium text-err">The model did not answer</p><p className="break-words text-[12.5px] text-ink-2">{t.error ?? t.message}</p></>}
            </div>
          </div>
        )}
      </Card>

      <Card className="overflow-clip">
        <button onClick={() => setAdvanced((a) => !a)} aria-expanded={advanced} className="btn flex w-full items-center justify-between px-6 py-4 text-left hover:bg-bg">
          <span><span className="block text-[15px] font-semibold">Advanced</span><span className="block text-[12.5px] text-muted">Timeouts, retries, temperature, how much text is sent and how many requests run at once</span></span>
          <ChevronDown className={clsx("size-4 text-muted transition-transform", advanced && "rotate-180")} />
        </button>
        {advanced && (
          <div className="enter grid grid-cols-1 gap-4 border-t border-line px-6 py-5 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Timeout (seconds)"><input className="field" type="number" min={5} max={300} value={f.timeout_s} onChange={(e) => set("timeout_s", +e.target.value)} /></Field>
            <Field label="Retries"><input className="field" type="number" min={0} max={6} value={f.max_retries} onChange={(e) => set("max_retries", +e.target.value)} /></Field>
            <Field label="Temperature" hint="0 is the most repeatable."><input className="field" type="number" min={0} max={1} step={0.1} value={f.temperature} onChange={(e) => set("temperature", +e.target.value)} /></Field>
            <Field label="Max characters sent" hint="Long invoices keep the first pages and the last."><input className="field" type="number" min={2000} max={100000} step={1000} value={f.max_chars} onChange={(e) => set("max_chars", +e.target.value)} /></Field>
            <Field label="Parallel requests"><input className="field" type="number" min={1} max={16} value={f.concurrency} onChange={(e) => set("concurrency", +e.target.value)} /></Field>
            <div className="flex items-end justify-between gap-3 rounded-lg bg-bg px-3 py-2.5"><span className="text-[13px] font-medium">Ask for JSON mode<span className="block text-[12px] font-normal text-muted">Turn off if the provider rejects it</span></span><Toggle checked={f.json_mode} onChange={(v) => set("json_mode", v)} label="JSON mode" /></div>
          </div>
        )}
      </Card>

      <Card className="p-6">
        <h2 className="text-[15px] font-semibold">OCR engine</h2>
        <p className="mt-1 text-[13px] text-muted">Reads scanned pages and photos. Tesseract is the safe default; RapidOCR can be faster on clean scans.</p>
        <div role="radiogroup" aria-label="OCR engine" className="mt-4 grid grid-cols-1 max-w-xl gap-3 sm:grid-cols-2">
          {[["tesseract", "Tesseract", "Classic, widely tested"], ["rapidocr", "RapidOCR", "ONNX models, no system install"]].map(([id, name, hint]) => (
            <button key={id} role="radio" aria-checked={f.ocr_engine === id} onClick={() => set("ocr_engine", id)}
              className={clsx("btn rounded-xl border px-4 py-3 text-left", f.ocr_engine === id ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong")}>
              <span className="block text-sm font-medium">{name}</span><span className="block text-[12px] text-muted">{hint}</span>
            </button>
          ))}
        </div>
      </Card>

      <p className="flex items-start gap-2 text-[12.5px] leading-relaxed text-muted"><ShieldCheck className="mt-0.5 size-4 shrink-0 text-ok" /><span>Changes apply to the <b className="font-medium text-ink-2">next document</b> without a restart. Records already extracted keep the model they were read with; re-process them from Documents to use the new one. Every change is written to the audit log, and the key itself is never logged.</span></p>

      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-card/90 px-4 py-3 backdrop-blur lg:left-[248px]">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-3 lg:px-6">
          <Button variant="ghost" icon={<RotateCcw className="size-4" />} disabled={cfg.source === "env" || !!busy} onClick={() => setResetting(true)}>Reset to .env defaults</Button>
          <span className="flex items-center gap-2 text-[12.5px] text-muted sm:ml-auto">{dirty ? <><span className="size-2 rounded-full bg-warn" /> Unsaved changes</> : "All changes saved"}</span>
          <span className="ml-auto flex items-center gap-2 sm:ml-0">
            {dirty && <Button variant="ghost" onClick={() => { setF(toForm(cfg)); setTest(null); }}>Discard</Button>}
            <Button variant="primary" loading={busy === "save"} disabled={!dirty} onClick={() => save()}>Save changes</Button>
          </span>
        </div>
      </div>

      <ConfirmDialog open={warn} tone="primary" title="The last test failed" confirmLabel="Save anyway" onConfirm={() => save(true)} onCancel={() => setWarn(false)}>
        <span className="flex items-start gap-2"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" /> The model did not answer with these settings. If you save them, new documents will use a model that is not working.</span>
      </ConfirmDialog>
      <ConfirmDialog open={resetting} title="Reset to the .env defaults?" confirmLabel="Reset" busy={busy === "reset"} onConfirm={reset} onCancel={() => setResetting(false)}>
        The saved model, key and OCR choice are removed from the app and the server&apos;s .env values apply again.
      </ConfirmDialog>
    </div>
  );
}
