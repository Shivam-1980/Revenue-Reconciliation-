import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, AlertTriangle, ArrowUpRight, BarChart3, Bot, CheckCircle2, ChevronDown, CircleDollarSign, Download, FileCheck2, FileText, LayoutDashboard, RefreshCw, Search, Settings2, ShieldCheck, SlidersHorizontal, Filter, Sparkles, Table2, TrendingUp, Upload, Users, X, Zap, Database, ClipboardList, SearchCheck, Gauge, Clock3, WalletCards, Building2, MoreHorizontal } from "lucide-react";
import { BarChart, Bar, CartesianGrid, Cell, PieChart, Pie, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from "recharts";
import "./styles.css";
import "./theme.css";
import "./dark.css";
import { CommandPalette, NavToggle, SearchTrigger, SecurityChecklist, TextSizeControl, ThemeControl, UploadSteps, useCommandShortcut, useTheme, useUiScale } from "./ux.jsx";
import { AuthGate, installAuthFetch, useAuth } from "./auth.jsx";

// Same host as the page, so the SameSite=Strict session cookie is always first-party.
const API_BASE = import.meta.env.VITE_API_BASE || `${window.location.protocol}//${window.location.hostname}:8000`;
// Session cookie + CSRF header on every API call; a 401 returns the user to sign-in.
installAuthFetch(API_BASE);

const friendlyApiError = (error, action = "request") => {
  const message = String(error?.message || error || "");
  if (/failed to fetch|networkerror|load failed|fetch failed/i.test(message)) {
    return `Cannot connect to the Revenue Reconciliation backend while trying to ${action}. The backend API at http://127.0.0.1:8000 is not responding. Close any duplicate project windows, run start.bat from the extracted project folder, and wait for READY. If it still fails, run diagnostics_backend.bat and inspect backend_runtime.log. The selected file has not been confirmed as uploaded; retry only after the health URL opens.`;
  }
  return message || `The backend could not ${action}. Check the backend window for details.`;
};
const fmt = n => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Number(n || 0));
const money = n => `₹${fmt(Math.abs(Number(n || 0)))}`;
const signedMoney = n => `${Number(n || 0) < 0 ? "-" : ""}₹${fmt(Math.abs(Number(n || 0)))}`;
const money0 = n => `₹${new Intl.NumberFormat("en-IN", {maximumFractionDigits:0}).format(Number(n || 0))}`;
const money2 = n => `₹${new Intl.NumberFormat("en-IN", {maximumFractionDigits:2}).format(Number(n || 0))}`;

