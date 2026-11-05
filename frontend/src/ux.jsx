import React, { useEffect, useMemo, useRef, useState } from "react";
import { CornerDownLeft, Menu, Minus, Monitor, Moon, Plus, Search, Sun } from "lucide-react";

const SCALES = [1, 1.1, 1.2, 1.3, 1.45];
const DEFAULT_SCALE = 1.2;
const KEY = "eko.ui.scale";

const readScale = () => {
  try {
    const v = Number(localStorage.getItem(KEY));
    if (SCALES.includes(v)) return v;
  } catch { /* storage may be blocked */ }
  return DEFAULT_SCALE;
};

/** Text size: the whole interface is built from small fixed pixel sizes, so it is scaled with CSS zoom. */
export function useUiScale() {
  const [scale, setScale] = useState(readScale);
  useEffect(() => {
    document.documentElement.style.setProperty("--ui-zoom", String(scale));
    try { localStorage.setItem(KEY, String(scale)); } catch { /* ignore */ }
  }, [scale]);
  const step = (dir) => setScale((s) => SCALES[Math.min(SCALES.length - 1, Math.max(0, SCALES.indexOf(s) + dir))]);
  return { scale, bigger: () => step(1), smaller: () => step(-1), canBigger: scale < SCALES[SCALES.length - 1], canSmaller: scale > SCALES[0] };
}

export function TextSizeControl({ ui }) {
  return <div className="ux-textsize" role="group" aria-label="Text size">
    <button type="button" className="top-icon" title="Smaller text" aria-label="Smaller text" onClick={ui.smaller} disabled={!ui.canSmaller}><Minus size={14} /></button>
    <span aria-hidden="true">Aa</span>
    <button type="button" className="top-icon" title="Larger text" aria-label="Larger text" onClick={ui.bigger} disabled={!ui.canBigger}><Plus size={14} /></button>
  </div>;
}

const THEME_KEY = "eko.ui.theme";
const THEMES = ["light", "dark", "system"];
const readTheme = () => {
  try { const v = localStorage.getItem(THEME_KEY); if (THEMES.includes(v)) return v; } catch { /* storage may be blocked */ }
  return "light";
};
const systemDark = () => typeof window !== "undefined" && !!window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;

/** Light / dark / follow-system. index.html sets the first paint; this keeps it in step afterwards. */
export function useTheme() {
  const [mode, setMode] = useState(readTheme);
  useEffect(() => {
    const apply = () => document.documentElement.setAttribute("data-theme", mode === "dark" || (mode === "system" && systemDark()) ? "dark" : "light");
    apply();
    try { localStorage.setItem(THEME_KEY, mode); } catch { /* ignore */ }
    if (mode !== "system" || !window.matchMedia) return undefined;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener?.("change", apply);
    return () => mq.removeEventListener?.("change", apply);
  }, [mode]);
  return { mode, setMode };
}

export function ThemeControl({ theme }) {
  const opts = [["light", Sun, "Light theme"], ["dark", Moon, "Dark theme"], ["system", Monitor, "Match this device"]];
  return <div className="ux-theme" role="group" aria-label="Colour theme">
    {opts.map(([id, Icon, label]) => <button key={id} type="button" className={`top-icon ${theme.mode === id ? "on" : ""}`} title={label} aria-label={label} aria-pressed={theme.mode === id} onClick={() => theme.setMode(id)}><Icon size={14} /></button>)}
  </div>;
}

export function NavToggle({ open, onClick }) {
  return <button type="button" className="top-icon ux-navtoggle" aria-label="Open menu" aria-expanded={open} onClick={onClick}><Menu size={17} /></button>;
}

export function SearchTrigger({ onClick }) {
  const mac = typeof navigator !== "undefined" && /Mac/i.test(navigator.platform || "");
  return <button type="button" className="ux-searchbtn" onClick={onClick} aria-label="Search pages and actions">
    <Search size={14} /><span>Search pages and actions</span><kbd>{mac ? "⌘" : "Ctrl"} K</kbd>
  </button>;
}

