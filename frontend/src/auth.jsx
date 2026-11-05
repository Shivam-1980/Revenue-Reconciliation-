import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { KeyRound, LoaderCircle, LockKeyhole, LogIn, ShieldCheck } from "lucide-react";

// The session lives in an HttpOnly cookie the page cannot read. The CSRF token is kept
// only in memory and is re-fetched from /api/auth/session after a page reload.
let csrfToken = "";
// An SSO (OIDC) sign-in has no cookie: the backend returns a bearer token once, which is kept
// only in memory (never localStorage) and sent as an Authorization header, same lifetime as csrfToken.
let bearerToken = "";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function installAuthFetch(apiBase) {
  if (window.__ekoAuthFetchInstalled) return;
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input?.url;
    if (!url || !url.startsWith(apiBase)) return nativeFetch(input, init);
    const method = String(init.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
    if (!SAFE_METHODS.has(method) && csrfToken && !headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", csrfToken);
    if (bearerToken && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${bearerToken}`);
    const response = await nativeFetch(input, { ...init, headers, credentials: "include" });
    if (response.status === 401 && !url.includes("/api/auth/")) window.dispatchEvent(new CustomEvent("eko:auth-required"));
    return response;
  };
  window.__ekoAuthFetchInstalled = true;
}

const AuthContext = createContext({ user: null, signOut: () => {} });
export const useAuth = () => useContext(AuthContext);

// Google's own four-colour "G" mark, used only on the button that starts Google sign-in (brand guideline: show it
// alongside the provider's real name, "Continue with Google", not a generic icon).
const GoogleMark = () => <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
  <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.9c1.7-1.57 2.7-3.88 2.7-6.62z"/>
  <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.9-2.26c-.8.54-1.84.86-3.06.86-2.35 0-4.34-1.59-5.05-3.72H.97v2.33A9 9 0 0 0 9 18z"/>
  <path fill="#FBBC05" d="M3.95 10.7A5.4 5.4 0 0 1 3.67 9c0-.59.1-1.17.28-1.7V4.97H.97A9 9 0 0 0 0 9c0 1.45.35 2.83.97 4.03l2.98-2.33z"/>
  <path fill="#EA4335" d="M9 3.58c1.32 0 2.51.46 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .97 4.97l2.98 2.33C4.66 5.17 6.65 3.58 9 3.58z"/>
</svg>;

const SSO_BUTTON = {
  google: { icon: <GoogleMark/>, label: "Continue with Google" },
  microsoft: { icon: <LogIn size={16}/>, label: "Continue with Microsoft" },
  sso: { icon: <LogIn size={16}/>, label: "Continue with single sign-on" },
};

const readError = async (response, fallback) => {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return "Please check the details you entered.";
  } catch (_) { /* non-JSON error body */ }
  return fallback;
};

export function AuthGate({ apiBase, children }) {
  const [state, setState] = useState({ status: "checking", user: null, notice: "" });
  const oidcExchanged = useRef(false);

  const check = useCallback(async () => {
    try {
      const r = await fetch(`${apiBase}/api/auth/session`);
      if (!r.ok) throw new Error("signed out");
      const d = await r.json();
      if (!d.signed_in) throw new Error("signed out");
      csrfToken = d.csrf_token || "";
      setState({ status: "signed_in", user: d.user, notice: "" });
    } catch (_) {
      csrfToken = ""; bearerToken = "";
      setState(s => ({ status: "signed_out", user: null, notice: s.notice }));
    }
  }, [apiBase]);

  useEffect(() => {
    // The SSO provider lands back here as ?oidc_code=... (see oidc_callback on the backend).
    // The code is single-use and expires in 60s, so this runs at most once per redirect.
    const oidcCode = new URLSearchParams(window.location.search).get("oidc_code");
    if (oidcCode && !oidcExchanged.current) {
      oidcExchanged.current = true;
      window.history.replaceState(null, "", window.location.pathname);
      fetch(`${apiBase}/api/auth/oidc/exchange`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: oidcCode }) })
        .then(async r => { if (!r.ok) throw new Error(await readError(r, "SSO sign-in failed.")); return r.json(); })
        .then(d => { bearerToken = d.access_token || ""; check(); })
        .catch(err => { setState({ status: "signed_out", user: null, notice: "", ssoError: err.message }); });
      return;
    }
    check();
    const onAuthRequired = () => {
      csrfToken = ""; bearerToken = "";
      setState(s => s.status === "signed_in" ? { status: "signed_out", user: null, notice: "Your session ended. Please sign in again." } : s);
    };
    window.addEventListener("eko:auth-required", onAuthRequired);
    return () => window.removeEventListener("eko:auth-required", onAuthRequired);
  }, [check, apiBase]);

  const signOut = useCallback(async () => {
    try { await fetch(`${apiBase}/api/auth/logout`, { method: "POST" }); } catch (_) { /* cookie is cleared server-side when reachable */ }
    csrfToken = ""; bearerToken = "";
    setState({ status: "signed_out", user: null, notice: "You have been signed out." });
  }, [apiBase]);

  if (state.status === "checking") {
    return <div className="auth-splash" role="status"><LoaderCircle className="auth-spin" size={22}/>Checking your session…</div>;
  }
  if (state.status === "signed_out") {
    return <LoginScreen apiBase={apiBase} notice={state.notice} ssoError={state.ssoError}
      onSignedIn={(user, csrf) => { csrfToken = csrf; setState({ status: "signed_in", user, notice: "" }); }}/>;
  }
  return <AuthContext.Provider value={{ user: state.user, signOut }}>
    {children}
  </AuthContext.Provider>;
}

function LoginScreen({ apiBase, notice, ssoError, onSignedIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(ssoError || "");
  const [sso, setSso] = useState(null);   // null = not checked yet; {} = checked

  useEffect(() => {
    let cancelled = false;
    fetch(`${apiBase}/api/auth/oidc/config-status`)
      .then(r => r.ok ? r.json() : { configured: false })
      .then(d => { if (!cancelled) setSso(d); })
      .catch(() => { if (!cancelled) setSso({ configured: false }); });
    return () => { cancelled = true; };
  }, [apiBase]);

  const signInWithSso = () => { window.location.href = `${apiBase}/api/auth/oidc/login`; };

  const submitPassword = async e => {
    e.preventDefault(); setBusy(true); setError("");
    try {
      const r = await fetch(`${apiBase}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: email.trim(), password }) });
      if (!r.ok) throw new Error(await readError(r, "Sign-in failed."));
      const d = await r.json();
      setPassword("");
      onSignedIn(d.user, d.csrf_token);
    } catch (err) {
      setError(/failed to fetch/i.test(err.message) ? "The reconciliation service is not reachable. Make sure start.bat is running." : err.message);
    } finally { setBusy(false); }
  };

  return <div className="auth-shell">
    <aside className="auth-brand">
      <img src="/eko-logo.png" alt="Eko" className="auth-logo"/>
      <h1>Revenue Reconciliation</h1>
      <p>SBI Business Correspondent commission control centre.</p>
      <ul>
        <li><ShieldCheck size={16}/>Lock-out after repeated wrong passwords</li>
        <li><LockKeyhole size={16}/>Sessions expire after inactivity</li>
        <li><KeyRound size={16}/>Every change is recorded in the audit log</li>
      </ul>
    </aside>
    <main className="auth-panel">
      <div className="auth-card">
        <div className="auth-eyebrow">Eko × SBI · Secure access</div>
        <h2>Sign in</h2>
        <p className="auth-sub">Use your work e-mail and password.</p>
        {notice && <div className="auth-notice" role="status">{notice}</div>}
        {error && <div className="auth-error" role="alert">{error}</div>}
        <form onSubmit={submitPassword} noValidate>
          <label htmlFor="auth-email">Work e-mail</label>
          <input id="auth-email" type="email" autoComplete="username" required value={email} onChange={e => setEmail(e.target.value)} disabled={busy} autoFocus/>
          <label htmlFor="auth-password">Password</label>
          <input id="auth-password" type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} disabled={busy}/>
          <button className="auth-primary" type="submit" disabled={busy || !email || !password}>{busy ? <LoaderCircle className="auth-spin" size={16}/> : null}Sign in</button>
        </form>
        {sso?.configured && <>
          <div className="auth-divider" role="separator"><span>or</span></div>
          <button type="button" className="auth-sso" onClick={signInWithSso} disabled={busy}>
            {(SSO_BUTTON[sso.provider] || SSO_BUTTON.sso).icon}{(SSO_BUTTON[sso.provider] || SSO_BUTTON.sso).label}
          </button>
        </>}
      </div>
      <p className="auth-foot">Authorised Eko Bharat Ventures users only. Access is logged.</p>
    </main>
  </div>;
}