function App() {
  const { user, signOut } = useAuth();
  const [active, setActive] = useState("Dashboard");
  const [csp, setCsp] = useState("All CSPs");
  const [type, setType] = useState("All Transaction Types");
  const [status, setStatus] = useState("All Status");
  const [search, setSearch] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [operationsMenuOpen, setOperationsMenuOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const ui = useUiScale();
  const theme = useTheme();
  useCommandShortcut(() => setPaletteOpen(v => !v));
  const [exporting, setExporting] = useState(false);
  const [summary, setSummary] = useState(null);
  const [cspData, setCspData] = useState([]);
  const [typeData, setTypeData] = useState([]);
  const [socialSecurity, setSocialSecurity] = useState(null);
  const [passbookCommission, setPassbookCommission] = useState(null);
  const [ruralCommission, setRuralCommission] = useState(null);
  const [dfsCommission, setDfsCommission] = useState(null);
  const [tabCommission, setTabCommission] = useState(null);
  const [matmCommission, setMatmCommission] = useState(null);
  const [loanLeadCommission, setLoanLeadCommission] = useState(null);
  const [sourceTypeData, setSourceTypeData] = useState([]);
  const [sourceTypeTotal, setSourceTypeTotal] = useState(0);
  const [exceptions, setExceptions] = useState([]);
  const [dataError, setDataError] = useState("");
  const [apiVersion, setApiVersion] = useState("");
  const [uploadSources, setUploadSources] = useState(null);
  const [historyPeriods, setHistoryPeriods] = useState([]);
  const [selectedHistory, setSelectedHistory] = useState("current");
  const [viewingHistory, setViewingHistory] = useState(false);
  const [historyCspType, setHistoryCspType] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyNotice, setHistoryNotice] = useState("");
  const [auditData, setAuditData] = useState(null);
  const [running, setRunning] = useState(false);
  const autoRunStarted = useRef(false);
  const [sourceStatus, setSourceStatus] = useState(null);
  const [periodGrain, setPeriodGrain] = useState("day");
  const [periodData, setPeriodData] = useState([]);
  const [periodError, setPeriodError] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [periodCsp, setPeriodCsp] = useState("");
  const [periodType, setPeriodType] = useState("");
  const [traceRows, setTraceRows] = useState([]);
  const [traceTotal, setTraceTotal] = useState(0);
  const [traceSearch, setTraceSearch] = useState("");
  const [traceOffset, setTraceOffset] = useState(0);
  const [harnessReport, setHarnessReport] = useState(null);
  const [harnessBusy, setHarnessBusy] = useState(false);
  const [harnessError, setHarnessError] = useState("");
  const [harnessToolResult, setHarnessToolResult] = useState(null);
  const [harnessToolBusy, setHarnessToolBusy] = useState("");
  const runHarnessTool = async (toolName) => { setHarnessToolBusy(toolName); setHarnessError(""); try { const r = await fetch(`${API_BASE}/api/ai-harness/tools/${toolName}`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})}); const d = await r.json(); if (!r.ok) throw new Error(d.detail || `Tool ${toolName} failed`); setHarnessToolResult(d); } catch(e) { setHarnessError(e.message || "Harness tool failed"); } finally { setHarnessToolBusy(""); } };
  const runHarness = async () => { setHarnessBusy(true); setHarnessError(""); try { const r = await fetch(`${API_BASE}/api/ai-harness/investigate`, {method:"POST"}); const d = await r.json(); if (!r.ok) throw new Error(d.detail || "Investigation unavailable"); setHarnessReport(d); } catch(e) { setHarnessError(e.message || "Investigation unavailable"); } finally { setHarnessBusy(false); } };

  const loadTrace = async (offset=0) => {
    try {
      const q = new URLSearchParams({offset:String(offset), limit:"100"});
      if (traceSearch) q.set("search", traceSearch);
      const r = await fetch(`${API_BASE}/api/operational/transactions?${q.toString()}`);
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Transaction trace unavailable");
      setTraceRows(d.rows || []); setTraceTotal(d.total || 0); setTraceOffset(offset);
    } catch(e) { setTraceRows([]); setTraceTotal(0); setDataError(friendlyApiError(e, "load transaction trace")); }
  };

  const runReconciliation = async (openAudit=false, quiet=false) => {
    setRunning(true);
    try {
      const r = await fetch(`${API_BASE}/api/reconciliation/run`, {method:"POST"});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Reconciliation could not be completed.");
      await loadReconciliation();
      await loadSourceStatus(false);
      // The server saves the month (snapshot + its source files in the database) as part of the run.
      try {
        const hd = d.month_saved || {};
        if (hd.saved) {
          setViewingHistory(false); setSelectedHistory("current");
          if (hd.sources_saved_to_database === false) setHistoryNotice(`Reconciliation saved, but the month's source files could not be stored in the database: ${hd.sources_error || "unknown error"}`);
          const list = await fetch(`${API_BASE}/api/reconciliation/history`, {cache:"no-store"});
          if (list.ok) setHistoryPeriods((await list.json()).periods || []);
        } else {
          const message = hd.error || "Unknown error";
          setHistoryNotice(`Reconciliation succeeded, but monthly history was not saved: ${message}`);
          console.warn("Reconciliation succeeded, but monthly history snapshot was not saved:", message);
        }
      } catch (historyError) {
        setHistoryNotice(`Reconciliation succeeded, but monthly history could not be saved: ${historyError.message || "API unavailable"}`);
        console.warn("Monthly history snapshot could not be saved:", historyError);
      }
      if (openAudit) { setActive("Audit & Reports"); alert(`Reconciliation completed. Run ID: ${d.run_id}`); }
    } catch(e) { if (quiet) setDataError(friendlyApiError(e, "run reconciliation")); else alert(friendlyApiError(e, "run reconciliation")); }
    finally { setRunning(false); }
  };

  const loadHistoryList = async () => {
    try {
      const r = await fetch(`${API_BASE}/api/reconciliation/history`, {cache:"no-store"});
      const d = await r.json();
      if (r.ok) {
        const periods = Array.isArray(d.periods) ? d.periods : [];
        setHistoryPeriods(periods);
        if (!periods.length) setHistoryNotice("No previous reconciliation history is available on this installation yet. Past periods will appear after a successful reconciliation is archived; older runs can only be recovered if their audit log still exists.");
        else setHistoryNotice("");
      } else setHistoryNotice(d.detail || "Could not load monthly reconciliation history.");
    } catch (_) { /* History is additive; it must not break the current workflow. */ }
  };

  const restoreSavedMonth = async (periodKey) => {
    const item = historyPeriods.find(p => p.period_key === periodKey);
    if (!window.confirm(`Restore the saved source files of ${item?.period_label || periodKey} into the current workspace?

The current workspace files are replaced. Nothing needs to be uploaded again; run reconciliation afterwards to recalculate with the current SBI rules.`)) return;
    setHistoryLoading(true);
    try {
      const r = await fetch(`${API_BASE}/api/reconciliation/history/${encodeURIComponent(periodKey)}/restore`, {method:"POST"});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "The saved month could not be restored.");
      setViewingHistory(false); setSelectedHistory("current");
      await loadSourceStatus(false);
      setHistoryNotice(d.message || "Saved month restored.");
    } catch (e) { alert(friendlyApiError(e, "restore the saved month")); }
    finally { setHistoryLoading(false); }
  };

  const showHistoricalPeriod = async (periodKey) => {
    if (periodKey === "current") {
      setSelectedHistory("current"); setViewingHistory(false);
      await loadReconciliation();
      return;
    }
    setHistoryLoading(true); setDataError("");
    try {
      const r = await fetch(`${API_BASE}/api/reconciliation/history/${encodeURIComponent(periodKey)}`, {cache:"no-store"});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Saved reconciliation period could not be loaded.");
      const summaryData = d.summary || {};
      setSummary({...summaryData, supplemental: d.supplemental || {}, historical_snapshot:true, historical_period_label:d.period_label, historical_saved_at:d.saved_at});
      setUploadSources(summaryData.upload_sources || null); setHistoryCspType(d.csp_type || []);
      setCspData((d.csp || []).map(row => ({
        csp:String(row.csp_id ?? "Unknown"), name:String(row.csp_id ?? "Unknown CSP"),
        txns:row.successful_transactions ?? 0, amount:row.transaction_amount ?? 0, reportBase:row.report_base ?? 0,
        expected:row.verified_expected_commission ?? null, actual:row.actual_commission ?? null,
        variance:row.financial_gap ?? row.variance ?? null, countVariance:row.count_variance ?? null,
        status:Number(row.exception_groups||0)>0 ? "Exception" : (row.expected_commission==null ? "Rate Master Missing" : (Math.abs(Number(row.variance||0))<0.005 ? "Reconciled" : Number(row.variance||0)>0 ? "Shortfall" : "Excess"))
      })));
      setTypeData((d.transaction_types || []).map(row => ({
        type:String(row.transaction_type ?? "Unknown"), mappingConfidence:String(row.mapping_confidence ?? "—"), expectedStatus:String(row.expected_calculation_status ?? "—"),
        txns:row.successful_transactions ?? 0, amount:row.transaction_amount ?? 0,
        reportBase:row.bc_report_base_overlap ?? row.report_base ?? 0, reportBaseTotal:row.bc_report_base_total ?? null,
        reportCommission:row.bc_report_commission_overlap ?? row.actual_commission ?? null, reportCommissionTotal:row.bc_report_commission_total ?? null,
        bcOnlyBase:row.bc_only_base ?? null, bcOnlyCommission:row.bc_only_commission ?? null,
        expected:row.expected_commission ?? null, verifiedExpected:row.verified_expected_commission ?? null, actual:row.actual_commission ?? null,
        variance:row.financial_gap ?? row.variance ?? null, countVariance:row.count_variance ?? null
      })));
      setExceptions((d.exceptions || []).map((row,i)=>({
        id:row.exception_id ?? `EX-${String(i+1).padStart(4,"0")}`, csp:String(row.csp_id ?? "Unknown"), type:String(row.transaction_type ?? "Unknown"), ref:row.transaction_id ?? "AGGREGATED",
        expected:row.expected_commission ?? 0, actual:row.actual_commission ?? 0, reportBase:row.report_base ?? 0, txns:row.successful_transactions ?? 0,
        variance:row.variance ?? row.count_variance ?? 0, reason:row.reconciliation_status ?? "Exception", rootCause:row.root_cause ?? "Reconciliation exception",
        action:row.recommended_action ?? "Review the CSP + transaction-type exception and source records.", severity:row.severity ?? "Medium", status:row.status ?? "Open"
      })));
      const st = d.successful_transaction_types || {};
      setSourceTypeData((st.rows || []).map(row=>({type:String(row.transaction_type ?? "Unknown"),txns:Number(row.successful_transactions||0),amount:Number(row.transaction_amount||0),csps:Number(row.unique_csps||0)})));
      setSourceTypeTotal(Number(st.total_successful_transactions||0));
      const extra = d.supplemental || {};
      setSocialSecurity(extra.social_security || null); setPassbookCommission(extra.passbook_printing || null); setRuralCommission(extra.rural_commission || null);
      setDfsCommission(extra.dfs_commission || null); setTabCommission(extra.tab_commission || null); setMatmCommission(extra.matm_commission || null);
      // Restore every supplemental dashboard control from the selected saved period.
      // Omitting Loan Lead here left that panel showing stale/current-period data while
      // the rest of the dashboard was displaying a historical snapshot.
      setLoanLeadCommission(extra.loan_lead_commission || null);
      setSelectedHistory(periodKey); setViewingHistory(true); setDataError(""); setActive("Dashboard");
    } catch (e) { setDataError(e.message || "Could not load saved reconciliation."); }
    finally { setHistoryLoading(false); }
  };

  const loadAudit = async () => {
    setAuditData(null);
    try {
      const [a,b,h] = await Promise.all([
        fetch(`${API_BASE}/api/audit/latest`, {cache:"no-store"}),
        fetch(`${API_BASE}/api/audit/controls`, {cache:"no-store"}),
        fetch(`${API_BASE}/api/audit/runs?limit=20`, {cache:"no-store"})
      ]);
      const [da,db,dh] = await Promise.all([a.json().catch(()=>({})), b.json().catch(()=>({})), h.json().catch(()=>({}))]);
      if (!a.ok) {
        setAuditData({error: da.detail || "No completed reconciliation run is recorded yet."});
        return;
      }
      if (!b.ok) throw new Error(db.detail || "Audit control totals could not be loaded.");
      if (!h.ok) throw new Error(dh.detail || "Audit run history could not be loaded.");
      setAuditData({latest: da, controls: db, history: Array.isArray(dh?.runs) ? dh.runs : []});
    } catch(e) {
      setAuditData({error:e.message || "Audit & Reports could not be loaded."});
    }
  };

  const loadSourceStatus = async (autoRun=true) => {
    try {
      const r = await fetch(`${API_BASE}/api/reconciliation/status`, {cache:"no-store"});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Unable to read upload status.');
      setSourceStatus(d);
      setUploadSources(d.upload_sources || null);
      // Rural Commission is an independent monthly control. Load its status even
      // before the core transaction reconciliation has run, so the user can see
      // whether the period-specific Rural CSP evidence is missing or validated.
      try {
        const ruralResponse = await fetch(`${API_BASE}/api/reconciliation/rural-commission`, {cache:"no-store"});
        const ruralData = await ruralResponse.json();
        setRuralCommission(ruralResponse.ok ? (ruralData || null) : {available:false,status:'ERROR',message:ruralData?.detail || 'Rural Commission control could not load.',summary:{},rows:[]});
      } catch (ruralError) {
        setRuralCommission({available:false,status:'ERROR',message:ruralError?.message || 'Rural Commission control could not reach the backend.',summary:{},rows:[]});
      }
      try {
        const dfsResponse = await fetch(`${API_BASE}/api/upload/dfs-incentive/reconciliation`, {cache:"no-store"});
        const dfsData = await dfsResponse.json();
        setDfsCommission(dfsResponse.ok ? (dfsData || null) : {available:false,status:'ERROR',message:dfsData?.detail || 'DFS control could not load.',summary:{},rows:[]});
      } catch (dfsError) {
        setDfsCommission({available:false,status:'ERROR',message:dfsError?.message || 'DFS control could not reach the backend.',summary:{},rows:[]});
      }
      try {
        const tabResponse = await fetch(`${API_BASE}/api/upload/tab-incentive/reconciliation`, {cache:"no-store"});
        const tabData = await tabResponse.json();
        setTabCommission(tabResponse.ok ? (tabData || null) : {available:false,status:'ERROR',message:tabData?.detail || 'TAB incentive control could not load.',summary:{},rows:[]});
      } catch (tabError) {
        setTabCommission({available:false,status:'ERROR',message:tabError?.message || 'TAB incentive control could not reach the backend.',summary:{},rows:[]});
      }
      try {
        const matmResponse = await fetch(`${API_BASE}/api/upload/matm-incentive/reconciliation`, {cache:"no-store"});
        const matmData = await matmResponse.json();
        setMatmCommission(matmResponse.ok ? (matmData || null) : {available:false,status:'ERROR',message:matmData?.detail || 'm-ATM control could not load.',summary:{},rows:[]});
      } catch (matmError) {
        setMatmCommission({available:false,status:'ERROR',message:matmError?.message || 'm-ATM control could not reach the backend.',summary:{},rows:[]});
      }
      try {
        const loanResponse = await fetch(`${API_BASE}/api/upload/loan-lead-generation/reconciliation`, {cache:"no-store"});
        const loanData = await loanResponse.json();
        setLoanLeadCommission(loanResponse.ok ? (loanData || null) : {available:false,status:'ERROR',message:loanData?.detail || 'Loan Lead control could not load.',summary:{},rows:[]});
      } catch (loanError) {
        setLoanLeadCommission({available:false,status:'ERROR',message:loanError?.message || 'Loan Lead control could not reach the backend.',summary:{},rows:[]});
      }
      if (d.reconciliation_cached) {
        await loadReconciliation();
      } else {
        // Never retain core results from a previous upload batch, but retain the
        // independent Rural control status fetched above.
        setSummary(null); setCspData([]); setTypeData([]); setSocialSecurity(null); setPassbookCommission(null); setRuralCommission(null); setDfsCommission(null); setTabCommission(null); setMatmCommission(null); setLoanLeadCommission(null); setSourceTypeData([]); setSourceTypeTotal(0); setExceptions([]);
        setDataError(d.ready_to_run ? "Sources are validated. Run reconciliation to calculate the current period." : "No completed transaction reconciliation. Upload and validate the current period's required files.");
        // Reconciliation is deliberately explicit. Upload/validation never triggers a financial run.
      }
    } catch (e) { setSourceStatus(null); setUploadSources(null); setSummary(null); setCspData([]); setTypeData([]); setSocialSecurity(null); setPassbookCommission(null); setRuralCommission(null); setSourceTypeData([]); setSourceTypeTotal(0); setExceptions([]); setDataError(e.message || "No current reconciliation data."); }
  };

  const loadReconciliation = async () => {
    try {
      setDataError("");
      // Load PMJJBY/PMSBY independently: its CSP-wise monthly source + BC report
      // control must remain visible even if the general Success/rate-master workflow
      // is incomplete or has a separate validation error.
      try {
        const ssResponse = await fetch(`${API_BASE}/api/reconciliation/social-security`, {cache:"no-store"});
        const ssData = await ssResponse.json();
        setSocialSecurity(ssResponse.ok ? (ssData || null) : {available:false,status:'ERROR',message:ssData?.detail || 'PMJJBY/PMSBY control could not load.',schemes:[],rows:[],total:{}});
      } catch (ssError) {
        setSocialSecurity({available:false,status:'ERROR',message:ssError?.message || 'PMJJBY/PMSBY control could not reach the backend.',schemes:[],rows:[],total:{}});
      }
      const urls = [
        `${API_BASE}/api/dashboard/summary`,
        `${API_BASE}/api/reconciliation/csp`,
        `${API_BASE}/api/reconciliation/transaction-type`,
        `${API_BASE}/api/reconciliation/exceptions`,
        `${API_BASE}/api/reconciliation/rural-commission`,
        `${API_BASE}/api/reconciliation/passbook-printing`,
        `${API_BASE}/api/upload/dfs-incentive/reconciliation`,
        `${API_BASE}/api/upload/tab-incentive/reconciliation`,
        `${API_BASE}/api/upload/matm-incentive/reconciliation`
      ];
      const responses = await Promise.all(urls.map(u => fetch(u, {cache:"no-store"})));
      const data = await Promise.all(responses.map(r => r.json()));
      const failed = responses.findIndex(r => !r.ok);
      if (failed >= 0) throw new Error(data[failed]?.detail || "Upload both source files first.");
      setSummary(data[0]);
      setRuralCommission(data[4] || null);
      setPassbookCommission(data[5] || null);
      setDfsCommission(data[6] || null);
      setTabCommission(data[7] || null);
      setMatmCommission(data[8] || null);
      setUploadSources(data[0]?.upload_sources || null);
      try { const vr = await fetch(`${API_BASE}/api/version`, {cache:"no-store"}); if (vr.ok) { const vd = await vr.json(); setApiVersion(vd.version || ""); } } catch {}
      setCspData(data[1].map(r => ({
        csp: String(r.csp_id ?? "Unknown"), name: String(r.csp_id ?? "Unknown CSP"),
        txns: r.successful_transactions ?? 0, amount: r.transaction_amount ?? 0, reportBase: r.report_base ?? 0,
        expected: r.verified_expected_commission ?? null, actual: r.actual_commission ?? null, variance: r.financial_gap ?? r.variance ?? null, countVariance: r.count_variance ?? null,
        status: Number(r.exception_groups||0)>0 ? "Exception" : (r.expected_commission==null ? "Rate Master Missing" : (Math.abs(Number(r.variance||0))<0.005 ? "Reconciled" : Number(r.variance||0)>0 ? "Shortfall" : "Excess"))
      })));
      setTypeData(data[2].map(r => ({
        type: String(r.transaction_type ?? "Unknown"),
        mappingConfidence: String(r.mapping_confidence ?? "—"),
        expectedStatus: String(r.expected_calculation_status ?? "—"),
        txns: r.successful_transactions ?? 0,
        amount: r.transaction_amount ?? 0,
        // Count comparison uses only the overlapping CSP + transaction-type BC
        // population. Full BC-source totals remain separate controls in the API.
        reportBase: r.bc_report_base_overlap ?? r.report_base ?? 0,
        reportBaseTotal: r.bc_report_base_total ?? null,
        reportCommission: r.bc_report_commission_overlap ?? r.actual_commission ?? null,
        reportCommissionTotal: r.bc_report_commission_total ?? null,
        bcOnlyBase: r.bc_only_base ?? null,
        bcOnlyCommission: r.bc_only_commission ?? null,
        expected: r.expected_commission ?? null,
        verifiedExpected: r.verified_expected_commission ?? null,
        actual: r.actual_commission ?? null,
        // Passbook CSP-wise source lacks account IDs, so the approved-rate estimate
        // is provisional (the 5-print/account/month cap cannot be verified).
        // Still show the calculation and variance instead of the misleading "See Passbook control".
        variance: String(r.transaction_type ?? '').trim().toUpperCase() === 'PASSBOOK PRINTING'
          ? ((r.actual_commission != null && r.expected_commission != null)
              ? Number(r.actual_commission) - Number(r.expected_commission) : null)
          : (r.financial_gap ?? r.variance ?? null),
        countVariance: r.count_variance ?? null
      })));
      // Source-of-truth transaction-type counts come directly from the uploaded
      // Successful Transaction Sheet. They are deliberately independent of BC
      // joins/rate rules so reconciliation logic can never hide source rows.
      try {
        const sr = await fetch(`${API_BASE}/api/dashboard/successful-transaction-types`, {cache:"no-store"});
        if (sr.ok) {
          const sd = await sr.json();
          setSourceTypeData((sd.rows || []).map(r => ({
            type: String(r.transaction_type ?? "Unknown"),
            txns: Number(r.successful_transactions || 0),
            amount: Number(r.transaction_amount || 0),
            csps: Number(r.unique_csps || 0)
          })));
          setSourceTypeTotal(Number(sd.total_successful_transactions || 0));
        }
      } catch {}
      setExceptions(data[3].map((r, i) => ({
        id: r.exception_id ?? `EX-${String(i + 1).padStart(4, "0")}`,
        csp: String(r.csp_id ?? "Unknown"), type: String(r.transaction_type ?? "Unknown"), ref: r.transaction_id ?? "AGGREGATED",
        expected: r.expected_commission ?? 0, actual: r.actual_commission ?? 0, reportBase: r.report_base ?? 0, txns: r.successful_transactions ?? 0, variance: r.variance ?? r.count_variance ?? 0,
        reason: r.reconciliation_status ?? "Exception", rootCause: r.root_cause ?? "Reconciliation exception", action: r.recommended_action ?? "Review the CSP + transaction-type exception and source records.", severity: r.severity ?? "Medium", status: r.status ?? "Open"
      })));
    } catch (e) {
      setSummary(null); setUploadSources(null); setCspData([]); setTypeData([]); setSocialSecurity(null); setPassbookCommission(null); setRuralCommission(null); setSourceTypeData([]); setSourceTypeTotal(0); setExceptions([]); setDataError(friendlyApiError(e, "load dashboard data"));
    }
  };

  useEffect(() => {
    // A full page load/refresh intentionally starts a clean reconciliation session.
    // Uploaded period files and generated results are cleared server-side, while
    // the permanent approved SBI rulebook and mapping catalogs remain available.
    let live = true;
    void loadHistoryList();
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/workspace/clear-current-data`, {method:"POST", cache:"no-store"});
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || "Could not clear previous upload data.");
        if (live) {
          setSummary(null); setCspData([]); setTypeData([]); setSocialSecurity(null); setPassbookCommission(null); setRuralCommission(null); setDfsCommission(null); setTabCommission(null); setMatmCommission(null); setLoanLeadCommission(null);
          setRuralCommission(null); setDfsCommission(null); setTabCommission(null); setMatmCommission(null);
          setLoanLeadCommission(null); setSourceTypeData([]); setSourceTypeTotal(0); setExceptions([]);
          setPeriodData([]); setTraceRows([]); setTraceTotal(0); setAuditData(null);
          setHarnessReport(null); setHarnessToolResult(null); setUploadSources(null);
          setDataError("");
          await loadSourceStatus(false);
        }
      } catch (e) {
        if (live) setDataError(friendlyApiError(e, "initialize a clean workspace"));
      }
    })();
    return () => { live = false; };
  }, []);
  useEffect(() => { if (active === "Audit & Reports") loadAudit(); if (active === "Transaction Traceability") loadTrace(0); }, [active]);
  useEffect(() => {
    if (active !== "Period Analysis") return;
    (async()=>{
      try {
        setPeriodError("");
        const q=new URLSearchParams({grain:periodGrain});
        if(periodStart) q.set("start_date",periodStart);
        if(periodEnd) q.set("end_date",periodEnd);
        if(periodCsp) q.set("csp_id",periodCsp);
        if(periodType) q.set("transaction_type",periodType);
        const r=await fetch(`${API_BASE}/api/reconciliation/time?${q.toString()}`);
        const d=await r.json();
        if(!r.ok) throw new Error(d.detail||"Period analysis unavailable");
        setPeriodData(d);
      } catch(e){ setPeriodData([]); setPeriodError(e.message||"Period analysis unavailable"); }
    })();
  }, [active, periodGrain, periodStart, periodEnd, periodCsp, periodType]);

  useEffect(() => {
    const t=uploadSources?.transactions;
    if(t?.period_start && !periodStart) setPeriodStart(t.period_start);
    if(t?.period_end && !periodEnd) setPeriodEnd(t.period_end);
  }, [uploadSources]);

  const filteredCsp = useMemo(() => cspData.filter(r =>
    (csp === "All CSPs" || r.csp === csp) && (search === "" || `${r.csp} ${r.name}`.toLowerCase().includes(search.toLowerCase()))
  ), [cspData, csp, search]);
  const filteredExceptions = useMemo(() => exceptions.filter(e =>
    (csp === "All CSPs" || e.csp === csp) && (type === "All Transaction Types" || e.type === type) &&
    (status === "All Status" || e.status === status) && (search === "" || `${e.id} ${e.csp} ${e.type} ${e.ref}`.toLowerCase().includes(search.toLowerCase()))
  ), [exceptions, csp, type, status, search]);

  const refresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setDataError("");
    try {
      // Refresh means re-read the live backend state, not merely repaint React.
      // Disable browser HTTP caching so a changed upload/reconciliation cannot
      // leave the dashboard showing an earlier API response.
      await loadSourceStatus(false);
      if (active === "Audit & Reports") await loadAudit();
      if (active === "Transaction Traceability") await loadTrace(0);
      if (active === "AI Harness") {
        setHarnessReport(null);
        setHarnessToolResult(null);
        setHarnessError("");
      }
      if (active === "Period Analysis") {
        // Changing the grain to itself does not trigger its effect; fetch the
        // currently selected period explicitly on refresh.
        const q = new URLSearchParams({grain:periodGrain});
        if (periodStart) q.set("start_date",periodStart);
        if (periodEnd) q.set("end_date",periodEnd);
        if (periodCsp) q.set("csp_id",periodCsp);
        if (periodType) q.set("transaction_type",periodType);
        const r = await fetch(`${API_BASE}/api/reconciliation/time?${q.toString()}`, {cache:"no-store"});
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || "Period analysis refresh failed.");
        setPeriodData(d);
        setPeriodError("");
      }
    } catch (e) {
      setDataError(friendlyApiError(e, "refresh dashboard data"));
    } finally {
      setRefreshing(false);
    }
  };
  const exportReport = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const r = await fetch(`${API_BASE}/api/reconciliation/export?format=xlsx`);
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d?.detail || "Upload and validate all three source files, then run reconciliation first.");
      }
      const blob = await r.blob();
      if (!blob.size) throw new Error("The backend returned an empty report.");
      const url = URL.createObjectURL(blob); const a = document.createElement("a");
      a.href = url; a.download = "revenue_reconciliation_audit_report.xlsx"; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { alert(friendlyApiError(e, "export the report")); }
    finally { setExporting(false); }
  };

  const pieData = summary ? [{name:"Matched",value:Number(summary.count_matched_groups||0)},{name:"Exceptions",value:Math.max(0,Number(summary.count_control_groups||0)-Number(summary.count_matched_groups||0))}] : [];
  const typeOptions = [...new Set(typeData.map(x => x.type))];
  const cspOptions = [...new Set(cspData.map(x => x.csp))];

  const periodLabel = (() => {
    const t = uploadSources?.transactions;
    if (!t) return "No active reconciliation period";
    if (t.period_start && t.period_end) return t.period_start === t.period_end ? t.period_start : `${t.period_start} → ${t.period_end}`;
    return t.filename || "Current upload";
  })();

  // Background auto-run: once the two required files are validated and nothing changes for AUTO_RUN_DELAY_MS,
  // the reconciliation starts by itself. It runs once per distinct set of uploaded sources (a failed run is not retried
  // in a loop), never while a saved month is being viewed, and can be cancelled from the banner.
  const AUTO_RUN_DELAY_MS = 15000;
  const autoRunFor = useRef("");
  const autoRunTimer = useRef(null);
  const [autoRunNote, setAutoRunNote] = useState("");
  const sourceSignature = useMemo(() => JSON.stringify(sourceStatus?.upload_sources || null), [sourceStatus]);
  useEffect(() => {
    clearTimeout(autoRunTimer.current);
    const eligible = sourceStatus?.ready_to_run && !sourceStatus?.reconciliation_cached && !viewingHistory && autoRunFor.current !== sourceSignature;
    if (running) { setAutoRunNote("Reconciliation is running in the background. You can keep working; results appear here when it finishes."); return; }
    if (!eligible) { setAutoRunNote(""); return; }
    setAutoRunNote(`Required files are ready. Reconciliation will start by itself in ${AUTO_RUN_DELAY_MS / 1000} seconds. Add any supporting files first if you have them.`);
    autoRunTimer.current = setTimeout(() => { autoRunFor.current = sourceSignature; void runReconciliation(false, true); }, AUTO_RUN_DELAY_MS);
    return () => clearTimeout(autoRunTimer.current);
  }, [sourceStatus, running, viewingHistory, sourceSignature]);
  const cancelAutoRun = () => { clearTimeout(autoRunTimer.current); autoRunFor.current = sourceSignature; setAutoRunNote(""); };
  const runNowFromBanner = () => { clearTimeout(autoRunTimer.current); autoRunFor.current = sourceSignature; void runReconciliation(false, true); };

  const paletteItems = [
    ...[['Dashboard',LayoutDashboard],['Data Upload',Upload],['Reconciliation',FileCheck2],['AI Harness',Bot],['Transaction Analysis',BarChart3],['CSP Analysis',Users],['CSP Transaction Counts',Table2],['Exception Center',AlertTriangle]].map(([label,icon])=>({id:label,label,icon,group:'Control center',kind:'page'})),
    ...[['Successful Transactions',Database],['BC Commission Data',CircleDollarSign],['SBI Expected Commission Rule',FileText],['Data Processing',Zap],['Period Analysis',TrendingUp],['Transaction Traceability',SearchCheck],['Audit & Reports',ShieldCheck]].map(([label,icon])=>({id:label,label,icon,group:'Operations',kind:'page'})),
    {id:'act-refresh',label:'Refresh current workspace',icon:RefreshCw,group:'Action',kind:'refresh'},
    {id:'act-export',label:'Download reconciliation audit workbook',icon:Download,group:'Action',kind:'export'},
    {id:'act-signout',label:'Sign out',icon:X,group:'Action',kind:'signout'},
  ];
  const onPalettePick = (it) => {
    if (it.kind === 'page') { setActive(it.id); setNavOpen(false); }
    else if (it.kind === 'refresh') refresh();
    else if (it.kind === 'export') exportReport();
    else if (it.kind === 'signout') signOut();
  };

  return <div className="enterprise-app">
    <header className="enterprise-topbar">
      <NavToggle open={navOpen} onClick={()=>setNavOpen(v=>!v)}/>
      <div className="enterprise-brand">
        <div className="enterprise-logo"><img src="/eko-logo.png" alt="Eko"/></div>
        <div><div className="enterprise-title">Revenue Reconciliation</div><div className="enterprise-subtitle">EKO × SBI · BC Commission Control Center</div></div>
      </div>
      <div className="enterprise-top-actions">
        <SearchTrigger onClick={()=>setPaletteOpen(true)}/>
        <TextSizeControl ui={ui}/>
        <ThemeControl theme={theme}/>
        <div className="period-chip"><span className="live-dot"/> {periodLabel}</div>
        <button className="top-icon" title="Refresh current workspace" aria-label="Refresh current workspace" onClick={refresh} disabled={refreshing}><RefreshCw size={16} className={refreshing?"spin":""}/></button>
        <button className="top-icon" title="Download reconciliation audit workbook" aria-label="Download reconciliation audit workbook" onClick={exportReport} disabled={exporting}><Download size={16}/></button>
        <div className="operations-menu-wrap">
          <button className="user-chip" aria-haspopup="menu" aria-expanded={operationsMenuOpen} onClick={()=>setOperationsMenuOpen(v=>!v)}>
            <div className="user-avatar">{(user?.email||"?").slice(0,2).toUpperCase()}</div><div><strong>{user?.email||"Signed in"}</strong><span>{String(user?.role||"").replace("_"," ")}</span></div><ChevronDown size={14}/>
          </button>
          {operationsMenuOpen && <div className="operations-menu" role="menu">
            <div className="operations-menu-heading">Workspace</div>
            {[['Dashboard','Dashboard'],['Upload current-period files','Data Upload'],['Reconciliation controls','Reconciliation'],['Audit & Reports','Audit & Reports']].map(([label,target])=><button key={target} role="menuitem" onClick={()=>{setActive(target);setOperationsMenuOpen(false);}}>{label}</button>)}
            <div className="operations-menu-status"><span className={`menu-status-dot ${sourceStatus?.ready_to_run?'ready':''}`}/>{sourceStatus?.ready_to_run?'Sources validated':sourceStatus?.reconciliation_cached?'Latest results available':'Current period not ready'}</div>
            <button role="menuitem" className="operations-menu-signout" onClick={()=>{setOperationsMenuOpen(false);signOut();}}>Sign out</button>
          </div>}
        </div>
      </div>
    </header>
    <div className="enterprise-shell">
      <div className={`ux-scrim ${navOpen?"open":""}`} onClick={()=>setNavOpen(false)}/>
      <aside className={`enterprise-sidebar ${navOpen?"open":""}`}>
        <div className="side-section-title">CONTROL CENTER</div>
        {[['Dashboard',LayoutDashboard],['Data Upload',Upload],['Reconciliation',FileCheck2],['AI Harness',Bot],['Transaction Analysis',BarChart3],['CSP Analysis',Users],['CSP Transaction Counts',Table2],['Exception Center',AlertTriangle]].map(([label,Icon])=><button key={label} onClick={()=>{setActive(label);setNavOpen(false)}} className={`enterprise-nav ${active===label?'active':''}`}><Icon size={17}/><span>{label}</span></button>)}
        <div className="side-section-title secondary">OPERATIONS</div>
        {[['Successful Transactions',Database],['BC Commission Data',CircleDollarSign],['SBI Expected Commission Rule',FileText],['Data Processing',Zap],['Period Analysis',TrendingUp],['Transaction Traceability',SearchCheck],['Audit & Reports',ShieldCheck]].map(([label,Icon])=><button key={label} onClick={()=>{setActive(label);setNavOpen(false)}} className={`enterprise-nav ${active===label?'active':''}`}><Icon size={17}/><span>{label}</span></button>)}
        <div className="side-bottom">
          <div className="agent-status-card"><div className="agent-status-icon"><Bot size={17}/></div><div><strong>AI Analysis Layer</strong><span><i/> Online · Explainable</span></div></div>
          <div className="security-note"><ShieldCheck size={14}/><span>Deterministic financial rules · Audit trace enabled</span></div>
        </div>
      </aside>
      <main className="enterprise-main">
        <div className="enterprise-head">
          <div><div className="enterprise-eyebrow">EKO · SBI BUSINESS CORRESPONDENT</div><h1>{active === 'Reconciliation' ? 'Reconciliation Command Center' : active}</h1><p>{active === 'Reconciliation' ? 'A management-ready view of transaction coverage, commission variance and exceptions.' : 'Manage and investigate the current reconciliation workspace.'}</p></div>
          <div className="head-actions">
            <label className="history-selector-label" title="Open a previously reconciled month"><span>Reconciled month</span><select value={selectedHistory} disabled={historyLoading} onChange={e=>void showHistoricalPeriod(e.target.value)}><option value="current">Current workspace</option>{historyPeriods.map(item=><option key={item.period_key} value={item.period_key}>{item.period_label}{item.legacy_audit_summary_only ? " · audit summary only" : ""}{item.saved_at ? ` · saved ${String(item.saved_at).slice(0,10)}` : ""}</option>)}</select></label>
            {viewingHistory && historyPeriods.find(p=>p.period_key===selectedHistory)?.restorable && <button className="enterprise-btn secondary" disabled={historyLoading} title="Bring this month's saved source files back into the workspace (no re-upload)" onClick={()=>void restoreSavedMonth(selectedHistory)}><RefreshCw size={15}/> Restore month files</button>}
            <button className="enterprise-btn secondary" onClick={()=>setShowFilters(!showFilters)}><SlidersHorizontal size={15}/> Filters</button>
            <button className="enterprise-btn secondary" onClick={()=>{setViewingHistory(false);setSelectedHistory("current");setActive('Data Upload')}}><Upload size={15}/> Upload</button>
            <button className="enterprise-btn primary" onClick={()=>runReconciliation(false)} disabled={running || !sourceStatus?.ready_to_run}>{running?<><RefreshCw size={15} className="spin"/> Running</>:<><Zap size={15}/> Run Reconciliation</>}</button>
          </div>
        </div>
        {autoRunNote && <div className="ux-autorun" role="status" aria-live="polite">{running?<RefreshCw size={15} className="spin"/>:<Clock3 size={15}/>}<span>{autoRunNote}</span>{!running&&<><button type="button" className="enterprise-btn primary small" onClick={runNowFromBanner}>Run now</button><button type="button" className="enterprise-btn secondary small" onClick={cancelAutoRun}>Cancel auto-run</button></>}</div>}
        {historyNotice && !viewingHistory && <div className="history-view-banner"><div><strong>Monthly history status</strong><span>{historyNotice}</span></div><button className="enterprise-btn secondary" onClick={()=>void loadHistoryList()}>Refresh history</button></div>}
        {viewingHistory && <div className="history-view-banner"><div><strong>Viewing saved reconciliation: {summary?.historical_period_label || selectedHistory}</strong><span>{summary?.historical_note ? summary.historical_note + " To restore full CSP-wise, transaction-type and exception details, upload that month's original source files in the current workspace and rerun reconciliation; the new full snapshot will replace this summary-only entry. · " : "Full read-only historical snapshot · "}saved {summary?.historical_saved_at ? new Date(summary.historical_saved_at).toLocaleString() : "previously"}. Current uploads and current-period calculations are unchanged.</span></div><button className="enterprise-btn secondary" onClick={()=>void showHistoricalPeriod("current")}>Return to current workspace</button></div>}
        <div className={`enterprise-filter ${showFilters?'open':''}`}><div><label>Period</label><div className="filter-static">{periodLabel}</div></div><div><label>CSP</label><select value={csp} onChange={e=>setCsp(e.target.value)}><option>All CSPs</option>{cspOptions.map(x=><option key={x}>{x}</option>)}</select></div><div><label>Transaction Type</label><select value={type} onChange={e=>setType(e.target.value)}><option>All Transaction Types</option>{typeOptions.map(x=><option key={x}>{x}</option>)}</select></div><div><label>Status</label><select value={status} onChange={e=>setStatus(e.target.value)}><option>All Status</option><option>Open</option><option>Investigating</option><option>Resolved</option></select></div></div>
        {active === 'Data Upload' ? <UploadWorkspace onUploaded={()=>{setViewingHistory(false);setSelectedHistory("current");autoRunStarted.current=false; setSummary(null); setCspData([]); setTypeData([]); setSocialSecurity(null); setPassbookCommission(null); setRuralCommission(null); setSourceTypeData([]); setSourceTypeTotal(0); setExceptions([]); setDataError('Waiting for current upload reconciliation...'); void loadSourceStatus(false)}} sourceStatus={sourceStatus} onRunRequested={()=>runReconciliation(false)} /> : active === 'Successful Transactions' ? <SourceDataView kind="transactions" title="Successful Transaction Sheet" subtitle="Complete row-level data fetched directly from the currently uploaded Successful Transaction source." icon={Database}/> : active === 'BC Commission Data' ? <SourceDataView kind="commission" title="BC Commission Sheet" subtitle="Complete row-level data fetched directly from the currently uploaded BC / Commission source." icon={CircleDollarSign}/> : active === 'SBI Expected Commission Rule' ? <SourceDataView kind="expected_commission_rule" title="SBI Expected Commission Rule" subtitle="Permanent SBI commission master. Use the workbook-sheet selector to view both Consolidated Commission Master and Slabs & Incentive Matrices, including DFS targets, monthly incentives, and average-balance matrix." icon={FileText}/> : active === 'Data Processing' ? <ProcessingView/> : active === 'Period Analysis' ? <PeriodAnalysisView grain={periodGrain} setGrain={setPeriodGrain} data={periodData} error={periodError} start={periodStart} setStart={setPeriodStart} end={periodEnd} setEnd={setPeriodEnd} csp={periodCsp} setCsp={setPeriodCsp} type={periodType} setType={setPeriodType}/> : active === 'Audit & Reports' ? <><SecurityChecklist apiBase={API_BASE}/><AuditView auditData={auditData} onRefresh={loadAudit} onRun={runReconciliation}/></> : active === 'Transaction Traceability' ? <TransactionTraceView rows={traceRows} total={traceTotal} offset={traceOffset} search={traceSearch} setSearch={setTraceSearch} onSearch={()=>loadTrace(0)} onPage={loadTrace}/> : active === 'Exception Center' ? <ExceptionCenterView exceptions={filteredExceptions} onExport={exportReport} search={search} setSearch={setSearch}/> : active === 'AI Harness' ? <AIHarnessView report={harnessReport} busy={harnessBusy} error={harnessError} onRun={runHarness} onRunTool={runHarnessTool} toolResult={harnessToolResult} toolBusy={harnessToolBusy}/> : active === 'CSP Transaction Counts' ? <CspTypeCountsView key={selectedHistory} snapshotRows={viewingHistory?historyCspType:null} monthLabel={viewingHistory?(summary?.historical_period_label||''):''}/> : active === 'CSP Analysis' ? <CspAnalysisView rows={filteredCsp} search={search} setSearch={setSearch} onExport={exportReport}/> : active === 'Transaction Analysis' ? <TransactionAnalysisView rows={typeData} socialSecurity={socialSecurity} search={search} setSearch={setSearch} onExport={exportReport}/> : <><ReconciliationView matmCommission={matmCommission} passbookCommission={passbookCommission} historicalWomenCspIncentive={viewingHistory ? (summary?.historical_snapshot ? (summary?.supplemental?.women_csp_incentive || null) : null) : null} viewingHistory={viewingHistory} ruralCommission={ruralCommission} dfsCommission={dfsCommission} tabCommission={tabCommission} loanLeadCommission={loanLeadCommission} summary={summary} uploadSources={uploadSources} dataError={dataError} cspData={filteredCsp} typeData={typeData} sourceTypeData={sourceTypeData} sourceTypeTotal={sourceTypeTotal} exceptions={filteredExceptions} pieData={pieData} search={search} setSearch={setSearch} csp={csp} type={type} status={status} apiVersion={apiVersion} onShowFilters={()=>setShowFilters(true)} onExport={exportReport} onNavigate={setActive}/></>}
        <footer className="enterprise-footer"><span><ShieldCheck size={13}/> Financial calculations use deterministic reconciliation rules.</span><span>AI assists with data understanding and exception explanations.</span></footer>
      </main>
    </div>
  <CommandPalette open={paletteOpen} onClose={()=>setPaletteOpen(false)} items={paletteItems} onPick={onPalettePick}/>
  </div>;

}

function AIHarnessView({report,busy,error,onRun,onRunTool,toolResult,toolBusy}) {
  const priorityCounts = report?.agent_summary?.priority_counts || {};
  return <section className="view-stack">
    <div className="card">
      <CardHeader title="AI Reconciliation Harness — Phase 2" subtitle="Evidence-grounded investigation queue. Prioritization is deterministic; financial calculations and approvals remain controlled."/>
      <div className="insight-list">
        <Insight icon={ShieldCheck} title="Read-only financial controls" text="The agent cannot change commission values, approved SBI rules, mappings, or CSP identities." tone="success"/>
        <Insight icon={SearchCheck} title="Prioritized investigation queue" text="Exceptions are ranked using status, count variance, financial gap and rule-approval evidence. Scores are review-order heuristics, not probabilities." tone="info"/>
        <Insight icon={AlertTriangle} title="Human approval required" text="Suggested causes are hypotheses. Rule changes, identity corrections and settlement decisions require evidence and explicit approval." tone="warning"/>
      </div>
      <div className="head-actions" style={{marginTop:16}}>
        <button className="primary-btn" onClick={onRun} disabled={busy}>{busy?<><RefreshCw size={15} className="spin"/> Prioritizing…</>:<><Sparkles size={15}/> Prioritize Current Exceptions</>}</button>
        <span className="muted">Phase 2 · deterministic triage · no external LLM configured</span>
      </div>
      {error?<p className="error-text">{error}</p>:null}
      <div className="card">
        <CardHeader title="Read-only investigation tools" subtitle="Use the existing deterministic services through the allow-listed tool interface."/>
        <div className="head-actions" style={{display:"flex",flexWrap:"wrap",gap:8}}>
          {[
            ["validate_upload","Validate uploads"],
            ["resolve_csp_identity","Resolve CSP identity"],
            ["calculate_expected_commission","Calculate expected commission"],
            ["reconcile_period","Run reconciliation"],
            ["explain_variance","Explain variance"],
            ["calculate_kpi","Calculate KPI"]
          ].map(([tool,label])=><button key={tool} className="secondary-btn" onClick={()=>onRunTool(tool)} disabled={!!toolBusy}>{toolBusy===tool?"Running…":label}</button>)}
        </div>
        {toolResult?<pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",maxHeight:360,overflow:"auto",fontSize:12,marginTop:12}}>{JSON.stringify(toolResult,null,2)}</pre>:null}
      </div>
    </div>
    {report?<>
      <div className="metric-grid">
        <div className="metric-card"><span>Total result groups</span><strong>{fmt(report.total_result_groups)}</strong></div>
        <div className="metric-card"><span>Exception groups</span><strong>{fmt(report.exception_groups)}</strong></div>
        <div className="metric-card"><span>Cases returned</span><strong>{fmt(report.cases_returned)}</strong></div>
        <div className="metric-card"><span>P1 urgent</span><strong>{fmt(priorityCounts["P1 - URGENT"]||0)}</strong></div>
        <div className="metric-card"><span>P2 high</span><strong>{fmt(priorityCounts["P2 - HIGH"]||0)}</strong></div>
      </div>
      <div className="card">
        <CardHeader title="Prioritized investigation queue" subtitle={`Generated ${report.generated_at_utc || ""} · source fingerprint ${String(report.source_metadata_sha256||"").slice(0,16)}…`}/>
        {report.agent_summary?<p className="muted">{report.agent_summary.prioritization}. Queue size: {fmt(report.agent_summary.queue_size)}. Scores do not modify KPI or settlement values.</p>:null}
        {(report.cases||[]).length ? <div className="table-wrap"><table><thead><tr><th>Rank</th><th>Priority</th><th>Score</th><th>Case</th><th>CSP</th><th>Transaction type</th><th>Status</th><th>Cause hypothesis</th><th>Priority reasons</th><th>Recommended checks</th><th>Decision</th></tr></thead><tbody>{report.cases.map(c=><tr key={c.case_id}><td>{c.queue_rank ?? "—"}</td><td>{c.priority_band || "UNRANKED"}</td><td>{c.priority_score ?? "—"}</td><td>{c.case_id}</td><td>{c.csp_id||"N/A"}</td><td>{c.transaction_type||"N/A"}</td><td>{c.status}</td><td>{c.root_cause_hypothesis}</td><td><ul>{(c.priority_reasons||[]).map((a,i)=><li key={i}>{a}</li>)}</ul></td><td><ul>{c.recommended_checks.map((a,i)=><li key={i}>{a}</li>)}</ul></td><td>{c.decision}</td></tr>)}</tbody></table></div>:<p>No exception groups were returned for the current reconciliation result.</p>}
        <p className="muted">Priority is a deterministic review-order heuristic, not an AI confidence score. No financial values or rules were modified; all proposed fixes require source evidence, regression tests and approval.</p>
      </div>
    </>:null}
  </section>;
}

function ReconciliationView({matmCommission,passbookCommission,historicalWomenCspIncentive,viewingHistory,ruralCommission,dfsCommission,tabCommission,loanLeadCommission,summary,uploadSources,dataError,cspData,typeData,sourceTypeData,sourceTypeTotal,exceptions,pieData,search,setSearch,csp,type,status,apiVersion,onShowFilters,onExport,onNavigate}) {
  const money2 = n => `₹${new Intl.NumberFormat('en-IN',{maximumFractionDigits:2}).format(Number(n||0))}`;
  const money0 = n => `₹${new Intl.NumberFormat('en-IN',{maximumFractionDigits:0}).format(Number(n||0))}`;
  const compact = n => new Intl.NumberFormat('en-IN',{notation:'compact',maximumFractionDigits:1}).format(Number(n||0));
  const signed = n => `${Number(n||0)<0?'-':''}₹${new Intl.NumberFormat('en-IN',{maximumFractionDigits:2}).format(Math.abs(Number(n||0)))}`;
  const period = uploadSources?.transactions?.period_start && uploadSources?.transactions?.period_end
    ? `${uploadSources.transactions.period_start} → ${uploadSources.transactions.period_end}` : 'Current upload';
  const matched = Number(summary?.count_matched_groups || 0);
  const controlGroups = Number(summary?.count_control_groups || 0);
  const exceptionGroups = Math.max(0, controlGroups - matched);
  const successful = Number(summary?.successful_transactions || 0);
  const eligible = Number(summary?.eligible_transactions || 0);
  const approvedTransactions = Number(summary?.fully_comparable_transactions || 0);
  const ruleCoverage = Number(summary?.settlement_rule_coverage ?? summary?.rate_rule_coverage ?? 0);
  const matchRate = Number(summary?.reconciliation_rate || (controlGroups ? matched / controlGroups * 100 : 0));
  // Keep two explicitly different KPIs: the health donut is transaction-only,
  // while the command-center hero uses the combined controlled rate when
  // the backend confirms current-period Rural and/or DFS controls. Never hardcode a rate.
  const ruralRows = Array.isArray(ruralCommission?.rows) ? ruralCommission.rows : [];
  const ruralAvailable = Boolean(ruralCommission?.available) && ruralRows.length > 0;
  const ruralGroups = Number(summary?.rural_commission_control_groups ?? ruralCommission?.summary?.rural_csp_count ?? ruralRows.length ?? 0);
  const ruralMatched = Number(summary?.rural_commission_matched_controls ?? ruralRows.filter(x => String(x.status || '') === 'Matched').length);
  // Derived locally from the current Rural control population; avoids a render-time ReferenceError.
  const ruralMatchRate = ruralGroups > 0 ? (ruralMatched / ruralGroups) * 100 : null;
  const overallRateValue = summary?.overall_controlled_reconciliation_rate;
  // The backend only publishes this KPI when a current-period Rural control is available.
  // Do not gate it on ruralRows being loaded in this separate panel: summary and Rural
  // detail endpoints can resolve at different times, which previously forced the hero
  // back to the transaction-only rate (e.g. 50%) despite a valid combined KPI (61.4%).
  const overallRateAvailable = overallRateValue !== null && overallRateValue !== undefined
    && Number.isFinite(Number(overallRateValue))
    && Number(summary?.overall_controlled_groups || 0) > 0;
  // Headline includes distinct, READY control populations: successful transaction
  // count groups, Rural CSP, DFS, PMJJBY/PMSBY, and Passbook. Women CSP Rule 24 is
  // deliberately kept as a separate monthly incentive KPI to avoid conflating it.
  const allSourceRateValue = summary?.all_source_control_rate;
  const allSourceRateAvailable = allSourceRateValue !== null && allSourceRateValue !== undefined
    && Number.isFinite(Number(allSourceRateValue))
    && Number(summary?.all_source_control_groups || 0) > 0;
  const extendedControlsAvailable = allSourceRateAvailable || overallRateAvailable
    || Number(summary?.dfs_control_groups || 0) > 0
    || Number(summary?.women_csp_control_groups || 0) > 0;
  const heroControlGroups = allSourceRateAvailable ? Number(summary?.all_source_control_groups) : (overallRateAvailable ? Number(summary?.overall_controlled_groups ?? controlGroups + ruralGroups) : controlGroups);
  const heroMatchedGroups = allSourceRateAvailable ? Number(summary?.all_source_control_matched_groups) : (overallRateAvailable ? Number(summary?.overall_controlled_matched_groups ?? matched + ruralMatched) : matched);
  // The displayed numerator/denominator are the canonical source of truth.
  // Do not show a separately cached/backend rate that can drift from those counts.
  const heroRate = heroControlGroups > 0 ? (heroMatchedGroups / heroControlGroups) * 100 : 0;
  const heroExceptionGroups = Math.max(0, heroControlGroups - heroMatchedGroups);
  // Health chart and hero always use the same uploaded-control population.
  const healthMatchedGroups = allSourceRateAvailable ? heroMatchedGroups : (overallRateAvailable ? heroMatchedGroups : matched);
  const healthControlGroups = allSourceRateAvailable ? heroControlGroups : (overallRateAvailable ? heroControlGroups : controlGroups);
  const healthExceptionGroups = Math.max(0, healthControlGroups - healthMatchedGroups);
  const healthRate = healthControlGroups > 0 ? (healthMatchedGroups / healthControlGroups) * 100 : 0;
  // Both KPI widgets must use identical counts and rounding to one decimal.
  const displayedHeroRate = Number(heroRate.toFixed(1));
  // Single formatted percentage source for both widgets. The health donut uses
  // the same canonical matched/total control population as the headline, so it
  // must not independently round a separately-derived rate.
  const displayedHealthRate = displayedHeroRate;
  const ruralExceptions = ruralRows.filter(x => String(x.status || '') !== 'Matched').sort((a,b) => Math.abs(Number(b.difference_bank_minus_expected || 0)) - Math.abs(Number(a.difference_bank_minus_expected || 0)));
  const expected = summary?.expected_commission_comparable ?? summary?.verified_expected_commission ?? summary?.provisional_transaction_expected_commission;
  const verifiedExpected = summary?.verified_expected_commission;
  const actual = summary?.actual_comparable_commission ?? summary?.provisional_actual_transaction_commission;
  const variance = summary?.comparable_variance ?? summary?.provisional_financial_gap;
  const calculatedExpected = summary?.calculated_expected_commission;
  const transactionAmount = Number(summary?.transaction_amount || 0);
  const grossCommission = summary?.bc_reported_gross_commission ?? summary?.bc_report_total_commission;
  const penalty = summary?.penalty_amount;
  const netPayable = summary?.bc_net_payable ?? summary?.final_commission ?? summary?.bc_reported_net_payable;
  const countMismatch = Number(summary?.count_mismatch_groups || 0);
  const missingCommission = Number(summary?.missing_commission_groups || 0);
  const rateMissing = Number(summary?.rate_master_missing_groups || 0);
  const unmapped = Number(summary?.unmapped_groups || summary?.unmapped_transaction_groups || 0);
  const health = matchRate >= 98 && exceptionGroups === 0 ? 'Reconciled' : matchRate >= 90 ? 'Needs attention' : 'Critical';
  const healthTone = health === 'Reconciled' ? 'good' : health === 'Needs attention' ? 'warn' : 'bad';
  const visibleCsps = cspData.filter(r => (csp === 'All CSPs' || r.csp === csp) && (!search || `${r.csp} ${r.name}`.toLowerCase().includes(search.toLowerCase())));
  const visibleTypes = typeData.filter(r => (type === 'All Transaction Types' || r.type === type) && (!search || r.type.toLowerCase().includes(search.toLowerCase())));
  // Rural Commission is a monthly CSP incentive, not a per-transaction type.
  // Render it as an explicitly labelled control row so the monthly table remains complete
  // without mixing CSP counts into transaction counts or inventing a count variance.
  const showRuralInTypeTable = (type === 'All Transaction Types' || type === 'Rural Commission')
    && (!search || 'rural commission'.includes(search.trim().toLowerCase()));
  const showDfsInTypeTable = (type === 'All Transaction Types' || type === 'DFS PRIORITIES INCENTIVE' || type === 'DFS Incentive')
    && (!search || 'dfs priorities incentive'.includes(search.trim().toLowerCase()) || 'dfs incentive'.includes(search.trim().toLowerCase()));
  const showWomenInTypeTable = (type === 'All Transaction Types' || type === 'WOMEN CSP INCENTIVE' || type === 'Women CSP Incentive')
    && (!search || 'women csp incentive'.includes(search.trim().toLowerCase()) || 'rule 24'.includes(search.trim().toLowerCase()));
  const showLoanLeadInTypeTable = (type === 'All Transaction Types' || type === 'LOAN LEAD GENERATION' || type === 'Loan Lead Generation')
    && (!search || 'loan lead generation activities'.includes(search.trim().toLowerCase()) || 'loan lead generation'.includes(search.trim().toLowerCase()));
  const loanLeadAvailable = Boolean(loanLeadCommission?.available);
  const loanLeadSummary = loanLeadCommission?.summary || {};
  const showTabInTypeTable = (type === 'All Transaction Types' || type === 'TAB FINANCIAL TRANSACTION INCENTIVE' || type === 'TAB Incentive')
    && (!search || 'tab financial transaction incentive'.includes(search.trim().toLowerCase()) || 'tab incentive'.includes(search.trim().toLowerCase()));
  // Monthly printer reimbursement is a non-transactional SBI incentive, but it
  // must remain visible in the transaction-type control table as a separate row.
  // Expected stays N/A until independent active/deployed printer evidence exists.
  const showPrinterReimbursementInTypeTable = (type === 'All Transaction Types' || type === 'PASSBOOK PRINTER COST REIMBURSEMENT' || type === 'Passbook Printer Cost Reimbursement')
    && (!search || 'passbook printer cost reimbursement'.includes(search.trim().toLowerCase()) || 'printer reimbursement'.includes(search.trim().toLowerCase()));
  const printerReimbursementControl = (summary?.monthly_expected_components || []).find(c => String(c.component || '').toLowerCase() === 'passbook printer cost reimbursement') || {};
  const dfsAvailable = Boolean(dfsCommission?.available) && dfsCommission?.status === 'READY';
  const dfsSummary = dfsCommission?.summary || {};
  const tabAvailable = Boolean(tabCommission?.available) && tabCommission?.status === 'READY';
  const tabSummary = tabCommission?.summary || {};
  const matmAvailable = Boolean(matmCommission?.available) && matmCommission?.status === 'READY';
  const matmSummary = matmCommission?.summary || {};
  const showMatmInTypeTable = (type === 'All Transaction Types' || type === 'MATM CASH TRANSACTIONS INCENTIVE' || type === 'm-ATM Cash Incentive' || type === 'm-ATM')
    && (!search || 'matm cash transactions incentive'.includes(search.trim().toLowerCase()) || 'm-atm'.includes(search.trim().toLowerCase()));
  const dfsMatched = Number(dfsSummary.matched || 0);
  const dfsExpected = dfsSummary.expected_total;
  const dfsActual = dfsSummary.actual_total;
  const dfsVariance = dfsSummary.variance_actual_minus_expected;
  const ruralPaidCspCount = ruralRows.filter(x => Number(x.actual_commission || 0) > 0).length
    + Number(ruralCommission?.summary?.unmapped_paid_csp_count || 0);
  const ruralExpectedAmount = ruralCommission?.summary?.expected_commission;
  const ruralActualAmount = ruralCommission?.summary?.total_bank_rural_commission;
  const typeTableCount = visibleTypes.length + (showRuralInTypeTable ? 1 : 0) + (showDfsInTypeTable ? 1 : 0) + (showWomenInTypeTable ? 1 : 0) + (showTabInTypeTable ? 1 : 0) + (showLoanLeadInTypeTable ? 1 : 0) + (showPrinterReimbursementInTypeTable ? 1 : 0) + (showMatmInTypeTable ? 1 : 0);
  const topCsps = [...visibleCsps].sort((a,b)=>Math.abs(Number(b.variance||0))-Math.abs(Number(a.variance||0))).slice(0,8);
  const topTypes = [...visibleTypes].sort((a,b)=>Number(b.txns||0)-Number(a.txns||0)).slice(0,8);
  const maxType = Math.max(1,...topTypes.map(x=>Number(x.txns||0)));
  const sourceRows = [...sourceTypeData].sort((a,b)=>Number(b.txns||0)-Number(a.txns||0)).slice(0,7);
  const auditOk = Number(summary?.condition_audit?.ok || 0);
  const auditFail = Number(summary?.condition_audit?.failed || summary?.condition_audit?.error || 0);
  const productRows = Array.isArray(summary?.product_wise_commission) ? summary.product_wise_commission : [];
  const initialDepositCalc = summary?.initial_deposit_conditional_calculation || {};
  const initialDepositSlabs = Array.isArray(initialDepositCalc.slabs) ? initialDepositCalc.slabs : [];
  const productGross = summary?.product_commission_gross ?? grossCommission;
  const productPenalty = summary?.product_commission_penalty ?? penalty;
  const productNet = summary?.product_commission_total_after_penalty ?? netPayable;

  if (!summary) return <>
    <div className="rr-empty-state">
      <div className="rr-empty-icon"><Gauge size={28}/></div>
      <div><span className="rr-overline">RECONCILIATION WORKSPACE</span><h2>Ready to reconcile</h2><p>{dataError || 'Upload the successful transaction file, BC commission report and approved SBI rate master, then run reconciliation.'}</p></div>
      <button className="rr-btn rr-primary" onClick={()=>onNavigate('Data Upload')}><Upload size={16}/> Open data controls</button>
    </div>

  </>;

  return <div className="rr-dashboard">
    <div className="rr-filterbar">
      <div className="rr-filter-left">
        <div className="rr-search"><Search size={16}/><input placeholder="Search CSP, transaction type or exception" value={search} onChange={e=>setSearch(e.target.value)}/>{search&&<button onClick={()=>setSearch('')}><X size={14}/></button>}</div>
        <span className={`rr-health ${healthTone}`}><i/> {health}</span>
      </div>
      <div className="rr-filter-right">
        <span className="rr-period"><Clock3 size={14}/><b>{period}</b></span>
        <button className="rr-btn rr-secondary" onClick={onExport}><Download size={15}/> Export</button>
      </div>
    </div>

    {dataError && <div className="rr-alert"><AlertTriangle size={17}/><div><b>Data control warning</b><span>{dataError}</span></div></div>}

    <section className="rr-hero">
      <div className="rr-hero-main">
        <div className="rr-overline light">EKO × SBI · REVENUE RECONCILIATION</div>
        <h2>Financial control tower</h2>
        <p>One view of source coverage, reconciliation status, commission exposure and the exceptions that require investigation.</p><small style={{display:'block',marginTop:6,color:'rgba(255,255,255,.75)'}}>Headline = matched ÷ total for the included current-period control populations. Women CSP Rule 24 remains a separate monthly financial KPI. Transaction-count and financial commission match rates are also shown separately.</small>
        <div className="rr-hero-tags"><span><ShieldCheck size={14}/> SBI rule controlled</span><span><Database size={14}/> Source controlled</span><span><SearchCheck size={14}/> Audit trace enabled</span></div>
        {extendedControlsAvailable && <div className="rr-hero-auditline" aria-label="Reconciliation rate details">
          <span><b>Uploaded-control rate</b> {displayedHeroRate.toFixed(1)}% <em>({fmt(heroMatchedGroups)} / {fmt(heroControlGroups)} controls)</em></span>
          <span><b>Transactions only</b> {matchRate.toFixed(1)}%</span>
          <span><b>Rural</b> {fmt(ruralMatched)} / {fmt(ruralGroups)}</span>
          <span><b>DFS</b> {fmt(summary?.dfs_control_matched_groups || 0)} / {fmt(summary?.dfs_control_groups || 0)}{summary?.dfs_headline_included === false && summary?.dfs_control_groups > 0 ? ' · excluded from headline (CSP IDs unresolved)' : ''}</span>
          <span><b>PMJJBY/PMSBY</b> {summary?.social_security_control_status === 'READY' ? `${fmt(summary?.social_security_matched_controls || 0)} / ${fmt(summary?.social_security_control_groups || 0)}` : (summary?.social_security_control_status || 'N/A')}</span>
          <span><b>Passbook Printing</b> {summary?.passbook_printing_control_status === 'READY' ? `${fmt(summary?.passbook_printing_matched_controls || 0)} / ${fmt(summary?.passbook_printing_control_groups || 0)}` : (summary?.passbook_printing_control_status || 'N/A')}</span>
          <span><b>Women CSP Rule 24</b> {summary?.women_csp_control_status === 'READY' ? `${fmt(summary?.women_csp_matched_controls || 0)} matched / ${fmt(summary?.women_csp_control_groups || 0)} eligible/paid controls` : (summary?.women_csp_control_status || 'N/A')}</span>
          <span><b>Loan Lead Generation</b> {summary?.loan_lead_control_groups > 0 ? `${fmt(summary?.loan_lead_control_matched_groups || 0)} / ${fmt(summary?.loan_lead_control_groups || 0)} controls · ${summary?.loan_lead_control_status || 'PROVISIONAL'}` : (summary?.loan_lead_control_status || 'SOURCE_REQUIRED')}</span>
        </div>}
      </div>
      <div className="rr-hero-score">
        <div className="rr-score-ring" aria-label={`${displayedHeroRate.toFixed(1)} percent controlled rate`}><svg viewBox="0 0 42 42" aria-hidden="true"><circle cx="21" cy="21" r="15.9155" fill="none" stroke="rgba(255,255,255,.15)" strokeWidth="3.5"/><circle cx="21" cy="21" r="15.9155" fill="none" stroke="white" strokeWidth="3.5" strokeLinecap="round" strokeDasharray={`${Math.min(100,Math.max(0,heroRate))} ${100-Math.min(100,Math.max(0,heroRate))}`} strokeDashoffset="25"/></svg><div><b>{displayedHeroRate.toFixed(1)}%</b></div></div>
        <div className="rr-score-meta"><span>{allSourceRateAvailable ? (summary?.all_source_control_status === 'PROVISIONAL' ? 'Provisional control exceptions' : 'Included-control exceptions') : (overallRateAvailable ? 'Core exception groups' : 'Transaction exception groups')}</span><b>{fmt(heroExceptionGroups)}</b><small>{fmt(heroControlGroups)} {allSourceRateAvailable ? `controls in KPI: ${(summary?.all_source_control_included_categories || []).join(' + ')}` : (overallRateAvailable ? 'transaction + Rural control groups' : 'transaction control groups')}</small></div>
      </div>
    </section>

    <section className="rr-kpis">
      <div className="rr-kpi"><div className="rr-kpi-icon blue"><Database size={18}/></div><span>Total transaction amount</span><strong>{money0(transactionAmount)}</strong><small>Successful transaction source</small></div>
      <div className="rr-kpi"><div className="rr-kpi-icon teal"><CircleDollarSign size={18}/></div><span>Successful transactions</span><strong>{fmt(successful)}</strong><small>{fmt(successful)} source rows</small></div>
      <div className="rr-kpi"><div className="rr-kpi-icon green"><CheckCircle2 size={18}/></div><span>Transaction reconciled groups</span><strong>{fmt(matched)}</strong><small>{matchRate.toFixed(1)}% of transaction control groups</small></div>
      <div className="rr-kpi"><div className="rr-kpi-icon amber"><AlertTriangle size={18}/></div><span>Transaction exception groups</span><strong>{fmt(exceptionGroups)}</strong><small>{fmt(countMismatch)} count exceptions · {fmt(Number(summary?.count_missing_bc_groups||0))} missing BC groups</small></div>
      <div className="rr-kpi"><div className="rr-kpi-icon red"><TrendingUp size={18}/></div><span>Penalty / deduction</span><strong>{penalty==null?'N/A':money2(penalty)}</strong><small>{penalty==null?'Evidence unavailable':'Verified from BC source'}</small></div>
      <div className="rr-kpi"><div className="rr-kpi-icon indigo"><WalletCards size={18}/></div><span>BC net payable</span><strong>{netPayable==null?'N/A':money2(netPayable)}</strong><small>Gross commission less verified penalty</small></div>
    </section>




    <section className="rr-main-grid rr-main-grid-single">
      <div className="rr-card rr-health-card">
        <div className="rr-card-head"><div><span className="rr-overline">RECONCILIATION HEALTH</span><h3>Overall control group outcome</h3><p>{allSourceRateAvailable ? `All-source control KPI: ${(summary?.all_source_control_included_categories || []).join(' + ') || 'current-period ready sources'}. Women CSP Rule 24 is shown separately.` : overallRateAvailable ? 'Core control KPI: transaction + Rural controls. DFS and other supplemental sources are shown separately unless included in the all-source KPI.' : 'Transaction-only control KPI; supplemental control sources are not currently ready.'}</p><small className="rr-muted">Adding a rule or uploading a source does not automatically increase the match rate: a control counts as matched only when the current-period source comparison satisfies that category’s matching rule.</small></div></div>
        <div className="rr-health-layout"><div className="rr-donut"><ResponsiveContainer width="100%" height={190}><PieChart><Pie data={[{name:'Reconciled',value:healthMatchedGroups},{name:'Exceptions',value:healthExceptionGroups}]} innerRadius={61} outerRadius={80} paddingAngle={3} dataKey="value"><Cell fill="#0f766e"/><Cell fill="#f59e0b"/></Pie><Tooltip formatter={(v,n)=>[fmt(v),n]}/></PieChart></ResponsiveContainer><div><b>{displayedHealthRate.toFixed(1)}%</b><span>{allSourceRateAvailable ? 'all included source controls' : overallRateAvailable ? 'transactions + Rural controls' : 'transaction controls'}</span></div></div><div className="rr-health-stats"><div><i className="dot-green"/><span>Matched control groups</span><b>{fmt(healthMatchedGroups)}</b></div><div><i className="dot-amber"/><span>Exception control groups</span><b>{fmt(healthExceptionGroups)}</b></div><div><i className="dot-red"/><span>Transaction count mismatch groups</span><b>{fmt(countMismatch)}</b></div><div><i className="dot-blue"/><span>Approved-rule transactions (rows)</span><b>{fmt(approvedTransactions)}</b></div></div></div>
      </div>
    </section>

    <section className="rr-control-strip">
      <div><div className="rr-control-icon green"><CheckCircle2 size={16}/></div><span>Approved rule coverage</span><b>{ruleCoverage.toFixed(1)}%</b><small>{fmt(approvedTransactions)} settlement-approved / {fmt(successful)} successful</small></div>
      <div><div className="rr-control-icon amber"><AlertTriangle size={16}/></div><span>Count mismatches</span><b>{fmt(countMismatch)}</b><small>CSP + transaction type population</small></div>
      <div><div className="rr-control-icon red"><CircleDollarSign size={16}/></div><span>Missing commission</span><b>{fmt(missingCommission)}</b><small>BC actual unavailable for groups</small></div>
      <div><div className="rr-control-icon blue"><Settings2 size={16}/></div><span>Rate master gaps</span><b>{fmt(rateMissing)}</b><small>Approved rule mapping required</small></div>
      <div><div className="rr-control-icon purple"><Sparkles size={16}/></div><span>Unmapped groups</span><b>{fmt(unmapped)}</b><small>Transaction mapping review</small></div>
      <div><div className="rr-control-icon teal"><ShieldCheck size={16}/></div><span>Rural Commission controls</span><b>{ruralAvailable ? `${fmt(ruralMatched)} / ${fmt(ruralGroups)}` : 'N/A'}</b><small>{ruralAvailable ? 'Matched / total Rural CSP controls; tracked separately' : 'Current-period Rural CSP source required'}</small></div>
    </section>

    <section className="rr-card rr-product-commission-card">
      <div className="rr-card-head">
        <div><span className="rr-overline">INITIAL DEPOSIT · CM001–CM006</span><h3>Initial Deposit amount-slab calculation</h3><p>Slabs are calculated from the current successful-transaction upload. e-KYC and OVD totals are conditional scenarios only until account-level KYC evidence is supplied.</p></div>
        <span className={`rr-status ${initialDepositCalc.status==='CONDITIONAL_KYC_EVIDENCE_REQUIRED'?'warn':'good'}`}>{initialDepositCalc.status==='CONDITIONAL_KYC_EVIDENCE_REQUIRED'?'KYC evidence required':'Source status'}</span>
      </div>
      <div className="rr-product-summary">
        <div className="rr-financial-number"><span>Initial Deposit transactions</span><b>{fmt(initialDepositCalc.successful_transactions||0)}</b><small>{fmt(initialDepositCalc.unique_csps||0)} CSPs · deposit amount {money2(initialDepositCalc.amount_total||0)}</small></div>
        <div className="rr-financial-number"><span>e-KYC scenario</span><b>{initialDepositCalc.conditional_ekyc_total==null?'N/A':money2(initialDepositCalc.conditional_ekyc_total)}</b><small>CM001–CM004; not verified payable commission</small></div>
        <div className="rr-financial-number"><span>Non-e-KYC + OVD scenario</span><b>{initialDepositCalc.conditional_ovd_total==null?'N/A':money2(initialDepositCalc.conditional_ovd_total)}</b><small>CM005–CM006; not verified payable commission</small></div>
      </div>
      <div className="rr-product-table-wrap"><table className="rr-product-table"><thead><tr><th>Deposit amount slab</th><th>Transactions</th><th>CSPs</th><th>Deposit amount</th><th>e-KYC scenario</th><th>OVD scenario</th></tr></thead><tbody>
        {initialDepositSlabs.map(row=><tr key={row.slab_key}><td><b>{row.label}</b></td><td>{fmt(row.transactions)}</td><td>{fmt(row.unique_csps)}</td><td>{money2(row.deposit_amount)}</td><td>{money2(row.conditional_ekyc_commission)}</td><td>{money2(row.conditional_ovd_commission)}</td></tr>)}
        {initialDepositSlabs.length===0&&<tr><td colSpan="6" className="rr-no-data">Upload the current successful transaction file to calculate Initial Deposit slabs.</td></tr>}
      </tbody></table></div>
      <div className="rr-control-foot"><span><AlertTriangle size={14}/> Verified expected commission: <b>N/A until KYC/OVD evidence is available</b></span><span>Excluded from settlement variance and reconciliation KPI</span></div>
    </section>

    <section className="rr-settlement-bridge">
      <div className="rr-card">
        <div className="rr-card-head"><div><span className="rr-overline">BC SETTLEMENT BRIDGE</span><h3>Gross commission → penalty → net payable</h3><p>Direct control from the uploaded BC workbook. Penalty is shown separately and is never mixed into transaction commission reconciliation.</p></div><span className={`rr-status ${summary?.penalty_assessment?.is_verified?'good':'warn'}`}>{summary?.penalty_assessment?.is_verified?'Verified':'Evidence required'}</span></div>
        <div className="rr-bridge-grid">
          <div className="rr-financial-number"><span>BC gross commission</span><b>{grossCommission==null?'N/A':money2(grossCommission)}</b><small>Uploaded BC source control</small></div>
          <div className="rr-financial-number penalty"><span>Penalty / deduction</span><b>{penalty==null?'N/A':`−${money2(penalty)}`}</b><small>{summary?.penalty_assessment?.source || 'Penalty evidence required'}</small></div>
          <div className="rr-financial-number emphasis"><span>BC net payable</span><b>{netPayable==null?'N/A':money2(netPayable)}</b><small>Gross commission − verified penalty</small></div>
        </div>
        <div className="rr-control-foot"><span><ShieldCheck size={14}/> Workbook internal control: <b>{summary?.bc_workbook_internal_control_status || 'N/A'}</b></span><span>Transaction value: <b>{money2(transactionAmount)}</b></span></div>
      </div>
    </section>

    <section className="rr-card rr-product-commission-card">
      <div className="rr-card-head">
        <div><span className="rr-overline">PRODUCT-WISE COMMISSION</span><h3>Actual commission by product / service</h3><p>Directly grouped from the uploaded BC Commission source. Penalty is kept separate from product commission.</p></div>
        <span className="rr-status good">Source controlled</span>
      </div>
      <div className="rr-product-summary">
        <div className="rr-financial-number"><span>Total BC commission</span><b>{productGross==null?'N/A':money2(productGross)}</b><small>Gross amount reported by BC</small></div>
        <div className="rr-financial-number penalty"><span>Penalty / deduction</span><b>{productPenalty==null?'N/A':`−${money2(productPenalty)}`}</b><small>Excluded from product commission total</small></div>
        <div className="rr-financial-number emphasis"><span>Total commission after penalty</span><b>{productNet==null?'N/A':money2(productNet)}</b><small>Gross commission − verified penalty</small></div>
      </div>
      <div className="rr-product-table-wrap">
        <table className="rr-product-table"><thead><tr><th>#</th><th>Product / Service</th><th>Commission</th><th>Share of Gross</th><th>Classification</th></tr></thead>
          <tbody>{productRows.map((row,i)=><tr key={`${row.product}-${i}`}><td>{i+1}</td><td><b>{row.product}</b></td><td><strong>{money2(row.commission)}</strong></td><td>{Number(row.share_pct||0).toFixed(2)}%</td><td><span className={`rr-product-badge ${row.is_penalty?'penalty':'product'}`}>{row.is_penalty?'Penalty':'Product / Service'}</span></td></tr>)}
          {productRows.length===0&&<tr><td colSpan="5" className="rr-no-data">No product-wise commission data available from the current BC source.</td></tr>}</tbody>
        </table>
      </div>
      <div className="rr-control-foot"><span><ShieldCheck size={14}/> {fmt(productRows.filter(x=>!x.is_penalty).length)} product/service categories</span><span>Source total: <b>{productGross==null?'N/A':money2(productGross)}</b></span></div>
    </section>

    <section className="rr-card rr-type-reconciliation-card">
      <div className="rr-card-head">
        <div><span className="rr-overline">TRANSACTION TYPE RECONCILIATION</span><h3>Complete transaction-type control</h3><p>All successful transaction types are compared at CSP + transaction-type level. Count and commission controls use only comparable populations.</p></div>
        <button className="rr-text-btn" onClick={onExport}>Export full report <Download size={14}/></button>
      </div>
      <div className="rr-type-summary-strip">
        <div><span>Transaction types / controls</span><b>{fmt(typeTableCount)}</b></div>
        <div><span>Count matched</span><b>{fmt(Number(summary?.count_matched_groups||0))}</b></div>
        <div><span>Count mismatches</span><b className={countMismatch>0?'warn-text':''}>{fmt(countMismatch)}</b></div>
        <div><span>Missing commission</span><b className={missingCommission>0?'warn-text':''}>{fmt(missingCommission)}</b></div>
      </div>
      <div className="rr-type-table-wrap">
        <table className="rr-type-table"><thead><tr><th>Transaction Type</th><th>Success Txns</th><th>BC Count</th><th>Count Diff</th><th>Expected ₹</th><th>Actual ₹</th><th>Variance ₹</th><th>Status</th></tr></thead>
          <tbody>{[...visibleTypes].sort((a,b)=>{const av=Math.abs(Number(a.countVariance||0)); const bv=Math.abs(Number(b.countVariance||0)); return bv-av || Number(b.txns||0)-Number(a.txns||0)}).map((r,i)=>{
            const cd=Number(r.countVariance||0);
            const exp=r.type==='PASSBOOK PRINTING' ? (r.expected ?? null) : (r.verifiedExpected ?? r.expected);
            const act=r.actual;
            const gap=r.variance;
            const statusLabel=Math.abs(cd)>0 ? 'Count mismatch' : (act==null && Number(r.txns||0)>0 ? 'Missing commission' : (r.expectedStatus||'Review'));
            const statusClass=statusLabel==='Matched'?'good':statusLabel==='Count mismatch'||statusLabel==='Missing commission'?'warn':'neutral';
            return <tr key={r.type||i}><td><b>{r.type}</b><small>{r.type==='PASSBOOK PRINTING'?'CSP-wise passbook count control':`${fmt(r.amount)} transaction value`}</small></td><td>{fmt(r.txns)}</td><td>{r.reportBase==null?'N/A':fmt(r.reportBase)}</td><td className={Math.abs(cd)>0?'warn-text':''}>{r.countVariance==null?'N/A':(cd>0?`+${fmt(cd)}`:fmt(cd))}</td><td>{exp==null?(r.type==='INITIAL DEPOSIT'?'KYC/OVD required':r.type==='PASSBOOK PRINTING'?'Rate/geography unresolved':'N/A'):money2(exp)}</td><td>{act==null?'N/A':money2(act)}</td><td className={gap!=null&&Math.abs(Number(gap))>0.005?(Number(gap)>0?'warn-text':'good-text'):''}>{gap==null?(r.type==='INITIAL DEPOSIT'?'Conditional':r.type==='PASSBOOK PRINTING'?'Needs source/rate':'N/A'):signed(gap)}</td><td><span className={`rr-type-status ${statusClass}`}>{r.type==='INITIAL DEPOSIT'&&exp==null?'KYC/OVD evidence required':r.type==='PASSBOOK PRINTING'?(exp==null?'Rate/geography unresolved':'Provisional · cap unverified'):statusLabel}</span></td></tr>
          })}
          {showPrinterReimbursementInTypeTable && <tr key="passbook-printer-cost-reimbursement-control" className="rr-rural-monthly-control">
            <td><b>PASSBOOK PRINTER COST REIMBURSEMENT</b><small>SBI monthly reimbursement · ₹610 per active and deployed printer-month</small></td>
            <td>{printerReimbursementControl.actual_paid_printer_months == null ? 'N/A' : fmt(printerReimbursementControl.actual_paid_printer_months)}<small>BC-reported paid printer-months; not eligibility proof</small></td>
            <td>{printerReimbursementControl.actual_paid_printer_months == null ? 'N/A' : fmt(printerReimbursementControl.actual_paid_printer_months)}<small>reported paid units</small></td>
            <td>N/A<small>Monthly reimbursement, not a transaction count</small></td>
            <td>{printerReimbursementControl.amount == null ? 'Evidence required' : money2(printerReimbursementControl.amount)}</td>
            <td>{printerReimbursementControl.actual_amount == null ? 'N/A' : money2(printerReimbursementControl.actual_amount)}</td>
            <td>{printerReimbursementControl.amount == null || printerReimbursementControl.actual_amount == null ? 'N/A' : signed(Number(printerReimbursementControl.actual_amount) - Number(printerReimbursementControl.amount))}</td>
            <td><span className="rr-type-status warn">{printerReimbursementControl.status || 'EVIDENCE REQUIRED'}<small>Upload independent active/deployed printer roster</small></span></td>
          </tr>}
          {showRuralInTypeTable && <tr key="rural-commission-monthly-control" className="rr-rural-monthly-control">
            <td><b>RURAL COMMISSION</b><small>Monthly CSP incentive control · not a transaction count</small></td>
            <td>{ruralAvailable ? fmt(ruralGroups) : 'N/A'}<small>{ruralAvailable ? 'CSP controls' : (ruralCommission?.message || 'Upload current-period Rural CSP list')}</small></td>
            <td>{ruralAvailable ? fmt(ruralPaidCspCount) : 'N/A'}<small>{ruralAvailable ? 'paid CSPs' : 'Awaiting BC data'}</small></td>
            <td>N/A<small>Different measurement unit</small></td>
            <td>{!ruralAvailable || ruralExpectedAmount==null?'N/A':money2(ruralExpectedAmount)}</td>
            <td>{!ruralAvailable || ruralActualAmount==null?'N/A':money2(ruralActualAmount)}</td>
            <td>N/A<small>Eligibility/short-pay shown below</small></td>
            <td><span className={`rr-type-status ${ruralAvailable ? 'neutral' : 'warn'}`}>{ruralAvailable ? 'Separate monthly control' : (ruralCommission?.status || 'Rural source required')}</span></td>
          </tr>}
          {showWomenInTypeTable && <tr key="women-csp-incentive-control" className="rr-rural-monthly-control">
            <td><b>WOMEN CSP INCENTIVE</b><small>SBI Rule 24 · monthly CSP incentive, not a transaction count</small></td>
            <td>{fmt(summary?.women_csp_control_groups || 0)}<small>eligible/paid CSP controls</small></td>
            <td>{fmt(summary?.women_csp_matched_controls || 0)}<small>matched CSP controls</small></td>
            <td>N/A<small>Monthly incentive, not transaction count</small></td>
            <td>{summary?.women_csp_expected_total==null?'N/A':money2(summary.women_csp_expected_total)}</td>
            <td>{summary?.women_csp_actual_total==null?'N/A':money2(summary.women_csp_actual_total)}</td>
            <td>{summary?.women_csp_variance_total==null?'N/A':signed(summary.women_csp_variance_total)}</td>
            <td><span className={`rr-type-status ${summary?.women_csp_control_status==='READY' && Number(summary?.women_csp_control_groups||0)===Number(summary?.women_csp_matched_controls||0) ? 'good' : 'warn'}`}>{summary?.women_csp_control_status==='READY' ? `${fmt(summary?.women_csp_matched_controls||0)} matched / ${fmt(Math.max(0,Number(summary?.women_csp_control_groups||0)-Number(summary?.women_csp_matched_controls||0)))} exceptions` : (summary?.women_csp_control_status || 'Current-period source required')}</span></td>
          </tr>}
          {showTabInTypeTable && <tr key="tab-financial-transaction-incentive-control" className="rr-rural-monthly-control">
            <td><b>TAB FINANCIAL TRANSACTION INCENTIVE</b><small>SBI permanent rule · ₹5 per eligible transaction, m-ATM excluded, ₹1,000 per CSP/month cap</small></td>
            <td>{tabAvailable ? fmt(tabSummary.control_groups || 0) : 'N/A'}<small>{tabAvailable ? 'CSP-month controls' : (tabCommission?.message || 'Upload current-period TAB incentive CSP/count sheet')}</small></td>
            <td>{tabAvailable ? fmt(tabSummary.matched || 0) : 'N/A'}<small>{tabAvailable ? 'matched controls' : 'Awaiting TAB + BC sources'}</small></td>
            <td>N/A<small>Monthly incentive, not transaction count variance</small></td>
            <td>{!tabAvailable || tabSummary.expected_total==null ? 'N/A' : money2(tabSummary.expected_total)}</td>
            <td>{!tabAvailable || tabSummary.actual_total==null ? 'N/A' : money2(tabSummary.actual_total)}</td>
            <td>{!tabAvailable || tabSummary.variance_actual_minus_expected==null ? 'N/A' : signed(tabSummary.variance_actual_minus_expected)}</td>
            <td><span className={`rr-type-status ${tabAvailable && Number(tabSummary.matched||0)===Number(tabSummary.control_groups||0) ? 'good' : 'warn'}`}>{tabAvailable ? `${fmt(tabSummary.matched||0)} matched / ${fmt(Math.max(0,Number(tabSummary.control_groups||0)-Number(tabSummary.matched||0)))} exceptions` : (tabCommission?.status || 'TAB source required')}</span></td>
          </tr>}
          {showLoanLeadInTypeTable && <tr key="loan-lead-generation-control" className="rr-rural-monthly-control">
            <td><b>LOAN LEAD GENERATION</b><small>SBI commission on sanction limit · Home/Vehicle 0.50%, Mudra 0.25%, Personal/P-Segment Gold/Agri Gold 0.10% + GST</small></td>
            <td>{loanLeadAvailable ? fmt(loanLeadSummary.rows || 0) : 'N/A'}<small>{loanLeadAvailable ? `${fmt(loanLeadSummary.unique_lead_count || 0)} unique leads · ${(loanLeadSummary.periods || []).join(', ')}` : (loanLeadCommission?.message || 'Upload current-period Loan Lead sheet')}</small></td>
            <td>{loanLeadAvailable ? fmt(loanLeadSummary.count_matched_groups || 0) : 'N/A'}<small>matched CSP + product count groups</small></td>
            <td>N/A<small>Lead count is not a transaction count</small></td>
            <td>{!loanLeadAvailable || loanLeadSummary.expected_base_commission_total==null ? 'N/A' : money2(loanLeadSummary.expected_base_commission_total)}<small>{loanLeadAvailable ? `${fmt(loanLeadSummary.unresolved_sanction_limit_rows || 0)} sanction limits missing` : ''}</small></td>
            <td>{!loanLeadAvailable || loanLeadSummary.actual_commission_total==null ? 'N/A' : money2(loanLeadSummary.actual_commission_total)}<small>{loanLeadAvailable ? `${fmt(loanLeadSummary.actual_commission_rows || 0)} actual payout rows · ${(loanLeadSummary.commission_periods_detected || []).join(', ')}` : 'Matching BC Report required'}</small></td>
            <td>N/A<small>Amount variance blocked until sanction base + GST treatment verified</small></td>
            <td><span className={`rr-type-status ${loanLeadAvailable && loanLeadCommission?.status==='READY' ? 'good' : 'warn'}`}>{loanLeadAvailable ? `${loanLeadSummary.actual_payout_status || 'PAYOUT_UNVERIFIED'} · ${fmt(loanLeadSummary.count_matched_groups || 0)} count matched · ${fmt(loanLeadSummary.match_status_counts?.LEAD_PAYOUT_COUNT_MISMATCH || 0)} count mismatches · ${fmt(loanLeadSummary.match_status_counts?.ACTUAL_WITHOUT_ELIGIBLE_LEAD || 0)} actual-only groups` : (loanLeadCommission?.status || 'Source required')}</span></td>
          </tr>}
          {showMatmInTypeTable && <tr key="matm-cash-incentive-control" className="rr-rural-monthly-control">
            <td><b>MATM CASH TRANSACTIONS INCENTIVE</b><small>SBI CM060 · ₹3 per financial transaction, capped at ₹1,000 per CSP/month</small></td>
            <td>{matmAvailable ? fmt(matmSummary.source_csp_controls || 0) : 'N/A'}<small>{matmAvailable ? `${fmt(matmSummary.source_transaction_count || 0)} source transactions` : (matmCommission?.message || 'Upload current-period m-ATM CSP/count sheet')}</small></td>
            <td>{matmAvailable ? fmt(matmSummary.matched || 0) : 'N/A'}<small>{matmAvailable ? `${fmt(matmSummary.control_groups || 0)} CSP controls` : 'Awaiting m-ATM + BC sources'}</small></td>
            <td>{matmAvailable ? fmt(matmSummary.bank_recognized_transactions ?? 0) : "N/A"}<small>{matmAvailable ? "BC-recognized transactions" : "Monthly incentive control unavailable"}</small></td>
            <td>{!matmAvailable || matmSummary.expected_total==null ? 'N/A' : money2(matmSummary.expected_total)}</td>
            <td>{!matmAvailable || matmSummary.actual_total==null ? 'N/A' : money2(matmSummary.actual_total)}</td>
            <td>{!matmAvailable || matmSummary.variance_actual_minus_expected==null ? 'N/A' : signed(matmSummary.variance_actual_minus_expected)}</td>
            <td><span className={`rr-type-status ${matmAvailable && Number(matmSummary.matched||0)===Number(matmSummary.control_groups||0) && Number(matmSummary.count_mismatches||0)===0 ? 'good' : 'warn'}`}>{matmAvailable ? `${fmt(matmSummary.matched||0)} commission matched / ${fmt(Math.max(0,Number(matmSummary.control_groups||0)-Number(matmSummary.matched||0)))} commission exceptions` : (matmCommission?.status || 'm-ATM source required')}<small>{matmAvailable ? `${fmt(matmSummary.count_matched||0)} count matched · ${fmt(matmSummary.count_mismatches||0)} count mismatches · source ${fmt(matmSummary.source_transaction_count||0)} vs BC ${fmt(matmSummary.bank_recognized_transactions||0)}` : 'Upload matching-period m-ATM source and BC Report'}</small></span></td>
          </tr>}
          {showDfsInTypeTable && <tr key="dfs-priorities-incentive-control" className="rr-rural-monthly-control">
            <td><b>DFS PRIORITIES INCENTIVE</b><small>Monthly CSP slab incentive · separate financial control</small></td>
            <td>{dfsAvailable ? fmt(dfsSummary.source_csp_count || 0) : 'N/A'}<small>{dfsAvailable ? 'source CSPs' : (dfsCommission?.message || 'Upload current-period DFS slab sheet')}</small></td>
            <td>{dfsAvailable ? fmt(dfsSummary.bc_csp_count || 0) : 'N/A'}<small>{dfsAvailable ? 'BC DFS CSPs' : 'Awaiting matching BC report'}</small></td>
            <td>N/A<small>Monthly incentive, not transaction count</small></td>
            <td>{!dfsAvailable || dfsExpected==null ? 'N/A' : money2(dfsExpected)}</td>
            <td>{!dfsAvailable || dfsActual==null ? 'N/A' : money2(dfsActual)}</td>
            <td>{!dfsAvailable || dfsVariance==null ? 'N/A' : signed(dfsVariance)}</td>
            <td><span className={`rr-type-status ${dfsAvailable && Number(dfsSummary.exceptions||0)===0 ? 'good' : 'warn'}`}>{dfsAvailable ? `${fmt(dfsMatched)} matched / ${fmt(dfsSummary.exceptions||0)} exceptions` : (dfsCommission?.status || 'DFS source required')}</span></td>
          </tr>}
          </tbody>
        </table>
        {visibleTypes.length===0&&!showRuralInTypeTable&&!showDfsInTypeTable&&!showWomenInTypeTable&&!showTabInTypeTable&&!showLoanLeadInTypeTable&&!showPrinterReimbursementInTypeTable&&!showMatmInTypeTable&&<div className="rr-no-data">No transaction-type data available for the selected filters.</div>}
      </div>
      {showLoanLeadInTypeTable && loanLeadAvailable && (loanLeadCommission?.match_rows || []).length > 0 && <div className="rr-loan-lead-detail rr-type-table-wrap">
        <div className="rr-card-head"><div><span className="rr-overline">LOAN LEAD GENERATION DETAILS</span><h3>CSP + loan product payout matching</h3><p>Actual BC payout is matched to eligible post-sanction leads by CSP and product. Amount variance stays N/A until sanction limit and GST treatment are evidenced.</p></div></div>
        <table className="rr-type-table"><thead><tr><th>Period</th><th>CSP ID</th><th>Loan product</th><th>Eligible leads</th><th>BC units</th><th>Expected base ₹</th><th>Actual ₹</th><th>Variance ₹</th><th>Match status</th></tr></thead>
          <tbody>{loanLeadCommission.match_rows.map((r,i)=><tr key={`${r.period}-${r.csp_id}-${r.loan_product}-${i}`}><td>{r.period || 'N/A'}</td><td>{r.csp_id}</td><td>{r.loan_product}</td><td>{fmt(r.eligible_sanctioned_leads || 0)}<small>{r.lead_ids || 'No eligible source lead'}</small></td><td>{r.actual_reported_units==null?'N/A':fmt(r.actual_reported_units)}</td><td>{r.expected_base_commission==null?'N/A':money2(r.expected_base_commission)}</td><td>{r.actual_commission==null?'N/A':money2(r.actual_commission)}</td><td>{r.variance==null?'N/A':signed(r.variance)}</td><td><span className={`rr-type-status ${String(r.status).startsWith('COUNT_MATCH')?'neutral':'warn'}`}>{r.status}</span></td></tr>)}</tbody>
        </table>
      </div>}
      {showDfsInTypeTable && dfsAvailable && (dfsCommission?.rows || []).length > 0 && <div className="rr-loan-lead-detail rr-type-table-wrap">
        <div className="rr-card-head"><div><span className="rr-overline">DFS PRIORITIES INCENTIVE DETAILS</span><h3>CSP-wise slab payout matching</h3><p>Expected = SBI slab amount for the slab in the DFS sheet; actual = DFS PRIORITIES INCENTIVE paid in the BC report. Exceptions are listed first.</p></div></div>
        <table className="rr-type-table"><thead><tr><th>CSP ID</th><th>CSP name</th><th>Slab</th><th>Expected ₹</th><th>BC paid ₹</th><th>Difference ₹</th><th>Status</th></tr></thead>
          <tbody>{[...dfsCommission.rows].sort((a,b)=>(a.status==='MATCHED')-(b.status==='MATCHED') || String(a.csp_id||'').localeCompare(String(b.csp_id||''))).map((r,i)=><tr key={`dfs-${r.csp_id||'unresolved'}-${i}`}>
            <td>{r.csp_id || <small>Not identified</small>}</td>
            <td>{r.csp_name || r.bc_csp_name || '—'}{r.bc_csp_name && r.csp_name && r.bc_csp_name.replace(/\s+/g,' ').toUpperCase() !== String(r.csp_name).replace(/\s+/g,' ').toUpperCase() && <small>BC: {r.bc_csp_name}</small>}</td>
            <td>{r.slab ? String(r.slab).replace('SLAB-','Slab-') : '—'}</td>
            <td>{r.expected_incentive==null ? 'N/A' : money2(r.expected_incentive)}</td>
            <td>{r.actual_commission==null ? 'N/A' : money2(r.actual_commission)}</td>
            <td>{r.variance_actual_minus_expected==null ? 'N/A' : signed(r.variance_actual_minus_expected)}</td>
            <td><span className={`rr-type-status ${r.status==='MATCHED' ? 'good' : 'warn'}`}>{String(r.status||'').replaceAll('_',' ').toLowerCase()}</span></td>
          </tr>)}</tbody>
        </table>
      </div>}
      <div className="rr-card-foot"><span>Showing all comparable and non-comparable transaction types from the current reconciliation run.</span><button className="rr-btn rr-secondary small" onClick={onShowFilters}><Filter size={14}/> Refine filters</button></div>
    </section>

    <section className="rr-control-summary-grid">
      <div className="rr-card"><div className="rr-card-head"><div><span className="rr-overline">EXCEPTION BREAKDOWN</span><h3>Why groups are not reconciled</h3><p>Use these categories to prioritize investigation across all transaction types.</p></div></div><div className="rr-exception-summary">
        <div><span>Count mismatch</span><b>{fmt(countMismatch)}</b><small>CSP + transaction-type population</small></div>
        <div><span>Missing commission</span><b>{fmt(missingCommission)}</b><small>No numeric BC commission for a matched population</small></div>
        <div><span>Mapping pending</span><b>{fmt(Number(summary?.pending_mapping_groups||0))}</b><small>Rule/mapping approval required</small></div>
        <div><span>Unmapped</span><b>{fmt(unmapped)}</b><small>No approved transaction mapping</small></div>
      </div></div>
      <div className="rr-card"><div className="rr-card-head"><div><span className="rr-overline">CSP DRILL-DOWN</span><h3>Detailed investigation</h3><p>Review control totals, transaction-type evidence and approved-rule coverage here; export the audit workbook for detailed follow-up.</p></div></div><div className="rr-drill-links"><button onClick={onExport}><Download size={15}/> Audit export <ArrowUpRight size={13}/></button></div></div>
    </section>

    <section className="rr-two-col lower">
      <div className="rr-card">
        <div className="rr-card-head"><div><span className="rr-overline">TRANSACTION MIX</span><h3>Successful transaction population</h3><p>Source-of-truth transaction types from the uploaded successful file.</p></div></div>
        <div className="rr-type-list">{sourceRows.map(r=><div className="rr-type-row" key={r.type}><div className="rr-type-label"><b>{r.type}</b><span>{fmt(r.txns)} txns · {fmt(r.csps)} CSPs</span></div><div className="rr-type-track"><i style={{width:`${Math.max(3,Math.min(100,(Number(r.txns||0)/Math.max(1,Number(sourceRows[0]?.txns||0)))*100))}%`}}/></div><strong>{sourceTypeTotal?((Number(r.txns||0)/sourceTypeTotal)*100).toFixed(1):'0.0'}%</strong></div>)}{sourceRows.length===0&&<div className="rr-no-data">No source transaction-type data available.</div>}</div>
      </div>
      <div className="rr-card">
        <div className="rr-card-head"><div><span className="rr-overline">CONTROL READINESS</span><h3>Settlement readiness</h3><p>Controls that determine whether this run is safe to review.</p></div></div>
        <div className="rr-readiness"><div className="rr-readiness-score"><b>{health}</b><span>Overall reconciliation status</span></div><div className="rr-check-list"><div><CheckCircle2 size={16}/><span>Successful source validated</span><b>PASS</b></div><div className={countMismatch>0?'attention':''}>{countMismatch>0?<AlertTriangle size={16}/>:<CheckCircle2 size={16}/>}<span>Count-level reconciliation</span><b>{countMismatch>0?'REVIEW':'PASS'}</b></div><div className={rateMissing>0||unmapped>0?'attention':''}>{rateMissing>0||unmapped>0?<AlertTriangle size={16}/>:<CheckCircle2 size={16}/>}<span>Rule / mapping coverage</span><b>{rateMissing>0||unmapped>0?'REVIEW':'PASS'}</b></div><div className={auditFail>0?'attention':''}>{auditFail>0?<AlertTriangle size={16}/>:<CheckCircle2 size={16}/>}<span>Condition audit</span><b>{auditFail>0?'REVIEW':auditOk?'PASS':'N/A'}</b></div></div></div>
      </div>
    </section>

    <section className="rr-card rr-audit-banner"><div className="rr-audit-icon"><ShieldCheck size={21}/></div><div><span className="rr-overline">AUDITABILITY</span><h3>Every number remains traceable to the uploaded sources and approved SBI rules.</h3><p>Use Reconciliation and Audit & Reports for source fingerprints, rule evidence and exportable control totals.</p></div><button className="rr-btn rr-primary" onClick={onExport}><Download size={15}/> Export audit workbook</button></section>
    <DfsReconciliationPanel historicalData={viewingHistory ? dfsCommission : null} viewingHistory={viewingHistory} />
    <WomenCspIncentivePanel historicalData={historicalWomenCspIncentive} viewingHistory={viewingHistory} />
    <PassbookPrintingPanel data={passbookCommission} viewingHistory={viewingHistory} />
    <MatmIncentivePanel historicalData={viewingHistory ? matmCommission : null} viewingHistory={viewingHistory} />
  </div>;
}

function ExecutiveKpi({icon:Icon,label,value,meta,tone='slate',warning=false}){return <div className={`exec-kpi ${tone}`}><div className="exec-kpi-top"><div className="exec-icon"><Icon size={17}/></div>{warning?<span className="kpi-warning">Needs review</span>:<ArrowUpRight size={14} className="kpi-arrow"/>}</div><div className="exec-label">{label}</div><div className="exec-value">{value}</div><div className="exec-meta">{meta}</div></div>}
function ControlLine({icon:Icon,title,text,good=false}){return <div className="control-line"><div className={`control-icon ${good?'good':''}`}><Icon size={14}/></div><div><strong>{title}</strong><span>{text}</span></div></div>}

function AnalysisSearch({search,setSearch}){return <div className="rr-analysis-search"><Search size={14}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search CSP or transaction type"/>{search&&<button className="rr-text-btn" onClick={()=>setSearch('')}><X size={13}/></button>}</div>}

function PageToolbar({overline,title,text,children}){return <div className="rr-analysis-toolbar"><div><span className="rr-overline">{overline}</span><h2>{title}</h2><p>{text}</p></div>{children&&<div className="rr-toolbar-actions">{children}</div>}</div>}
function MiniStats({items}){return <div className="rr-mini-grid">{items.map(([label,value,tone])=><div key={label} className={tone?`rr-mini-${tone}`:''}><span>{label}</span><b>{value}</b></div>)}</div>}
function SearchField({value,onChange,onSubmit,placeholder,onClear}){return <div className="rr-analysis-search"><Search size={14}/><input value={value} onChange={e=>onChange(e.target.value)} onKeyDown={e=>e.key==='Enter'&&onSubmit&&onSubmit()} placeholder={placeholder}/>{value&&<button className="rr-text-btn" onClick={onClear||(()=>onChange(''))}><X size={13}/></button>}</div>}
function Pager({from,to,total,canPrev,canNext,onPrev,onNext}){return <div className="rr-pager"><span>Showing <b>{from}</b> to <b>{to}</b> of <b>{total}</b></span><div><button className="rr-btn rr-secondary small" disabled={!canPrev} onClick={onPrev}>Previous</button><button className="rr-btn rr-secondary small" disabled={!canNext} onClick={onNext}>Next</button></div></div>}
function Notice({tone='info',icon:Icon=AlertTriangle,title,children}){return <div className={`rr-notice ${tone}`}><Icon size={16}/><div><strong>{title}</strong><span>{children}</span></div></div>}

function useFacets(rows,defs){
  const [vals,setVals]=useState(()=>Object.fromEntries(defs.map(d=>[d.key,d.all])));
  const match=(r,skip)=>defs.every(d=>d.key===skip||vals[d.key]===d.all||d.get(r)===vals[d.key]);
  const filtered=useMemo(()=>rows.filter(r=>match(r,null)),[rows,vals]);
  const groups=defs.map(d=>{
    const base=rows.filter(r=>match(r,d.key)); const counts={}; base.forEach(r=>{const v=d.get(r);counts[v]=(counts[v]||0)+1});
    const allCounts={}; rows.forEach(r=>{const v=d.get(r);allCounts[v]=(allCounts[v]||0)+1});
    const list=d.opts||Object.keys(allCounts).sort((a,b)=>allCounts[b]-allCounts[a]).map(v=>[v,v]);
    return {key:d.key,label:d.label,all:d.all,select:d.select,value:vals[d.key],set:v=>setVals(o=>({...o,[d.key]:v})),
      options:[[d.all,d.allLabel||"All",base.length]].concat(list.map(([v,l])=>[v,l,counts[v]||0]))};
  });
  const reset=()=>setVals(Object.fromEntries(defs.map(d=>[d.key,d.all])));
  return {groups,filtered,reset,active:groups.filter(g=>g.value!==g.all).length};
}
function FilterBar({groups,total,shown,extraActive,onReset}){
  const active=groups.filter(g=>g.value!==g.all);
  return <div className="rr-fbar">
    {groups.map(g=><div className="rr-fgroup" key={g.key}><span className="rr-flabel">{g.label}</span>
      {g.select
        ? <select value={g.value} onChange={e=>g.set(e.target.value)}>{g.options.map(([v,l,c])=><option key={v} value={v}>{l} ({fmt(c)})</option>)}</select>
        : <div className="rr-chips">{g.options.map(([v,l,c])=><button key={v} className={g.value===v?"on":c===0?"zero":""} disabled={c===0&&g.value!==v} onClick={()=>g.set(v)}>{l}<em>{fmt(c)}</em></button>)}</div>}
    </div>)}
    <div className="rr-fsum"><span>Showing <b>{fmt(shown)}</b> of <b>{fmt(total)}</b></span>
      {active.map(g=>{const o=g.options.find(x=>x[0]===g.value);return <button key={g.key} className="rr-chip-x" onClick={()=>g.set(g.all)}>{g.label}: {o?o[1]:g.value} <X size={11}/></button>})}
      {(active.length>0||extraActive)&&<button className="rr-text-btn rr-clear" onClick={onReset}>Clear all filters</button>}
    </div>
  </div>
}
const DIFF_OPTS=[["more","File has more"],["less","Bank has more"],["same","Same count"],["none","Not in bank report"]];
const diffKind=(file,bank)=>bank==null?"none":file>bank?"more":file<bank?"less":"same";

function CspTypeCountsView({snapshotRows=null,monthLabel=""}){
  const [rows,setRows]=useState(null), [error,setError]=useState(""), [search,setSearch]=useState(""), [offset,setOffset]=useState(0), [view,setView]=useState("csp");
  const limit=100;
  useEffect(()=>{if(snapshotRows){setError("");setRows(snapshotRows);return}let live=true;(async()=>{try{const r=await fetch(`${API_BASE}/api/reconciliation/csp-type`);const d=await r.json();if(!r.ok)throw new Error(d.detail||"Run the reconciliation first.");if(live)setRows(Array.isArray(d)?d:[])}catch(e){if(live)setError(e.message||"The agent-wise counts could not be loaded. Run the reconciliation first.")}})();return()=>{live=false}},[snapshotRows]);
  const all=useMemo(()=>(rows||[]).map(r=>{const file=Number(r.successful_transactions||0), bank=r.report_base==null?null:Number(r.report_base);return {csp:r.csp_id,type:r.transaction_type,file,bank,diff:bank==null?null:file-bank,kind:diffKind(file,bank),status:r.reconciliation_status||"-"}}).filter(r=>r.file>0||r.bank>0),[rows]);
  const cspRows=useMemo(()=>{const m=new Map();all.forEach(r=>{let c=m.get(r.csp);if(!c){c={csp:r.csp,file:0,bank:0,types:0,differ:0,notInBank:0};m.set(r.csp,c)}
    if(r.bank==null){c.notInBank+=r.file}else{c.file+=r.file;c.bank+=r.bank;c.types++;if(r.diff!==0)c.differ++}});
    return [...m.values()].map(c=>({...c,diff:c.types?c.file-c.bank:null,kind:c.types?diffKind(c.file,c.bank):"none"}))},[all]);
  const q=search.trim().toLowerCase();
  const cspSearched=useMemo(()=>cspRows.filter(r=>!q||String(r.csp).toLowerCase().includes(q)),[cspRows,q]);
  const typeSearched=useMemo(()=>all.filter(r=>!q||`${r.csp} ${r.type}`.toLowerCase().includes(q)),[all,q]);
  const fc=useFacets(cspSearched,[{key:"kind",label:"Count",all:"all",allLabel:"All agents",opts:DIFF_OPTS.map(([k,l])=>k==="none"?[k,"No comparison possible"]:[k,l]),get:r=>r.kind}]);
  const ft=useFacets(typeSearched,[
    {key:"type",label:"Product",all:"all",allLabel:"All products",select:true,get:r=>r.type},
    {key:"kind",label:"Count",all:"all",allLabel:"All",opts:DIFF_OPTS,get:r=>r.kind},
    {key:"status",label:"Result",all:"all",allLabel:"All results",get:r=>r.status},
  ]);
  const byCsp=view==="csp", f=byCsp?fc:ft;
  const shown=useMemo(()=>[...f.filtered].sort((a,b)=>Math.abs(b.diff??b.file)-Math.abs(a.diff??a.file)),[f.filtered]);
  useEffect(()=>setOffset(0),[search,f.filtered,view]);
  const compared=all.filter(r=>r.bank!=null), cspCompared=cspRows.filter(r=>r.types>0);
  const sum=(a,k)=>a.reduce((t,r)=>t+(Number(r[k])||0),0);
  const csv=()=>{const head=byCsp?["Agent code","Transactions in successful sheet","Transactions in bank report","Difference (sheet minus bank)","Transaction types with a difference","Sheet transactions of types missing in bank report"]:["Agent code","Transaction type","Transactions in successful sheet","Transactions in bank report","Difference (sheet minus bank)","Result"];
    const lines=[head.join(",")].concat(shown.map(r=>(byCsp?[r.csp,r.file,r.bank,r.diff??"",r.differ,r.notInBank]:[r.csp,`"${String(r.type).replace(/"/g,'""')}"`,r.file,r.bank??"",r.diff??"",r.status]).join(",")));
    const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([lines.join("\n")],{type:"text/csv"}));a.download=byCsp?"csp_wise_transaction_count_difference.csv":"csp_and_type_wise_transaction_counts.csv";a.click()};
  const page=shown.slice(offset,offset+limit);
  const diffCell=d=><td className={d?'warn-text':''}>{d==null?"N/A":(d>0?"+":"")+fmt(d)}</td>;
  return <div className="rr-analysis-page">
    <PageToolbar overline="CSP-WISE COUNTS" title={`${byCsp?"Transaction count difference by CSP":"Transaction counts by CSP and type"}${monthLabel?`: ${monthLabel}`:""}`} text={byCsp?"For every CSP (agent): how many successful transactions are in the successful sheet, how many the bank (actual) report shows, and the difference. Largest differences first. Click 'See types' to see which transaction type causes it.":"For every CSP and transaction type: transactions in the successful sheet, in the bank (actual) report, and the difference. Largest differences first."}>
      <div className="rr-seg"><button className={byCsp?"on":""} onClick={()=>setView("csp")}>By CSP</button><button className={!byCsp?"on":""} onClick={()=>setView("type")}>By CSP and type</button></div>
      <SearchField value={search} onChange={setSearch} placeholder={byCsp?"CSP code":"CSP code or transaction type"}/>
      <button className="rr-btn rr-secondary small" onClick={csv} disabled={!shown.length}><Download size={14}/> Download this list</button>
    </PageToolbar>
    {error&&<Notice tone="warn" title="Counts unavailable">{error}</Notice>}
    {rows&&(byCsp
      ?<MiniStats items={[["CSPs compared",fmt(cspCompared.length)],["CSPs with a difference",fmt(cspCompared.filter(r=>r.diff!==0).length),"warn"],["Transactions in successful sheet",fmt(sum(cspCompared,"file"))],["Transactions in bank report",fmt(sum(cspCompared,"bank"))]]}/>
      :<MiniStats items={[["CSP and type pairs compared",fmt(compared.length)],["Pairs with a difference",fmt(compared.filter(r=>r.diff!==0).length),"warn"],["Transactions in successful sheet",fmt(sum(compared,"file"))],["Transactions in bank report",fmt(sum(compared,"bank"))]]}/>)}
    {rows&&<FilterBar groups={f.groups} total={byCsp?cspRows.length:all.length} shown={shown.length} extraActive={!!search} onReset={()=>{f.reset();setSearch("")}}/>}
    <div className="rr-analysis-table-wrap">{byCsp
      ?<table className="rr-analysis-table"><thead><tr><th>CSP</th><th>In successful sheet</th><th>In bank report</th><th>Difference (sheet minus bank)</th><th>Types with a difference</th><th>Types missing in bank report (sheet transactions)</th><th></th></tr></thead><tbody>{page.map((r,i)=><tr key={`${r.csp}-${i}`}><td><b>{r.csp}</b></td><td>{fmt(r.file)}</td><td>{r.types?fmt(r.bank):"Not in bank report"}</td>{diffCell(r.diff)}<td>{r.types?`${fmt(r.differ)} of ${fmt(r.types)}`:"N/A"}</td><td>{r.notInBank?fmt(r.notInBank):"-"}</td><td><button className="rr-text-btn" onClick={()=>{setSearch(String(r.csp));setView("type")}}>See types</button></td></tr>)}</tbody></table>
      :<table className="rr-analysis-table"><thead><tr><th>CSP</th><th>Transaction type</th><th>In successful sheet</th><th>In bank report</th><th>Difference (sheet minus bank)</th><th>Result</th></tr></thead><tbody>{page.map((r,i)=><tr key={`${r.csp}-${r.type}-${i}`}><td><b>{r.csp}</b></td><td>{r.type}</td><td>{fmt(r.file)}</td><td>{r.bank==null?"Not in bank report":fmt(r.bank)}</td>{diffCell(r.diff)}<td><span className={`rr-type-status ${r.status==='MATCH'?'good':'warn'}`}>{r.status}</span></td></tr>)}</tbody></table>}
      {rows&&shown.length===0&&<div className="rr-analysis-empty">Nothing matches these filters. Use "Clear all filters".</div>}{!rows&&!error&&<div className="rr-analysis-empty">Loading...</div>}</div>
    {rows&&<Notice tone="info" icon={ShieldCheck} title="How the difference is counted">Only transaction types that the bank report also lists are compared. Sheet transactions of types the bank report does not list are shown separately, not as a difference. A positive difference means the successful sheet has more transactions than the bank report.</Notice>}
    {shown.length>0&&<Pager from={offset+1} to={Math.min(offset+limit,shown.length)} total={fmt(shown.length)} canPrev={offset>0} canNext={offset+limit<shown.length} onPrev={()=>setOffset(Math.max(0,offset-limit))} onNext={()=>setOffset(offset+limit)}/>}
  </div>
}