/** Ctrl/⌘+K command palette: jump to any page or run a top action from the keyboard. */
export function CommandPalette({ open, onClose, items, onPick }) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef(null);
  const list = useRef(null);
  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) => `${it.label} ${it.group} ${it.hint || ""}`.toLowerCase().includes(q));
  }, [items, query]);

  useEffect(() => { if (open) { setQuery(""); setIndex(0); setTimeout(() => input.current?.focus(), 0); } }, [open]);
  useEffect(() => { setIndex(0); }, [query]);
  useEffect(() => { list.current?.querySelector(".active")?.scrollIntoView({ block: "nearest" }); }, [index]);
  if (!open) return null;

  const pick = (it) => { if (it) { onClose(); onPick(it); } };
  const onKey = (e) => {
    if (e.key === "Escape") { e.preventDefault(); onClose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setIndex((i) => Math.min(results.length - 1, i + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIndex((i) => Math.max(0, i - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); pick(results[index]); }
  };
  return <div className="ux-palette-backdrop" onMouseDown={onClose}>
    <div className="ux-palette" role="dialog" aria-modal="true" aria-label="Search pages and actions" onMouseDown={(e) => e.stopPropagation()} onKeyDown={onKey}>
      <div className="ux-palette-input"><Search size={16} /><input ref={input} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Type a page or action…" aria-label="Search" /><kbd>Esc</kbd></div>
      <div className="ux-palette-list" ref={list} role="listbox">
        {results.length === 0 && <div className="ux-palette-empty">No match for “{query}”.</div>}
        {results.map((it, i) => <button type="button" key={it.id} role="option" aria-selected={i === index} className={i === index ? "active" : ""} onMouseEnter={() => setIndex(i)} onClick={() => pick(it)}>
          {it.icon ? <it.icon size={16} /> : <span style={{ width: 16 }} />}
          <span className="ux-palette-label">{it.label}</span><small>{it.group}</small>{i === index && <CornerDownLeft size={13} />}
        </button>)}
      </div>
    </div>
  </div>;
}

export function useCommandShortcut(toggle) {
  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); toggle(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);
}

/** "What do I do next?" strip for the upload page; every state is derived from what the server already reports. */
export function UploadSteps({ sources, files, ready, onRun, running }) {
  const txDone = !!sources?.transactions, cmDone = !!sources?.commission;
  const steps = [
    { n: 1, title: "Upload transactions", text: txDone ? "Loaded and checked" : files?.transactions ? "File chosen: press Upload & Validate" : "Successful Transaction file (CSV or XLSX)", done: txDone },
    { n: 2, title: "Upload BC commission", text: cmDone ? "Loaded and checked" : files?.commission ? "File chosen: press Upload & Validate" : "Commission report for the same month", done: cmDone },
    { n: 3, title: "Add supporting files", text: "Optional: only for the incentives you want checked", done: false, optional: true },
    { n: 4, title: "Run reconciliation", text: ready ? "Everything required is ready" : "Unlocks after steps 1 and 2", done: false, action: true },
  ];
  const current = !txDone ? 1 : !cmDone ? 2 : 4;
  return <ol className="ux-steps" aria-label="Upload steps">
    {steps.map((s) => <li key={s.n} className={`${s.done ? "done" : ""} ${s.n === current ? "current" : ""} ${s.optional ? "optional" : ""}`}>
      <span className="ux-step-n" aria-hidden="true">{s.done ? "✓" : s.n}</span>
      <div><strong>{s.title}</strong><small>{s.text}</small></div>
      {s.action && <button type="button" className="enterprise-btn primary small" disabled={!ready || running} onClick={onRun}>Run now</button>}
    </li>)}
  </ol>;
}

/** Security checklist (admins only): what is protected and the few steps only the owner can do. */
export function SecurityChecklist({ apiBase }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const r = await fetch(`${apiBase}/api/database/security-posture`, { cache: "no-store" });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(r.status === 403 ? "Only administrators can see the security checklist." : (d.detail || "Checklist unavailable."));
        if (live) setData(d);
      } catch (e) { if (live) setError(e.message || "Checklist unavailable."); }
    })();
    return () => { live = false; };
  }, [apiBase]);
  if (error) return <section className="card ux-sec"><h3>Security checklist</h3><p className="ux-sec-note">{error}</p></section>;
  if (!data) return <section className="card ux-sec"><h3>Security checklist</h3><p className="ux-sec-note">Checking…</p></section>;
  const mark = { ok: "✓", action: "!", unknown: "?" };
  return <section className="card ux-sec">
    <div className="ux-sec-head"><h3>Security checklist</h3><span>{data.ok} protected{data.action ? ` · ${data.action} for you to do` : ""}{data.unknown ? ` · ${data.unknown} not readable` : ""}</span></div>
    <ul>{data.checks.map((c) => <li key={c.id} className={c.status}>
      <span className="ux-sec-mark" aria-hidden="true">{mark[c.status]}</span>
      <div><strong>{c.title}</strong><small>{c.detail}</small>{c.fix && <code>{c.fix}</code>}</div>
    </li>)}</ul>
  </section>;
}