function ExceptionCenterView({exceptions,onExport,search,setSearch}){
  const f=useFacets(exceptions,[{key:"reason",label:"Reason",all:"all",allLabel:"All reasons",select:true,get:r=>String(r.reason||"Exception").replaceAll('_',' ')},{key:"status",label:"Status",all:"all",get:r=>r.status||"Open"},{key:"severity",label:"Severity",all:"all",get:r=>r.severity||"Medium"},{key:"type",label:"Product",all:"all",allLabel:"All products",select:true,get:r=>r.type}]);
  const rows=[...f.filtered].sort((a,b)=>Math.abs(Number(b.variance||0))-Math.abs(Number(a.variance||0)));
  return <div className="rr-analysis-page">
    <div className="rr-analysis-toolbar"><div><span className="rr-overline">EXCEPTION CENTER</span><h2>All reconciliation exceptions</h2><p>Investigate source-count, mapping, rule and commission exceptions without changing the underlying financial result.</p></div><div style={{display:'flex',gap:8}}><AnalysisSearch search={search} setSearch={setSearch}/><button className="rr-btn rr-secondary small" onClick={onExport}><Download size={14}/> Export</button></div></div>
    <FilterBar groups={f.groups} total={exceptions.length} shown={rows.length} onReset={f.reset}/>
    <div className="rr-analysis-table-wrap"><table className="rr-analysis-table"><thead><tr><th>Exception</th><th>CSP</th><th>Transaction Type</th><th>Transactions</th><th>Count Diff</th><th>Variance</th><th>Reason</th><th>Status</th></tr></thead><tbody>{rows.map((r,i)=><tr key={r.id||i}><td><b>{r.id}</b></td><td>{r.csp}</td><td>{r.type}</td><td>{fmt(r.txns)}</td><td>{r.reportBase==null?'N/A':fmt(Number(r.txns||0)-Number(r.reportBase||0))}</td><td>{r.variance==null?'N/A':signedMoney(r.variance)}</td><td>{r.reason}</td><td><span className={`rr-type-status ${String(r.status).toLowerCase()==='resolved'?'good':'warn'}`}>{r.status||'Open'}</span></td></tr>)}</tbody></table>{rows.length===0&&<div className="rr-analysis-empty">No exceptions match the current search.</div>}</div>
  </div>
}

function CspAnalysisView({rows,search,setSearch,onExport}){
  const f=useFacets(rows,[{key:"status",label:"Result",all:"all",get:r=>r.status||"-"},{key:"money",label:"Amount",all:"all",opts:[["gap","Has amount difference"],["ok","No amount difference"],["na","Not comparable"]],get:r=>r.variance==null?"na":Math.abs(Number(r.variance))>=0.01?"gap":"ok"},{key:"count",label:"Count",all:"all",opts:[["diff","Count differs"],["same","Count same"]],get:r=>Number(r.countVariance||0)!==0?"diff":"same"}]);
  const data=[...f.filtered].filter(r=>!search||`${r.csp} ${r.name}`.toLowerCase().includes(search.toLowerCase())).sort((a,b)=>Math.abs(Number(b.variance||0))-Math.abs(Number(a.variance||0)));
  return <div className="rr-analysis-page">
    <div className="rr-analysis-toolbar"><div><span className="rr-overline">CSP ANALYSIS</span><h2>CSP-wise reconciliation</h2><p>Financial variance and population controls for every CSP in the current reconciliation run.</p></div><div style={{display:'flex',gap:8}}><AnalysisSearch search={search} setSearch={setSearch}/><button className="rr-btn rr-secondary small" onClick={onExport}><Download size={14}/> Export</button></div></div>
    <FilterBar groups={f.groups} total={rows.length} shown={data.length} extraActive={!!search} onReset={()=>{f.reset();setSearch('')}}/>
    <div className="rr-analysis-table-wrap"><table className="rr-analysis-table"><thead><tr><th>CSP</th><th>Successful Txns</th><th>Transaction Amount</th><th>Expected ₹</th><th>Actual ₹</th><th>Variance ₹</th><th>Count Diff</th><th>Status</th></tr></thead><tbody>{data.map((r,i)=><tr key={r.csp||i}><td><b>{r.csp}</b></td><td>{fmt(r.txns)}</td><td>{money0(r.amount)}</td><td>{r.expected==null?'N/A':money2(r.expected)}</td><td>{r.actual==null?'N/A':money2(r.actual)}</td><td>{r.variance==null?'N/A':signedMoney(r.variance)}</td><td>{r.countVariance==null?'N/A':fmt(r.countVariance)}</td><td><span className={`rr-type-status ${r.status==='Reconciled'?'good':r.status==='Exception'?'warn':'neutral'}`}>{r.status}</span></td></tr>)}</tbody></table>{data.length===0&&<div className="rr-analysis-empty">No CSP data matches the current search.</div>}</div>
  </div>
}

function TransactionAnalysisView({rows,socialSecurity,search,setSearch,onExport}){
  const f=useFacets(rows,[{key:"calc",label:"Calculation",all:"all",get:r=>String(r.expectedStatus||"-")},{key:"count",label:"Count",all:"all",opts:[["diff","Count differs"],["same","Count same"],["na","Not comparable"]],get:r=>r.countVariance==null?"na":Number(r.countVariance)!==0?"diff":"same"}]);
  const data=[...f.filtered].filter(r=>!search||r.type.toLowerCase().includes(search.toLowerCase())).sort((a,b)=>Number(b.txns||0)-Number(a.txns||0));
  const ssRows=socialSecurity?.rows||[];
  const ssTotal=socialSecurity?.total;
  return <div className="rr-analysis-page">
    <div className="rr-analysis-toolbar"><div><span className="rr-overline">TRANSACTION ANALYSIS</span><h2>All transaction types</h2><p>Complete transaction-type-wise view of source population, BC population, commission and variance.</p></div><div style={{display:'flex',gap:8}}><AnalysisSearch search={search} setSearch={setSearch}/><button className="rr-btn rr-secondary small" onClick={onExport}><Download size={14}/> Export</button></div></div>
    <FilterBar groups={f.groups} total={rows.length} shown={data.length} extraActive={!!search} onReset={()=>{f.reset();setSearch('')}}/>
    {socialSecurity&&!socialSecurity.available&&<div className="rr-card" style={{marginBottom:16}}><div className="rr-card-head"><div><span className="rr-overline">PMJJBY / PMSBY CONTROL</span><h3>Social-security reconciliation not ready</h3><p>{socialSecurity.message || 'Upload the current-period scheme source and matching-period BC commission report.'}</p></div><span className="rr-type-status warn">{socialSecurity.status || 'NOT READY'}</span></div></div>}
    {socialSecurity?.available&&<div className="rr-card" style={{marginBottom:16}}><div className="rr-card-head"><div><span className="rr-overline">PMJJBY / PMSBY CONTROL</span><h3>Authoritative current-period social-security reconciliation</h3><p>CSP-wise source workbook for the current uploaded period, matched against the BC commission population using the approved SBI rates.</p></div><span className="rr-status warn">BC excess ₹{fmt(ssTotal?.commission_difference_bc_minus_expected||0)}</span></div><div className="rr-mini-grid"><div><span>Valid-CSP source transactions</span><b>{fmt(ssTotal?.source_transactions)}</b></div><div><span>BC transactions (all valid keys)</span><b>{fmt(ssTotal?.bc_transactions)}</b></div><div><span>Expected commission (valid CSPs)</span><b>{money2(ssTotal?.expected_commission)}</b></div><div><span>Actual commission (matched-key population)</span><b>{money2(ssTotal?.actual_commission)}</b></div></div>{socialSecurity.full_source_control&&<div className="rr-mini-grid" style={{marginTop:10}}><div><span>Full-source expected (indicative)</span><b>{money2(socialSecurity.full_source_control.full_source_expected_commission_indicative)}</b></div><div><span>Unresolved source enrollments</span><b>{fmt(socialSecurity.full_source_control.unresolved_source_enrollments)}</b></div><div><span>Unresolved indicative commission</span><b>{money2(socialSecurity.full_source_control.unresolved_source_commission_indicative_not_approved)}</b></div><div><span>BC actual on matched-key population</span><b>{money2(socialSecurity.full_source_control.full_bc_actual_commission)}</b></div></div>}<div className="rr-analysis-table-wrap" style={{marginTop:12}}><table className="rr-analysis-table"><thead><tr><th>Scheme</th><th>Source Txns</th><th>BC Txns</th><th>Count Diff</th><th>Expected ₹</th><th>Actual ₹</th><th>BC − Expected</th></tr></thead><tbody>{socialSecurity.schemes.map(r=><tr key={r.transaction_type}><td><b>{r.transaction_type}</b></td><td>{fmt(r.source_transactions)}</td><td>{fmt(r.bc_transactions)}</td><td>{fmt(r.bc_transactions-r.source_transactions)}</td><td>{money2(r.expected_commission)}</td><td>{money2(r.actual_commission)}</td><td className={Number(r.commission_difference_bc_minus_expected)>0?'warn-text':''}>{signedMoney(r.commission_difference_bc_minus_expected)}</td></tr>)}<tr><td><b>TOTAL</b></td><td><b>{fmt(ssTotal?.source_transactions)}</b></td><td><b>{fmt(ssTotal?.bc_transactions)}</b></td><td><b>{fmt(ssTotal?.transaction_difference)}</b></td><td><b>{money2(ssTotal?.expected_commission)}</b></td><td><b>{money2(ssTotal?.actual_commission)}</b></td><td className="warn-text"><b>{signedMoney(ssTotal?.commission_difference_bc_minus_expected)}</b></td></tr></tbody></table></div><div className="rr-analysis-table-wrap" style={{marginTop:12}}><table className="rr-analysis-table"><thead><tr><th>CSP</th><th>Scheme</th><th>Source</th><th>BC</th><th>Count Diff</th><th>Expected ₹</th><th>Actual ₹</th><th>Status</th></tr></thead><tbody>{ssRows.filter(r=>r.status!=='MATCHED').sort((a,b)=>Math.abs(Number(b.commission_difference_bc_minus_expected||0))-Math.abs(Number(a.commission_difference_bc_minus_expected||0))).map((r,i)=><tr key={`${r.csp_id}-${r.transaction_type}`}><td><b>{r.csp_id}</b></td><td>{r.transaction_type}</td><td>{fmt(r.source_count)}</td><td>{fmt(r.bc_count)}</td><td>{fmt(r.count_difference)}</td><td>{money2(r.expected_commission)}</td><td>{money2(r.actual_commission)}</td><td><span className="rr-type-status warn">{r.status}</span></td></tr>)}</tbody></table></div></div>}
    <div className="rr-analysis-table-wrap"><table className="rr-analysis-table"><thead><tr><th>Transaction Type</th><th>Success Txns</th><th>Transaction Amount</th><th>BC Count</th><th>Count Diff</th><th>Expected ₹</th><th>Actual ₹</th><th>Variance ₹</th><th>Calculation</th></tr></thead><tbody>{data.map((r,i)=><tr key={r.type||i}><td><b>{r.type}</b></td><td>{fmt(r.txns)}</td><td>{money0(r.amount)}</td><td>{r.reportBase==null?'N/A':fmt(r.reportBase)}</td><td className={Math.abs(Number(r.countVariance||0))>0?'warn-text':''}>{r.countVariance==null?'N/A':fmt(r.countVariance)}</td><td>{r.expected==null?'N/A':money2(r.expected)}</td><td>{r.actual==null?'N/A':money2(r.actual)}</td><td>{r.variance==null?'N/A':signedMoney(r.variance)}</td><td><span className="rr-type-status neutral">{r.expectedStatus}</span></td></tr>)}</tbody></table>{data.length===0&&<div className="rr-analysis-empty">No transaction type matches the current search.</div>}</div>
  </div>
}

function SourceDataView({kind,title,subtitle,icon:Icon}) {
  const [data,setData]=useState(null), [search,setSearch]=useState(""), [query,setQuery]=useState(""), [offset,setOffset]=useState(0), [error,setError]=useState(""), [sheetName,setSheetName]=useState("");
  const limit=100;
  const load=async(nextOffset=offset,nextQuery=query,nextSheetName=sheetName)=>{
    try{
      setError("");
      const q=new URLSearchParams({offset:String(nextOffset),limit:String(limit)});
      if(nextQuery) q.set("search",nextQuery);
      if(nextSheetName) q.set("sheet_name",nextSheetName);
      const r=await fetch(`${API_BASE}/api/source-data/${kind}?${q.toString()}`);
      const d=await r.json();
      if(!r.ok) throw new Error(d.detail||"Source data could not be loaded.");
      setData(d); setOffset(nextOffset);
    }catch(e){setData(null);setError(e.message||"Source data could not be loaded.");}
  };
  useEffect(()=>{load(0,"");},[kind]);
  const submit=()=>load(0,search.trim());
  const rows=data?.rows||[], cols=data?.columns||[];
  return <div className="rr-analysis-page">
    <PageToolbar overline="SOURCE DATA" title={title} text={`${subtitle} Nothing is added up or calculated here: every stored row is shown, page by page, with all its columns.`}/>
    {error&&<Notice tone="warn" title="Source data unavailable">{error}</Notice>}
    {data&&<>
      <div className="rr-source-file"><Icon size={16}/><div><strong>{data.filename||"Uploaded file"}</strong><span>Sheet: {data.sheet_name||"—"} · Period: {data.period_start||"—"} to {data.period_end||"—"}</span></div></div>
      <MiniStats items={[["Rows in file",new Intl.NumberFormat("en-IN").format(data.total_rows||0)],["Rows in this search",new Intl.NumberFormat("en-IN").format(data.filtered_rows||0)],["Columns",cols.length],["Page size",`${limit} rows`]]}/>
      <div className="card">{(data.available_sheets||[]).length>1&&<div className="search-row" style={{marginBottom:12}}><label style={{fontWeight:700}}>Workbook sheet</label><select value={sheetName||data.sheet_name||""} onChange={e=>{setSheetName(e.target.value);setOffset(0);load(0,query,e.target.value)}}>{data.available_sheets.map(n=><option key={n} value={n}>{n}</option>)}</select></div>}<div className="search-row"><div className="search-box"><Search size={16}/><input placeholder="Search any value across all columns..." value={search} onChange={e=>setSearch(e.target.value)} onKeyDown={e=>e.key==='Enter'&&submit()}/>{search&&<button onClick={()=>{setSearch("");load(0,"")}}><X size={14}/></button>}</div><button className="primary-btn" onClick={submit}><Search size={15}/> Search</button><button className="secondary-btn" onClick={()=>load(offset,query)}><RefreshCw size={15}/> Refresh</button></div>
        <div className="source-table-wrap"><table className="source-data-table"><thead><tr><th>#</th>{cols.map(c=><th key={c}>{c}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={`${r.__row_number}-${i}`}><td>{r.__row_number}</td>{cols.map(c=><td key={c}>{r[c]===null||r[c]===undefined||r[c]===""?"—":String(r[c])}</td>)}</tr>)}</tbody></table></div>
        <div className="head-actions source-pager"><span>Showing {data.filtered_rows?offset+1:0}–{Math.min(offset+rows.length,data.filtered_rows||0)} of {data.filtered_rows||0}</span><div><button className="secondary-btn" disabled={offset<=0} onClick={()=>load(Math.max(0,offset-limit),query)}>Previous</button><button className="secondary-btn" disabled={offset+limit>=(data.filtered_rows||0)} onClick={()=>load(offset+limit,query)}>Next</button></div></div>
      </div>
    </>}
  </div>;
}

function TransactionTraceView({rows,total,offset,search,setSearch,onSearch,onPage}) {
  const money=n=>n==null?"N/A":`₹${new Intl.NumberFormat("en-IN",{maximumFractionDigits:2}).format(Number(n||0))}`;
  const shown=rows.length;
  return <div className="rr-analysis-page">
    <PageToolbar overline="TRANSACTIONS" title="Transaction audit trail" text="Look up any successful transaction from the uploaded file and see the commission it should earn and the rule behind it. The commission actually paid is kept per agent and transaction type, because the bank report has no transaction numbers.">
      <SearchField value={search} onChange={setSearch} onSubmit={onSearch} placeholder="Reference number, agent code or transaction type" onClear={()=>{setSearch("");setTimeout(onSearch,0)}}/>
      <button className="rr-btn rr-primary small" onClick={onSearch}><Search size={14}/> Search</button>
    </PageToolbar>
    <MiniStats items={[["Transactions available",total?new Intl.NumberFormat("en-IN").format(total):"0"],["Showing now",shown?`${offset+1} – ${offset+shown}`:"0"],["Page size","100 rows"],["Commission paid","Per agent and type"]]}/>
    {!total&&<Notice tone="info" icon={ShieldCheck} title="Nothing to show yet">Upload the transaction file and the bank commission report, then run the reconciliation to fill this page.</Notice>}
    <div className="rr-analysis-table-wrap"><table className="rr-analysis-table"><thead><tr><th>Reference</th><th>Agent</th><th>Type</th><th>Date</th><th>Amount</th><th>Should earn</th><th>Confirmed amount</th><th>Rate rule</th><th>Status</th></tr></thead><tbody>{rows.map((r,i)=><tr key={`${r.transaction_id||'row'}-${i}`}><td><b>{r.transaction_id||"—"}</b></td><td>{r.csp_id||"—"}</td><td>{r.transaction_type||"—"}</td><td>{r.transaction_date?String(r.transaction_date).slice(0,10):"—"}</td><td>{money(r.amount)}</td><td>{r.expected_commission==null?"N/A":money(r.expected_commission)}</td><td>{r.verified_expected_commission==null?"N/A":money(r.verified_expected_commission)}</td><td>{r.commission_rule_id||r.rate_status||"—"}</td><td><StatusBadge status={r.condition_status||"—"}/></td></tr>)}</tbody></table>{rows.length===0&&<div className="rr-analysis-empty">No transactions match the current search.</div>}</div>
    {total>0&&<Pager from={offset+1} to={Math.min(offset+shown,total)} total={new Intl.NumberFormat("en-IN").format(total)} canPrev={offset>0} canNext={offset+100<total} onPrev={()=>onPage(Math.max(0,offset-100))} onNext={()=>onPage(offset+100)}/>}
  </div>;
}

function ProcessingView(){
  const [data,setData]=useState(null); const [mapping,setMapping]=useState([]); const [audit,setAudit]=useState(null); const [error,setError]=useState("");
  useEffect(()=>{(async()=>{try{const [a,b,c]=await Promise.all([fetch(`${API_BASE}/api/processing/summary`),fetch(`${API_BASE}/api/processing/mapping`),fetch(`${API_BASE}/api/reconciliation/condition-audit/summary`)]);const da=await a.json();const db=await b.json();const dc=await c.json();if(!a.ok)throw new Error(da.detail||"Upload transaction file first");if(!b.ok)throw new Error(db.detail||"Unable to load mapping");setData(da);setMapping(db);if(c.ok)setAudit(dc)}catch(e){setError(e.message||"Unable to load processing data")}})()},[]);
  if(error) return <div className="upload-result error"><AlertTriangle size={16}/><div><strong>Processing data unavailable</strong><span>{error}</span></div></div>;
  if(!data) return <div className="card"><div className="card-header"><div><h3>Processing transaction file...</h3><p>Loading deterministic validation and normalization results.</p></div></div></div>;
  return <div className="rr-analysis-page">
    <PageToolbar overline="FILE CHECK" title="How the transaction file was prepared" text="Only successful transactions are kept, the data is checked for mistakes, transaction names are matched to the standard list, and everything is made ready to compare with the bank report. No commission rate is guessed here."/>
    <section className="kpi-grid">
      <Kpi icon={FileCheck2} label="Uploaded Rows" value={fmt(data.total_uploaded_rows)} meta={`${fmt(data.successful_rows)} eligible successful`} positive/>
      <Kpi icon={CheckCircle2} label="Success Rate" value={`${Number(data.success_rate||0).toFixed(2)}%`} meta={`${fmt(data.non_successful_rows)} non-success rows`} positive/>
      <Kpi icon={CircleDollarSign} label="Transaction Amount" value={money(data.transaction_amount)} meta="Successful transaction population"/>
      <Kpi icon={Users} label="Unique CSPs" value={fmt(data.unique_csps)} meta={`${fmt(data.unique_transaction_types)} transaction types`}/>
      <Kpi icon={AlertTriangle} label="Duplicate References" value={fmt(data.duplicate_reference_rows)} meta={`${fmt(data.invalid_amount_rows)} invalid amounts`} warning={Number(data.duplicate_reference_rows)>0||Number(data.invalid_amount_rows)>0}/>
      <Kpi icon={Table2} label="Type Mapping" value={`${Number(data.mapped_transaction_type_rate||0).toFixed(2)}%`} meta={`${fmt(data.unmapped_transaction_type_rows)} rows unmapped`} warning={Number(data.unmapped_transaction_type_rows)>0}/>
    </section>
    {audit&&<section className="card"><CardHeader title="SBI transaction condition audit" subtitle="Every successful transaction is classified before expected commission is accepted" action={`${Number(audit.total_transactions||0).toLocaleString("en-IN")} rows checked`}/><div className="insight-list"><Insight icon={CheckCircle2} title="Verified" text={`${fmt(audit.ok)} transactions satisfy one confirmed SBI rule and are included in the verified expected total.`} tone="success"/><Insight icon={AlertTriangle} title="Conditional" text={`${fmt(audit.conditional)} transactions need geography, rule approval or another commercial condition before final calculation.`} tone="warning"/><Insight icon={AlertTriangle} title="Condition fail / Unmapped" text={`${fmt(audit.condition_fail)} condition-fail and ${fmt(audit.unmapped)} unmapped transactions are excluded from the verified expected amount.`} tone="warning"/></div></section>}
    <section className="content-grid"><div className="card"><CardHeader title="Transaction-type mapping" subtitle="Operational transaction type → commission/reporting type"/><div className="table-wrap"><table><thead><tr><th>Transaction Type</th><th>Successful Txns</th><th>Commission Type</th><th>Status</th></tr></thead><tbody>{mapping.map((r,i)=><tr key={`${r.transaction_type_normalized}-${i}`}><td>{r.transaction_type_normalized}</td><td>{fmt(r.successful_transactions)}</td><td>{r.commission_type||"—"}</td><td><StatusBadge status={r.mapping_status}/></td></tr>)}</tbody></table></div></div>
    <div className="card"><CardHeader title="Processing controls" subtitle="Checks performed before reconciliation"/><div className="insight-list">
      <Insight icon={CheckCircle2} title="Successful filter" text={`${fmt(data.successful_rows)} rows qualify from ${fmt(data.total_uploaded_rows)} uploaded rows.`} tone="success"/>
      <Insight icon={CheckCircle2} title="Duplicate check" text={`${fmt(data.duplicate_reference_rows)} duplicate-reference rows detected in the successful population.`} tone="success"/>
      <Insight icon={AlertTriangle} title="Unmapped types" text={`${fmt(data.unmapped_transaction_type_rows)} successful rows are outside the current approved transaction-type mapping and will remain exceptions.`} tone="warning"/>
      <Insight icon={ShieldCheck} title="Expected commission control" text="Only confirmed SBI rules with all required transaction conditions are included in the verified monthly expected total; conditional rows remain excluded until evidence is available." tone="info"/>
    </div></div></section>
  </div>;
}

function DfsReconciliationPanel({historicalData=null,viewingHistory=false}) {
  const [data,setData]=useState(null);
  const [rules,setRules]=useState(null);
  const [loading,setLoading]=useState(true);
  const [rulesLoading,setRulesLoading]=useState(true);
  const [rulesError,setRulesError]=useState("");
  const [error,setError]=useState("");
  const loadRules=async()=>{
    setRulesLoading(true); setRulesError("");
    try {
      const r=await fetch(`${API_BASE}/api/upload/dfs-incentive/rules`);
      const d=await r.json();
      if(!r.ok) throw new Error(d.detail || "Permanent DFS rule matrix could not be loaded.");
      setRules(d.rule_matrix || null);
      if(!d.rule_matrix) throw new Error("DFS rules response did not include rule_matrix.");
    } catch(e) { setRules(null); setRulesError(e.message || "Permanent DFS rules unavailable."); }
    finally { setRulesLoading(false); }
  };
  const load=async()=>{
    setLoading(true); setError("");
    try {
      const r=await fetch(`${API_BASE}/api/upload/dfs-incentive/reconciliation`, {cache:"no-store"});
      const d=await r.json();
      if(!r.ok) throw new Error(d.detail || "DFS reconciliation could not be loaded.");
      setData(d);
    } catch(e) { setData(null); setError(e.message || "DFS reconciliation unavailable."); }
    finally { setLoading(false); }
  };
  useEffect(()=>{if(viewingHistory) setLoading(false); else load(); loadRules();},[viewingHistory]);
  const shownData = viewingHistory ? historicalData : data;
  return <section className="card" style={{marginBottom:18}}>
    <CardHeader title="DFS Priorities Incentive — monthly reconciliation" subtitle={shownData?.available ? `Period: ${(shownData.periods||[]).join(", ")}. CSP-wise expected vs actual incentive from the ${viewingHistory ? "saved period" : "active BC Report"}.` : "Monthly DFS incentive reconciliation and exceptions."} action={!viewingHistory && <button className="rr-btn rr-secondary" onClick={load} disabled={loading}><RefreshCw size={14} className={loading?"spin":""}/> Refresh</button>}/>
    {rulesLoading ? <div className="upload-result"><RefreshCw size={16} className="spin"/><div><strong>Loading permanent DFS rule matrix</strong><span>Reading the saved SBI rule endpoint.</span></div></div>
    : rulesError ? <div className="upload-result error"><AlertTriangle size={16}/><div><strong>Permanent DFS rule matrix unavailable</strong><span>{rulesError}</span></div></div>
    : rules && <div className="table-wrap" style={{marginBottom:14}}><table><thead><tr><th>Permanent DFS Rule</th><th>Slab-1</th><th>Slab-2</th><th>Slab-3</th><th>Slab-4</th><th>Super Slab</th></tr></thead><tbody>
      {(rules.schemes||[]).map(row=><tr key={row.scheme}><td>{row.scheme}</td><td>{row.targets?.["SLAB-1"]}</td><td>{row.targets?.["SLAB-2"]}</td><td>{row.targets?.["SLAB-3"]}</td><td>{row.targets?.["SLAB-4"]}</td><td>{row.targets?.["SUPER SLAB"]}</td></tr>)}
      <tr><td><b>Monthly extra incentive (₹)</b></td>{["SLAB-1","SLAB-2","SLAB-3","SLAB-4","SUPER SLAB"].map(k=><td key={k}><b>{fmt(rules.monthly_extra_incentive_inr?.[k])}</b></td>)}</tr>
      <tr><td><b>Average balance multiplier / comm. (%)</b></td>{["SLAB-1","SLAB-2","SLAB-3","SLAB-4","SUPER SLAB"].map(k=><td key={k}><b>{Number(rules.average_balance_multiplier_percent?.[k]||0).toFixed(2)}%</b></td>)}</tr>
      </tbody></table><div className="muted" style={{padding:"8px 10px",fontSize:12}}>Scheme targets: PMJDY / PMJJBY / PMSBY / APY. Monthly slab incentive is reconciled separately from average-balance commission; average-balance amount needs its approved base/formula. Slab eligibility is not inferred without the current-period CSP scheme counts.</div></div>}
    {loading ? <div className="upload-result"><RefreshCw size={16} className="spin"/><div><strong>Loading DFS reconciliation</strong><span>Reading the active monthly source and BC commission report.</span></div></div>
    : error ? <div className="upload-result error"><AlertTriangle size={16}/><div><strong>DFS reconciliation unavailable</strong><span>{error}</span></div></div>
    : !shownData?.available ? <div className="upload-result error"><AlertTriangle size={16}/><div><strong>DFS reconciliation not ready</strong><span>{shownData?.message || "Upload the matching-period DFS slab sheet and BC Commission Report from Data Upload."}</span></div></div>
    : <>
      <div className="upload-steps">
        <div className="upload-step"><span>1</span><b>Expected: ₹{fmt(shownData.summary?.expected_total)}</b></div>
        <div className="upload-step"><span>2</span><b>Actual: ₹{fmt(shownData.summary?.actual_total)}</b></div>
        <div className="upload-step"><span>3</span><b>Variance: ₹{fmt(shownData.summary?.variance_actual_minus_expected)}</b></div>
        <div className="upload-step"><span>4</span><b>Matched {fmt(shownData.summary?.matched)} / Exceptions {fmt(shownData.summary?.exceptions)}</b></div>
      </div>
      <div className="table-wrap"><table><thead><tr><th>CSP ID</th><th>CSP Name</th><th>Slab</th><th>Expected ₹</th><th>Actual ₹</th><th>Variance ₹</th><th>Status</th></tr></thead>
      <tbody>{(shownData?.rows||[]).map((r,i)=><tr key={`${r.csp_id||"bc"}-${i}`}><td>{r.csp_id||"—"}</td><td>{r.csp_name||"—"}</td><td>{r.slab||"BC only"}</td><td>{r.expected_incentive==null?"N/A":money2(r.expected_incentive)}</td><td>{r.actual_commission==null?"N/A":money2(r.actual_commission)}</td><td>{r.variance_actual_minus_expected==null?"N/A":money2(r.variance_actual_minus_expected)}</td><td>{r.status}</td></tr>)}</tbody></table></div>
    </>}
  </section>;
}

function WomenCspIncentivePanel({historicalData=null,viewingHistory=false}) {
  const [data,setData]=useState(null); const [loading,setLoading]=useState(true); const [error,setError]=useState("");
  const load=async()=>{setLoading(true);setError("");try{const r=await fetch(`${API_BASE}/api/upload/women-csp-incentive/reconciliation`);const d=await r.json();if(!r.ok)throw new Error(d.detail||"Women CSP reconciliation could not be loaded.");setData(d);}catch(e){setData(null);setError(e.message||"Women CSP reconciliation unavailable.");}finally{setLoading(false);}};
  useEffect(()=>{if(!viewingHistory) load();},[viewingHistory]);
  const shownData=viewingHistory ? historicalData : data;
  const sm=shownData?.summary||{};
  return <section className="card" style={{marginBottom:18}}>
    <CardHeader title="Women CSP Incentive — SBI Rule 24" subtitle={shownData?.available?`Period: ${shownData.period||"saved period"} · Additional 10% on eligible transaction commission, capped at ₹1,000 per CSP/month.`:"Upload current-period Women CSP roster and matching BC report to calculate Rule 24."} action={!viewingHistory && <button className="rr-btn rr-secondary" onClick={load} disabled={loading}><RefreshCw size={14} className={loading?"spin":""}/> Refresh</button>}/>
    {!viewingHistory && loading?<div className="upload-result"><RefreshCw size={16} className="spin"/><div><strong>Loading Women CSP reconciliation</strong><span>Reading the active-period roster and BC report.</span></div></div>
    :!viewingHistory && error?<div className="upload-result error"><AlertTriangle size={16}/><div><strong>Women CSP reconciliation unavailable</strong><span>{error}</span></div></div>
    :!shownData?.available?<div className="upload-result error"><AlertTriangle size={16}/><div><strong>Women CSP reconciliation not ready</strong><span>{shownData?.message||"Upload the current-period Women CSP roster from Data Upload."}</span></div></div>
    :<>
      <div className="rr-mini-grid" style={{marginTop:10}}>
        <div><span>Total bank-paid incentive</span><b>{money2(sm.total_bank_paid)}</b><small>{fmt(sm.bank_paid_csp_count)} CSPs</small></div>
        <div><span>Matched in master</span><b>{money2(sm.matched_in_master_actual)}</b><small>{fmt(sm.matched_in_master_csp_count)} CSPs</small></div>
        <div><span>Bank paid; missing from master</span><b>{money2(sm.bank_paid_extra_actual)}</b><small>{fmt(sm.bank_paid_extra_csp_count)} CSPs</small></div>
        <div><span>Unpaid active shortfall</span><b className={Number(sm.unpaid_shortfall_expected)>0?"warn-text":""}>{money2(sm.unpaid_shortfall_expected)}</b><small>{fmt(sm.unpaid_shortfall_csp_count)} CSPs</small></div>
      </div>
      <div className="table-wrap" style={{marginTop:12}}><table><thead><tr><th>CSP ID</th><th>CSP Name</th><th>Classification</th><th>Base Txn Commission</th><th>Expected Incentive</th><th>Bank Paid</th><th>Variance</th></tr></thead><tbody>{(shownData?.rows||[]).map((r,i)=><tr key={`${r.csp_id}-${i}`}><td>{r.csp_id}</td><td>{r.csp_name||"—"}</td><td>{r.category}</td><td>{money2(r.base_transaction_commission)}</td><td>{money2(r.expected_incentive)}</td><td>{money2(r.actual_incentive)}</td><td className={Number(r.variance_actual_minus_expected)<-0.02?"warn-text":""}>{money2(r.variance_actual_minus_expected)}</td></tr>)}</tbody></table></div>
      {(shownData?.notes||[]).map((n,i)=><p key={i} style={{fontSize:12,color:"var(--muted,#64748b)"}}>{n}</p>)}
    </>}
  </section>;
}

function UploadWorkspace({onUploaded, sourceStatus, onRunRequested}) { const [txFile,setTxFile]=useState(null),[commissionFile,setCommissionFile]=useState(null),[ruralFile,setRuralFile]=useState(null),[ssFile,setSsFile]=useState(null),[pbFile,setPbFile]=useState(null),[dfsFile,setDfsFile]=useState(null),[womenFile,setWomenFile]=useState(null),[tabFile,setTabFile]=useState(null),[loanLeadFile,setLoanLeadFile]=useState(null),[matmFile,setMatmFile]=useState(null),[matmResult,setMatmResult]=useState(null),[txResult,setTxResult]=useState(null),[commissionResult,setCommissionResult]=useState(null),[ruralResult,setRuralResult]=useState(null),[ssResult,setSsResult]=useState(null),[pbResult,setPbResult]=useState(null),[dfsResult,setDfsResult]=useState(null),[womenResult,setWomenResult]=useState(null),[tabResult,setTabResult]=useState(null),[loanLeadResult,setLoanLeadResult]=useState(null),[loading,setLoading]=useState({transactions:false,commission:false,rural_csp:false,social_security_counts:false,passbook_printing_counts:false,dfs_incentive:false,women_csp_roster:false,tab_incentive:false,loan_lead_generation:false,matm_incentive:false});
  const files={transactions:txFile,commission:commissionFile,rural_csp:ruralFile,social_security_counts:ssFile,passbook_printing_counts:pbFile,dfs_incentive:dfsFile,women_csp_roster:womenFile,tab_incentive:tabFile,loan_lead_generation:loanLeadFile,matm_incentive:matmFile}; const setters={transactions:setTxResult,commission:setCommissionResult,rural_csp:setRuralResult,social_security_counts:setSsResult,passbook_printing_counts:setPbResult,dfs_incentive:setDfsResult,women_csp_roster:setWomenResult,tab_incentive:setTabResult,loan_lead_generation:setLoanLeadResult,matm_incentive:setMatmResult};
  const upload=async kind=>{const file=files[kind];if(!file)return;setLoading(x=>({...x,[kind]:true}));try{const body=new FormData();body.append("file",file);const endpoint=kind==="rate_master"?"expected-commission-rule":(kind==="rural_csp"?"rural-csp":kind==="social_security_counts"?"social-security-counts":kind==="passbook_printing_counts"?"passbook-printing-counts":kind==="dfs_incentive"?"dfs-incentive":kind==="women_csp_roster"?"women-csp-roster":kind==="tab_incentive"?"tab-incentive":kind==="loan_lead_generation"?"loan-lead-generation":kind==="matm_incentive"?"matm-incentive-v2":kind);const res=await fetch(`${API_BASE}/api/upload/${endpoint}`,{method:"POST",body});const data=await res.json();if(!res.ok)throw new Error(data.detail||"Upload failed");setters[kind]({ok:true,data});if(onUploaded)await onUploaded();}catch(e){const message=friendlyApiError(e, `upload ${file.name}`);setters[kind]({ok:false,error:message});if((kind==="transactions"||kind==="commission")&&onUploaded){try{await onUploaded()}catch{}}}finally{setLoading(x=>({...x,[kind]:false}));}};
  return <div className="upload-page"><div className="upload-intro card"><div><div className="ai-badge"><Upload size={16}/> STEP 5 · CONTROLLED RECONCILIATION INPUTS</div><h2>Upload reconciliation source files</h2><p>Upload the current-period transaction file and matching BC/commission file. The approved SBI commission rules are bundled permanently with the project and apply across months; only current-period source data changes. The system never infers a commercial rate from historical commission.</p></div><div className="upload-rules"><span><CheckCircle2 size={15}/> CSV</span><span><CheckCircle2 size={15}/> XLSX</span><span><ShieldCheck size={15}/> Deterministic validation</span></div></div><UploadSteps sources={sourceStatus?.sources} files={files} ready={!!sourceStatus?.ready_to_run} running={false} onRun={onRunRequested}/>{sourceStatus?.ready_to_run&&<div className="card" style={{marginBottom:16,borderColor:"#a7e3c2",background:"#f2fbf6"}}><div className="upload-result success"><CheckCircle2 size={18}/><div><strong>Current source data is already loaded</strong><span>The project supports any month or multi-month period. Upload the Successful Transaction Sheet and matching BC Commission Report for the period you want to reconcile. The permanent SBI rule master is already configured. Transaction dates determine the period; upload matching Rural CSP, PMJJBY/PMSBY, Passbook Printing and DFS evidence when applicable.</span></div></div></div>}<div className="card" style={{marginBottom:16}}><CardHeader title="Processing status" subtitle="Current-period transaction and BC commission files are validated independently. Permanent SBI rules are bundled and reused across all periods."/><div className="upload-steps"><div className="upload-step"><span>1</span><b>Transaction: {sourceStatus?.sources?.transactions ? "Validated" : "Waiting"}</b></div><div className="upload-step"><span>2</span><b>BC/Commission: {sourceStatus?.sources?.commission ? "Validated" : "Waiting"}</b></div><div className="upload-step"><span>3</span><b>Permanent SBI rules: Bundled and active</b></div><div className="upload-step"><span>4</span><b>CSP Geography: {sourceStatus?.sources?.csp_geography ? "Auto-derived from BC Report" : "Auto-detected when available"}</b></div><div className="upload-step"><span>5</span><b>Rural CSP List: {sourceStatus?.sources?.rural_csp ? "Validated" : "Required for Rural Commission control"}</b></div><div className="upload-step"><span>6</span><b>{sourceStatus?.reconciliation_cached ? "Reconciliation ready" : sourceStatus?.ready_to_run ? "Ready to run reconciliation" : "Waiting for current-period transaction + BC commission files"}</b></div></div>{(sourceStatus?.readiness_errors||sourceStatus?.quality_errors||[]).length>0&&<div className="upload-result error" style={{marginTop:14}}><AlertTriangle size={16}/><div><strong>Reconciliation is not ready</strong><span>{(sourceStatus.readiness_errors||sourceStatus.quality_errors||[]).join(" · ")}</span></div></div>}</div>
    <div className="upload-grid"><UploadCard title="1. Successful Transaction File" description="Any successful-transaction export: reference, CSP, type, amount and transaction date. Status is used when present; success-only files may omit it." file={txFile} setFile={setTxFile} result={txResult} loading={loading.transactions} onUpload={()=>upload("transactions")} required="Reference Number · CSP Code · Type · Amount · Date · Status (if present)"/><UploadCard title="2. BC / Commission File" description="Actual commission/base reported by CSP and transaction type." file={commissionFile} setFile={setCommissionFile} result={commissionResult} loading={loading.commission} onUpload={()=>upload("commission")} required="CSP Code · Transaction Type · Commission"/><UploadCard title="3. Rural CSP Eligibility List (required for Rural Commission)" description="Upload the current-period Rural CSP eligibility roster (NOT the permanent SBI Expected Commission Rule workbook). It must contain CSP ID and a month-labelled Total Login Day column, e.g. Total Login Day Aug-26. Used only for the ₹2,000 Rural CSP incentive control; no month is hardcoded." file={ruralFile} setFile={setRuralFile} result={ruralResult} loading={loading.rural_csp} onUpload={()=>upload("rural_csp")} required="Rural CSP roster XLSX/CSV · CSP ID · Total Login Day <month-year> (not SBI_Expected_Commission_Rule.xlsx)"/><div className="card upload-auto-source"><CardHeader title="3. CSP Geography — automatic from BC Report" subtitle="The standard SBI BC workbook already contains CSP geography in Payment Status → POPULATION. The system imports that source field automatically and maps only SBI rule groupings; it does not infer geography from commission values."/><div className="upload-result success"><CheckCircle2 size={16}/><div><strong>Manual geography upload is not required for this BC workbook</strong><span>RURAL + SEMI URBAN are grouped as RURAL; URBAN + METRO are grouped as URBAN for rules that use those SBI geography buckets.</span></div></div></div><UploadCard title="3. PMJJBY / PMSBY Monthly Source (when applicable)" description="Upload current-period CSP-wise scheme counts. Premium is retained when the source provides it; it is never inferred. Commission uses the approved period rule." file={ssFile} setFile={setSsFile} result={ssResult} loading={loading.social_security_counts} onUpload={()=>upload("social_security_counts")} required="CSP Code · Scheme (column or PMJJBY/PMSBY sheet) · Count + Period/month column · Premium if supplied"/><UploadCard title="3. Passbook Printing Monthly Source (when applicable)" description="Upload CSP-wise passbook print counts. Geography and rate are resolved from the current BC commission workbook and approved SBI rate master, not from this supplemental file." file={pbFile} setFile={setPbFile} result={pbResult} loading={loading.passbook_printing_counts} onUpload={()=>upload("passbook_printing_counts")} required="CSP Code · Count/Prints + Period, or one month-year count column (e.g. Sep 2026)"/><UploadCard title="3. DFS Priorities Incentive — Monthly CSP Slab Sheet" description="Upload each month’s CSP-wise assigned DFS slab sheet. Permanent DFS matrix: monthly extra incentive Slab-1 ₹1,200; Slab-2 ₹1,500; Slab-3 ₹1,800; Slab-4 ₹2,200; Super Slab ₹5,000. Scheme targets (PMJDY/PMJJBY/PMSBY/APY): S1 8/12/20/3, S2 10/14/25/4, S3 12/16/30/5, S4 14/18/35/6, Super 30/50/100/15. Average-balance multipliers: 0.85%, 0.90%, 0.95%, 1.00%, 1.00%. Slab is not inferred without current-period CSP-wise counts; average-balance amount needs its separate base and approved formula." file={dfsFile} setFile={setDfsFile} result={dfsResult} loading={loading.dfs_incentive} onUpload={()=>upload("dfs_incentive")} required="CSP Code · Assigned Slab · Month/year (in column or filename)"/><UploadCard title="3. Women CSP Incentive — SBI Rule 24" description="Upload the current period’s Women CSP roster. The permanent rule applies 10% to eligible transaction-based commission, capped at ₹1,000 per Women CSP/month. Actual payout is read from the BC Report." file={womenFile} setFile={setWomenFile} result={womenResult} loading={loading.women_csp_roster} onUpload={()=>upload("women_csp_roster")} required="CSP ID · CSP Name · Total Transaction Count for one month (e.g. Total Transaction Count Sep 2026)"/><UploadCard title="3. TAB Financial Transaction Incentive — Permanent SBI Rule" description="Upload monthly CSP-wise eligible TAB financial transaction counts. SBI rule: ₹5 per eligible transaction, excluding m-ATM transactions through TAB, capped at ₹1,000 per CSP/month. Reconciles separately against the actual TAB incentive line in the BC report." file={tabFile} setFile={setTabFile} result={tabResult} loading={loading.tab_incentive} onUpload={()=>upload("tab_incentive")} required="Period · CSP Code · TAB financial transaction count; do not include m-ATM transactions"/><UploadCard title="3. m-ATM Cash Transaction Incentive — SBI CM060" description="Upload current-period CSP-wise m-ATM cash transaction counts. Rule: ₹3 per financial transaction, capped at ₹1,000 per CSP per month. Expected amount is calculated from this independent source; BC Report is actual-side only." file={matmFile} setFile={setMatmFile} result={matmResult} loading={loading.matm_incentive} onUpload={()=>upload("matm_incentive")} required="CSP ID · Month-labelled mATM transaction count column (e.g. mATM Transaction Count August 2026)"/><UploadCard title="3. Loan Lead Generation Activities — SBI Commission Rule" description="Upload current-period loan leads. SBI base commission is calculated only on documented sanction limit: Home/Vehicle 0.50%, Mudra 0.25%, Personal/P-Segment Gold/Agri Gold 0.10% + GST. No sanction limit or GST rate is inferred." file={loanLeadFile} setFile={setLoanLeadFile} result={loanLeadResult} loading={loading.loan_lead_generation} onUpload={()=>upload("loan_lead_generation")} required="Lead ID · Lead Date · Loan Type · Status · CSP Code · Sanction Limit (required for calculation) · GST rate (if GST amount needed)"/></div><div className="card upload-flow"><CardHeader title="Control rule" subtitle="Upload the transaction file and its matching BC Commission Report for the selected month. The first replacement starts a new batch and the companion file joins that same batch. Reconciliation is blocked if the source periods do not align or required validation fails."/><div className="upload-steps">{["Read & detect source sheet","Validate mandatory fields","Normalize CSP/type/date/amount","Apply approved rate/slab by date + amount","Reconcile expected vs actual + exceptions"].map((x,i)=><div className="upload-step" key={x}><span>{i+1}</span><b>{x}</b></div>)}</div></div></div>;
}


function PassbookPrintingPanel({data,viewingHistory=false}) {
  if (!data) return null;
  const total=data.total||{};
  return <section className="rr-card" style={{marginTop:16}}>
    <div className="rr-card-head"><div><span className="rr-overline">PASSBOOK PRINTING · {viewingHistory ? "SAVED PERIOD" : "CURRENT PERIOD"}</span><h3>Passbook printing reconciliation</h3><p>{data.source_limit || data.message || "CSP-wise print counts compared with BC-reported counts and commission."}</p></div><span className={`rr-status ${data.available && data.status === "READY" ? "good" : "warn"}`}>{data.status || "NOT AVAILABLE"}</span></div>
    {!data.available ? <div className="rr-alert"><AlertTriangle size={17}/><div><b>Passbook control not available for this period.</b><span>{data.message || "No saved passbook details were available."}</span></div></div> : <>
      <div className="rr-product-summary"><div className="rr-financial-number"><span>Source prints</span><b>{fmt(total.source_prints_including_unresolved ?? total.source_prints)}</b></div><div className="rr-financial-number"><span>BC-reported prints</span><b>{fmt(total.bc_prints)}</b></div><div className="rr-financial-number"><span>Expected (indicative)</span><b>{money2(total.expected_commission_indicative)}</b></div><div className="rr-financial-number penalty"><span>Actual − expected</span><b>{money2(total.commission_difference_actual_minus_expected)}</b></div></div>
      <div className="rr-table-wrap"><table><thead><tr><th>CSP ID</th><th>Period</th><th>Source prints</th><th>BC prints</th><th>Expected (indicative)</th><th>Actual</th><th>Count status</th><th>Cap verification</th></tr></thead><tbody>{(data.rows||[]).map((r,i)=><tr key={`${r.csp_id||"csp"}-${i}`}><td>{r.csp_id||"—"}</td><td>{r.period||"—"}</td><td>{fmt(r.source_count)}</td><td>{fmt(r.bc_count)}</td><td>{r.expected_commission_indicative==null?"N/A":money2(r.expected_commission_indicative)}</td><td>{r.actual_commission==null?"N/A":money2(r.actual_commission)}</td><td>{r.status||"—"}</td><td>{r.cap_status||"NOT_VERIFIABLE_ACCOUNT_LEVEL_SOURCE"}</td></tr>)}</tbody></table></div>
      <p className="rr-muted">Expected amount is indicative because account-level evidence for the five-print monthly cap is not available in the CSP-wise source.</p>
    </>}
  </section>;
}

function MatmIncentivePanel({historicalData=null,viewingHistory=false}){const [data,setData]=useState(null);const [error,setError]=useState("");const shownData=viewingHistory ? historicalData : data;useEffect(()=>{if(viewingHistory)return;let live=true;fetch(`${API_BASE}/api/upload/matm-incentive/reconciliation`, {cache:"no-store"}).then(async r=>{const d=await r.json();if(!r.ok)throw new Error(d.detail||"m-ATM reconciliation unavailable");return d;}).then(d=>{if(live){setData(d);setError("")}}).catch(e=>{if(live)setError(e.message||"m-ATM reconciliation unavailable")});return()=>{live=false}},[viewingHistory]);if(!shownData?.available)return <section className="rr-card" style={{marginTop:16}}><div className="rr-card-head"><div><span className="rr-overline">M-ATM CASH TRANSACTION INCENTIVE · SBI CM060</span><h3>m-ATM incentive reconciliation</h3><p>₹3 per eligible transaction; maximum ₹1,000 per CSP per month.</p></div><span className="rr-status warn">{shownData?.status||"Source required"}</span></div><div className="rr-alert"><AlertTriangle size={17}/><div><b>Independent CSP-wise m-ATM source is required.</b><span>{shownData?.message||error||"Open Data Upload and upload the current-period CSP_mATM count sheet and matching BC report."}</span></div></div></section>;const s=shownData.summary||{};return <section className="rr-card" style={{marginTop:16}}><div className="rr-card-head"><div><span className="rr-overline">M-ATM CASH TRANSACTION INCENTIVE · {shownData.periods?.join(", ")}</span><h3>m-ATM incentive reconciliation</h3><p>Permanent SBI rule CM060: ₹3 per financial transaction, capped at ₹1,000 per CSP/month.</p></div><span className={`rr-status ${s.short_paid===0&&s.excess_paid===0&&s.source_only===0&&s.bc_only===0?"good":"warn"}`}>{s.match_rate}% exact CSP matches</span></div><div className="rr-product-summary"><div className="rr-financial-number"><span>Expected commission</span><b>{money2(s.expected_total)}</b><small>{fmt(s.source_csp_controls)} source CSPs · {fmt(s.source_transaction_count)} base transactions</small></div><div className="rr-financial-number"><span>Actual bank payment</span><b>{money2(s.actual_total)}</b><small>{fmt(s.bank_recognized_transactions)} bank-recognized transactions</small></div><div className="rr-financial-number penalty"><span>Variance (actual − expected)</span><b>{money2(s.variance_actual_minus_expected)}</b><small>{fmt(s.short_paid)} short · {fmt(s.excess_paid)} excess</small></div></div><div className="rr-alert"><AlertTriangle size={17}/><div><b>Count and commission matches are separate checks.</b><span>{fmt(s.count_matched||0)} exact count matches · {fmt(s.count_mismatches||0)} count mismatches · {fmt(s.count_source_only||0)} source-only count controls · {fmt(s.count_bc_only||0)} BC-only count controls. Source-to-bank count variance: {fmt(s.count_variance_bank_minus_source||0)}.</span></div></div><div className="rr-table-wrap"><table className="rr-table"><thead><tr><th>Period</th><th>CSP Code</th><th>Source Txns</th><th>Bank Txns</th><th>Expected</th><th>Actual</th><th>Variance</th><th>Commission status</th><th>Count status</th><th>Count variance</th></tr></thead><tbody>{(shownData.rows||[]).map((r,i)=><tr key={`${r.period||"BC"}-${r.csp_id}-${i}`}><td>{r.period||"—"}</td><td>{r.csp_id}<small>{r.identity_resolution && r.identity_resolution!=="EXACT_CSP_ID" ? `${r.source_csp_id || ""} · ${r.identity_resolution}` : "Exact CSP ID"}</small></td><td>{fmt(r.matm_transaction_count)}</td><td>{fmt(r.bank_recognized_txns)}</td><td>{money2(r.expected_incentive)}</td><td>{money2(r.actual_commission)}</td><td>{money2(r.variance_actual_minus_expected)}</td><td>{r.status}</td><td>{r.count_status||"N/A"}</td><td>{fmt(r.count_variance_bank_minus_source||0)}</td></tr>)}</tbody></table></div><p className="rr-muted">This is a separate incentive control. Expected uses the uploaded CSP count source; actual uses BC-reported commission. August source values are not preloaded.</p></section>}
function TabIncentivePanel(){const [data,setData]=useState(null);const [error,setError]=useState("");useEffect(()=>{let live=true;fetch(`${API_BASE}/api/upload/tab-incentive/reconciliation`, {cache:"no-store"}).then(async r=>{const d=await r.json();if(!r.ok)throw new Error(d.detail||"TAB reconciliation unavailable");return d;}).then(d=>{if(live){setData(d);setError("")}}).catch(e=>{if(live)setError(e.message||"TAB reconciliation unavailable")});return()=>{live=false}},[]);if(!data?.available)return <section className="rr-card" style={{marginTop:16}}><div className="rr-card-head"><div><span className="rr-overline">TAB FINANCIAL TRANSACTION INCENTIVE · SBI PERMANENT RULE</span><h3>TAB incentive reconciliation</h3><p>₹5 per eligible transaction; m-ATM excluded; maximum ₹1,000 per CSP per month.</p></div><span className="rr-status warn">{data?.status||"Source required"}</span></div><div className="rr-alert"><AlertTriangle size={17}/><div><b>TAB incentive is separate from the overall KPI until current-period actual payment is verified.</b><span>{data?.message||error||"Open Data Upload and upload the current-period TAB incentive count sheet plus the matching BC commission report."}</span></div></div></section>;const s=data.summary||{};return <section className="rr-card" style={{marginTop:16}}><div className="rr-card-head"><div><span className="rr-overline">TAB FINANCIAL TRANSACTION INCENTIVE · {data.periods?.join(", ")}</span><h3>TAB incentive reconciliation</h3><p>Permanent SBI rule: ₹5 per eligible TAB financial transaction, m-ATM excluded, capped at ₹1,000 per CSP/month.</p></div><span className={`rr-status ${s.short_paid===0&&s.excess_paid===0?"good":"warn"}`}>{s.match_rate}% CSP-month matched</span></div><div className="rr-product-summary"><div className="rr-financial-number"><span>Expected incentive</span><b>{money2(s.expected_total)}</b><small>{fmt(s.control_groups)} CSP-month controls</small></div><div className="rr-financial-number"><span>Actual bank payment</span><b>{money2(s.actual_total)}</b><small>{fmt(s.matched)} matched</small></div><div className="rr-financial-number penalty"><span>Variance (actual − expected)</span><b>{money2(s.variance_actual_minus_expected)}</b><small>{fmt(s.short_paid)} short · {fmt(s.excess_paid)} excess</small></div></div><div className="rr-table-wrap"><table className="rr-table"><thead><tr><th>Period</th><th>CSP Code</th><th>Eligible TAB Txns</th><th>Expected</th><th>Actual</th><th>Variance</th><th>Status</th></tr></thead><tbody>{(data.rows||[]).map((r,i)=><tr key={`${r.period}-${r.csp_id}-${i}`}><td>{r.period}</td><td>{r.csp_id}</td><td>{fmt(r.tab_financial_transactions)}</td><td>{money2(r.expected_incentive)}</td><td>{money2(r.actual_commission)}</td><td>{money2(r.variance)}</td><td>{r.status}</td></tr>)}</tbody></table></div><p className="rr-muted">TAB KPI is shown separately. It will be added to the combined overall control rate only after overall KPI denominator logic is explicitly extended to avoid double counting.</p></section>}

function UploadCard({title,description,file,setFile,result,loading,onUpload,required,xlsxOnly=false}){
  const [drag,setDrag]=useState(false);
  const accept=f=>{if(!f)return;if(xlsxOnly?!/\.xlsx$/i.test(f.name):!/\.(csv|xlsx)$/i.test(f.name)){setPickError(xlsxOnly?"This must be the .xlsx workbook.":"Only CSV or XLSX files can be uploaded.");return}setPickError("");setFile(f)};
  const [pickError,setPickError]=useState("");
  const onChange=e=>{accept(e.target.files?.[0]);e.target.value=""};
  const onDrop=e=>{e.preventDefault();setDrag(false);accept(e.dataTransfer?.files?.[0])};
  const isRequired=/^\s*[12]\./.test(title);
  const v=result?.data?.validation;
  const short=String(description||"").split(/(?<=[.!?])\s/)[0];
  return <div className={`card upload-card ${isRequired?"is-required":""}`}><div className="upload-card-icon"><Upload size={20}/></div><span className={`ux-badge ${isRequired?"req":"opt"}`}>{isRequired?"Required":"Optional"}</span><h3>{title}</h3><p>{short}</p>{description&&description!==short&&<details className="ux-more"><summary>More details</summary><p>{description}</p></details>}
    <label className={`dropzone ${drag?"drag":""} ${file?"has-file":""}`} onDragOver={e=>{e.preventDefault();setDrag(true)}} onDragLeave={()=>setDrag(false)} onDrop={onDrop}><input type="file" accept={xlsxOnly?".xlsx":".csv,.xlsx"} onChange={onChange}/><FileCheck2 size={24}/><strong>{file?file.name:"Drop a file here or click to choose"}</strong><span>{file?`${(file.size/1024/1024).toFixed(2)} MB`:(xlsxOnly?"XLSX workbook":"CSV or XLSX")}</span></label>
    {pickError&&<div className="ux-inline-error" role="alert"><AlertTriangle size={13}/> {pickError}</div>}
    <details className="ux-more"><summary>Columns this file needs</summary><p>{required}</p></details>
    {file&&<div className="selected-file"><CheckCircle2 size={14}/> Ready to upload: <strong>{file.name}</strong><button type="button" className="ux-linkbtn" onClick={()=>setFile(null)}>Remove</button></div>}
    <button className="primary-btn full" disabled={!file||loading} onClick={onUpload}>{loading?<><RefreshCw size={15} className="spin"/> Validating...</>:<><Upload size={15}/> Upload & Validate</>}</button>
    {result&&<div className={`upload-result ${result.ok&&v?.valid?"success":"error"}`}>{!result.ok?<><AlertTriangle size={16}/><div><strong>Upload failed</strong><span>{result.error}</span></div></>:<><CheckCircle2 size={16}/><div><strong>{v?.valid?"Validation successful":"Validation blocked"}</strong><span>{v?.rows??0} rows · {v?.missing_columns?.length?`Missing: ${v.missing_columns.join(", ")}`:"Required columns found"}</span>{v?.errors?.length>0&&<small>{v.errors.join(" · ")}</small>}{v?.warnings?.length>0&&<small>{v.warnings.join(" · ")}</small>}{v?.mapped_columns&&<small>Mapped: {Object.entries(v.mapped_columns).map(([a,b])=>`${a} → ${b}`).join(" · ")}</small>}{result.data?.sheet_name&&<small>Worksheet: {result.data.sheet_name} · Header row: {(Number(v?.header_row_zero_based||0)+1)}</small>}</div></>}</div>}</div>}
function AuditView({auditData,onRefresh,onRun}) {
  if (!auditData) return <div className="upload-page"><div className="card"><CardHeader title="Audit & Reports" subtitle="Loading audit controls and reconciliation history..."/><div className="upload-result info"><RefreshCw size={16} className="spin"/><div><strong>Loading audit data</strong><span>Please wait while the latest reconciliation run and control totals are fetched from the backend.</span></div></div></div></div>;
  if (auditData?.error) return <div className="upload-page"><div className="card"><CardHeader title="Audit & Reports" subtitle="No completed reconciliation run is recorded yet."/><div className="insight info"><AlertTriangle size={17}/><div><strong>Run the reconciliation first</strong><span>Upload the three source files, then click Run Reconciliation. A unique run ID and source hashes will be stored for audit traceability.</span></div></div><button className="primary-btn" onClick={onRun}><Zap size={16}/> Run Reconciliation</button></div></div>;
  const a=auditData?.latest||{}, c=auditData?.controls?.controls||{};
  const checks=[
    ["Successful transactions",c.successful_transaction_count],
    ["Reconciliation groups",c.reconciliation_groups],
    ["Matched groups",c.matched_groups],
    ["Count mismatches",c.count_mismatch_groups],
    ["Shortfall groups",c.shortfall_groups],
    ["Excess groups",c.excess_groups],
    ["Missing commission",c.missing_commission_groups],
    ["Rate master missing",c.rate_master_missing_groups],
    ["Ambiguous rate rules",c.ambiguous_rate_groups],
    ["Unmapped transaction groups",c.unmapped_transaction_groups],
  ];
  return <div className="rr-analysis-page">
    <PageToolbar overline="AUDIT & REPORTS" title="Reconciliation runs and audit trail" text="Every finished run gets its own run number. The exported workbook holds the totals, the exceptions, the rates that were used, a fingerprint of each uploaded file and the earlier runs."/>
    <section className="kpi-grid">{checks.map(([label,value])=><Kpi key={label} icon={label.includes("transaction")?FileCheck2:AlertTriangle} label={label} value={fmt(value)} meta="Current reconciliation run" warning={Number(value||0)>0 && /mismatch|shortfall|excess|missing|ambiguous|unmapped/i.test(label)}/>)}</section>
    <section className="content-grid"><div className="card"><CardHeader title="Latest run" subtitle="Immutable source references for this run"/><div className="table-wrap"><table><tbody><tr><th>Run ID</th><td>{a.run_id}</td></tr><tr><th>Run time (UTC)</th><td>{a.run_at_utc}</td></tr><tr><th>Status</th><td><StatusBadge status={a.status}/></td></tr><tr><th>Transaction file</th><td>{a.transaction_file}</td></tr><tr><th>Commission file</th><td>{a.commission_file}</td></tr><tr><th>Rate master</th><td>{a.rate_master_file}</td></tr><tr><th>Period</th><td>{a.transaction_period_start} → {a.transaction_period_end}</td></tr><tr><th>Calculated expected commission</th><td>{a.expected_commission_calculated==null?"N/A":money(a.expected_commission_calculated)}</td></tr><tr><th>Settlement-comparable expected</th><td>{a.comparable_expected_commission==null?"N/A":money(a.comparable_expected_commission)}</td></tr><tr><th>Comparable actual commission</th><td>{a.actual_comparable_commission==null?"N/A":money(a.actual_comparable_commission)}</td></tr><tr><th>Comparable gap</th><td>{a.comparable_variance==null?"N/A":signedMoney(a.comparable_variance)}</td></tr><tr><th>Final settlement variance</th><td>{a.variance==null?"N/A — source controls unresolved":signedMoney(a.variance)}</td></tr></tbody></table></div></div>
    <div className="card"><CardHeader title="Integrity & control notes" subtitle="What the audit layer guarantees"/><div className="insight-list"><Insight icon={ShieldCheck} title="Source fingerprinting" text="Transaction, commission and rate-master files are fingerprinted with SHA-256 so an exported report can be tied back to the exact source bytes used." tone="success"/><Insight icon={CheckCircle2} title="Deterministic calculation" text="Expected commission comes only from the approved rate/slab master. The system does not infer rates from actual commission." tone="success"/><Insight icon={AlertTriangle} title="Exception transparency" text="Unmapped types, missing rules, ambiguous rules, count mismatches and monetary differences remain visible instead of being silently treated as zero." tone="warning"/><Insight icon={FileText} title="Audit workbook" text="Use Export Report to generate Control Summary, CSP-wise, Transaction Type, CSP + Type, Exceptions, Rate Master Used, Audit Run Log and Source Integrity sheets." tone="info"/></div><div className="head-actions" style={{marginTop:16}}><button className="secondary-btn" onClick={onRefresh}><RefreshCw size={15}/> Refresh Controls</button><button className="primary-btn" onClick={onRun}><Zap size={15}/> Run New Reconciliation</button></div></div></section>
    <section className="card"><CardHeader title="Reconciliation run history" subtitle="Prior runs remain available for audit comparison and source fingerprinting"/><div className="table-wrap"><table><thead><tr><th>Run ID</th><th>Run Time</th><th>Status</th><th>Period</th><th>Calculated Expected</th><th>Comparable Actual</th><th>Final Variance</th></tr></thead><tbody>{(auditData?.history||[]).map((x,i)=><tr key={x.run_id||i}><td>{x.run_id}</td><td>{String(x.run_at_utc||'').replace('T',' ').slice(0,19)}</td><td><StatusBadge status={x.status}/></td><td>{x.transaction_period_start} → {x.transaction_period_end}</td><td>{money(x.expected_commission_calculated ?? x.expected_commission)}</td><td>{money(x.actual_comparable_commission ?? x.actual_commission)}</td><td>{x.variance==null?"N/A":signedMoney(x.variance)}</td></tr>)}</tbody></table></div></section>
  </div>;
}


function PeriodAnalysisView({grain,setGrain,data,error,start,setStart,end,setEnd,csp,setCsp,type,setType}) {
  const sum=k=>data.reduce((t,r)=>t+(Number(r[k])||0),0);
  const unit=grain==="day"?"days":"months";
  return <div className="rr-analysis-page">
    <PageToolbar overline="PERIOD VIEW" title={`${grain==="day"?"Daily":"Monthly"} reconciliation`} text="Every date or month found in the uploaded transaction file. The commission actually paid is shown day by day only when the bank report carries a date; the app never splits it by guesswork.">
      <div className="rr-seg"><button className={grain==="day"?"on":""} onClick={()=>setGrain("day")}>Daily</button><button className={grain==="month"?"on":""} onClick={()=>setGrain("month")}>Monthly</button></div>
    </PageToolbar>
    <div className="rr-card rr-filters"><div className="rr-field"><label>From</label><input type="date" value={start} onChange={e=>setStart(e.target.value)}/></div><div className="rr-field"><label>To</label><input type="date" value={end} onChange={e=>setEnd(e.target.value)}/></div><div className="rr-field"><label>Agent code (optional)</label><input value={csp} onChange={e=>setCsp(e.target.value)} placeholder="All agents"/></div><div className="rr-field"><label>Transaction type (optional)</label><input value={type} onChange={e=>setType(e.target.value)} placeholder="All types"/></div><button className="rr-btn rr-secondary small" onClick={()=>{setStart("");setEnd("");setCsp("");setType("")}}>Clear filters</button></div>
    {error&&<Notice tone="warn" title="Period view unavailable">{error}</Notice>}
    <MiniStats items={[[unit==="days"?"Days shown":"Months shown",fmt(data.length)],["Successful transactions",fmt(sum("successful_transactions"))],["Should earn",money(sum("expected_commission"))],["Actually paid",money(sum("actual_commission"))]]}/>
    <div className="rr-analysis-table-wrap"><table className="rr-analysis-table"><thead><tr><th>Period</th><th>Successful transactions</th><th>Checked</th><th>Coverage</th><th>Transaction amount</th><th>Should earn</th><th>Actually paid</th><th>Difference</th><th>Status</th></tr></thead><tbody>{data.map((r,i)=><tr key={`${r.period}-${i}`}><td><b>{r.period}</b></td><td>{fmt(r.successful_transactions)}</td><td>{fmt(r.eligible_transactions)}</td><td>{Number(r.coverage_pct||0).toFixed(2)}%</td><td>{money(r.transaction_amount)}</td><td>{r.expected_commission==null?"N/A":money(r.expected_commission)}</td><td>{r.actual_commission==null?"N/A":money(r.actual_commission)}</td><td>{r.variance==null?"N/A":signedMoney(r.variance)}</td><td><StatusBadge status={r.reconciliation_status || r.actual_commission_status}/></td></tr>)}</tbody></table>{data.length===0&&<div className="rr-analysis-empty">No {unit} match the selected filters.</div>}</div>
  </div>
}

function Kpi({icon:Icon,label,value,meta,positive,warning,sourceLabel,sourceType}){return <div className="kpi-card"><div className="kpi-top"><div className="kpi-icon"><Icon size={17}/></div>{warning&&<span className="trend warn">Needs attention</span>}</div><div className="kpi-label">{label}</div><div className="kpi-source"><span>{sourceType || "Source"}</span><strong title={sourceLabel || ""}>{sourceLabel || "Current uploaded data"}</strong></div><div className="kpi-value">{value}</div><div className="kpi-meta">{meta}</div></div>}
function CardHeader({title,subtitle,action}){return <div className="card-header"><div><h3>{title}</h3><p>{subtitle}</p></div>{action&&<button className="text-btn">{action}</button>}</div>}
function LegendRow({color,label,value}){return <div className="legend-row"><span><i style={{background:color}}></i>{label}</span><b>{value}</b></div>}
function StatusBadge({status}){const cls=String(status).toLowerCase().replace(/\s+/g,"-");return <span className={`status ${cls}`}>{status}</span>}
function Insight({icon:Icon,title,text,tone}){return <div className={`insight ${tone}`}><Icon size={17}/><div><strong>{title}</strong><span>{text}</span></div></div>}
class FrontendErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) { console.error("Revenue Reconciliation UI render failed", error, info); }
  render() {
    if (this.state.error) return <div style={{fontFamily:"system-ui",padding:28,maxWidth:900,margin:"40px auto",background:"white",border:"1px solid #fecaca",borderRadius:12,color:"#7f1d1d"}}><h2>Dashboard could not render</h2><p>The frontend encountered a JavaScript error instead of showing a blank page.</p><pre style={{whiteSpace:"pre-wrap",background:"#fff7f7",padding:14,borderRadius:8}}>{String(this.state.error?.stack || this.state.error)}</pre><button onClick={()=>window.location.reload()} style={{padding:"10px 14px",background:"#0f766e",color:"white",border:0,borderRadius:8,cursor:"pointer"}}>Reload dashboard</button></div>;
    return this.props.children;
  }
}

function PlatformWorkspacePage() {
 const [status,setStatus]=useState(null), [job,setJob]=useState(null), [message,setMessage]=useState(""), [busy,setBusy]=useState(false), [workspaceId,setWorkspaceId]=useState(localStorage.getItem("eko_platform_workspace_id")||"");
 const platformFetch=async(url, options={})=>{const headers=new Headers(options.headers||{}); const selectedOrg=localStorage.getItem("eko_platform_workspace_id"); if(selectedOrg) headers.set("X-Eko-Workspace",selectedOrg); return fetch(url,{...options,headers});};
 const refresh=async()=>{const r=await platformFetch(`${API_BASE}/api/tenant-workspace/status`);const d=await r.json();if(!r.ok)throw new Error(d.detail||"Workspace unavailable");setStatus(d)};
 useEffect(()=>{refresh().catch(e=>setMessage(e.message));},[]);
 useEffect(()=>{if(!job||!["queued","running"].includes(job.status))return;const timer=setInterval(async()=>{try{const selectedOrg=localStorage.getItem("eko_platform_workspace_id");const statusUrl=`${API_BASE}/api/platform/jobs/${job.id}${selectedOrg?`?organization_id=${encodeURIComponent(selectedOrg)}`:""}`;const r=await platformFetch(statusUrl);const d=await r.json();if(r.ok){setJob(d);if(["succeeded","failed"].includes(d.status)){setMessage(d.status==="succeeded"?"Job completed successfully.":(d.error||"Job failed."));refresh().catch(()=>{});}}}catch(e){setMessage(e.message)}},1500);return()=>clearInterval(timer)},[job?.id,job?.status]);
 const upload=async(kind,file)=>{if(!file)return;setBusy(true);setMessage("");try{const fd=new FormData();fd.append("file",file);const r=await platformFetch(`${API_BASE}/api/tenant-workspace/uploads/${kind}`,{method:"POST",body:fd});const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==="string"?d.detail:JSON.stringify(d.detail));setMessage(`${kind}: uploaded ${d.rows} rows.`);await refresh()}catch(e){setMessage(e.message)}finally{setBusy(false)}};
 const start=async(path)=>{setBusy(true);setMessage("");try{const r=await platformFetch(`${API_BASE}/api/tenant-workspace/${path}`,{method:"POST"});const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==="string"?d.detail:JSON.stringify(d.detail));setJob(d);setMessage(`${path} queued.`)}catch(e){setMessage(e.message)}finally{setBusy(false)}};
 const { signOut: logout } = useAuth();
 return <div style={{minHeight:"100vh",background:"#f8fafc",padding:28,fontFamily:"Inter,system-ui,sans-serif",color:"#0f172a"}}><div style={{maxWidth:980,margin:"0 auto"}}><div style={{display:"flex",justifyContent:"space-between",alignItems:"center",gap:12}}><div><div style={{fontSize:11,fontWeight:800,letterSpacing:2,color:"#0f766e"}}>EKO · SBI PLATFORM</div><h1>Organisation workspace</h1><p style={{color:"#64748b"}}>Tenant-isolated hosted workflow. This path accepts canonical CSV inputs; the local XLSX workflow remains unchanged.</p></div><button onClick={logout}>Sign out</button></div>{message&&<div role="status" style={{padding:12,background:"#ecfeff",borderRadius:8,margin:"16px 0"}}>{message}</div>}<div style={{background:"white",border:"1px solid #e2e8f0",borderRadius:12,padding:20,marginTop:16}}><h2>Workspace selection (super-admin only)</h2><label style={{display:"block",fontWeight:700}}>Organisation ID<input value={workspaceId} onChange={e=>setWorkspaceId(e.target.value)} placeholder="Leave blank for your assigned organisation" style={{display:"block",width:"100%",maxWidth:420,padding:10,marginTop:6,border:"1px solid #cbd5e1",borderRadius:8}}/></label><button style={{marginTop:8}} onClick={()=>{localStorage.setItem("eko_platform_workspace_id",workspaceId.trim());refresh().then(()=>setMessage("Workspace selected and status refreshed.")).catch(e=>setMessage(e.message));}}>Select workspace</button></div><div style={{background:"white",border:"1px solid #e2e8f0",borderRadius:12,padding:20,marginTop:16}}><h2>1. Upload current-period source CSVs</h2>{[ ["transactions","Transactions CSV"],["commission","BC commission CSV"],["rate_master","SBI rate master CSV (optional)" ] ].map(([kind,label])=><label key={kind} style={{display:"block",margin:"14px 0",fontWeight:700}}>{label}<input type="file" accept=".csv,text/csv" disabled={busy} onChange={e=>upload(kind,e.target.files?.[0])} style={{display:"block",marginTop:6}}/></label>)}<button disabled={busy} onClick={()=>refresh().then(()=>setMessage("Workspace status refreshed.")).catch(e=>setMessage(e.message))}>Refresh status</button>{status&&<pre style={{whiteSpace:"pre-wrap",background:"#f1f5f9",padding:12,borderRadius:8}}>{JSON.stringify(status,null,2)}</pre>}</div><div style={{background:"white",border:"1px solid #e2e8f0",borderRadius:12,padding:20,marginTop:16}}><h2>2. Run reconciliation</h2><p>Worker uses the deterministic reconciliation engine. Transaction CSV must use normalized columns: transaction_id, csp_id, transaction_type, amount, transaction_date. Commission CSV must include csp_id and transaction_type.</p><button disabled={busy||!status?.ready_for_reconciliation} onClick={()=>start("reconciliation")}>Run reconciliation</button><button disabled={busy} onClick={()=>start("report-export")} style={{marginLeft:8}}>Export latest result to Excel</button>{job&&<pre style={{whiteSpace:"pre-wrap",background:"#f1f5f9",padding:12,borderRadius:8,marginTop:12}}>{JSON.stringify(job,null,2)}</pre>}<p style={{color:"#64748b",fontSize:12}}>Report download is available at /api/tenant-workspace/reports/latest after export completes.</p></div></div></div>
}

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error('Missing #root element in frontend/index.html');
try { localStorage.removeItem("eko_platform_token"); } catch (_) { /* drop legacy bearer tokens from older releases */ }
createRoot(rootElement).render(<FrontendErrorBoundary><AuthGate apiBase={API_BASE}>{window.location.pathname === "/platform-workspace" ? <PlatformWorkspacePage /> : <App />}</AuthGate></FrontendErrorBoundary>);
