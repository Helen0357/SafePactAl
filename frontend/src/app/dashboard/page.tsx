"use client";
import { Nav } from "@/components/Nav";
import { ActionBar } from "@/components/dashboard/ActionBar";
import { FilterTabs } from "@/components/dashboard/FilterTabs";
import { MessagePanel } from "@/components/dashboard/MessagePanel";
import { RiskList } from "@/components/dashboard/RiskList";
import { SearchInput } from "@/components/dashboard/SearchInput";
import { StatsGrid } from "@/components/dashboard/StatsGrid";
import { VoicePanel } from "@/components/dashboard/VoicePanel";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { Toast } from "@/components/ui/Toast";
import { setActiveClause, setSelectedClauses } from "@/lib/api";
import type { FilterTab, RiskItem, ToastData } from "@/lib/types";
import { useStore } from "@/store/useStore";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

type PanelMode = "none" | "message" | "voice";

export default function DashboardPage() {
  const router = useRouter();
  const {
    sessionId,
    riskReport,
    selectedIds,
    debugLines,
    toggleSelect,
    clearSession,
    addDebugLine,
    _hasHydrated,
  } = useStore();

  const [filter, setFilter] = useState<FilterTab>("all");
  const [search, setSearch] = useState("");
  const [termOpen, setTermOpen] = useState(false);
  const [toast, setToast] = useState<ToastData | null>(null);
  const [panelMode, setPanelMode] = useState<PanelMode>("none");
  const [panelRiskIds, setPanelRiskIds] = useState<string[]>([]);
  const [voiceClauseId, setVoiceClauseId] = useState<string | null>(null);

  // Debounce "Ask agent" opens — suppress duplicate logs + active-clause POSTs
  // from rapid double-clicks or React StrictMode re-invokes.
  const lastOpenRef = useRef<{ key: string; ts: number }>({ key: "", ts: 0 });

  useEffect(() => {
    if (!_hasHydrated) return;
    if (!sessionId || !riskReport) router.replace("/");
  }, [_hasHydrated, sessionId, riskReport, router]);

  // Keep the backend's selected clauses in sync with the dashboard selection
  // while a GENERAL voice panel is open (voiceClauseId === null). This makes the
  // selection persist across turns AND update live when the user changes it.
  // Single-clause panels (opened via "Ask agent" on a card) ignore selection.
  useEffect(() => {
    if (panelMode !== "voice" || voiceClauseId !== null || !sessionId) return;
    setSelectedClauses(sessionId, selectedIds)
      .then(() =>
        addDebugLine(
          "tool",
          selectedIds.length
            ? `[Session] selected_clause_ids set: ${selectedIds.join(",")}`
            : "[Session] selected_clause_ids cleared",
        ),
      )
      .catch(() => {});
  }, [selectedIds, panelMode, voiceClauseId, sessionId, addDebugLine]);

  const showToast = useCallback((t: ToastData) => {
    setToast(t);
    setTimeout(() => setToast(null), 3000);
  }, []);

  const closePanel = useCallback(() => setPanelMode("none"), []);

  const openMessagePanel = useCallback((ids: string[]) => {
    setPanelRiskIds(ids);
    setPanelMode("message");
  }, []);

  const openVoicePanel = useCallback((clauseId: string | null = null) => {
    setVoiceClauseId(clauseId);
    setPanelMode("voice");
  }, []);

  const handleFilterChange = useCallback(
    (tab: FilterTab) => {
      setFilter(tab);
      addDebugLine("info", `Filter: ${tab}`);
    },
    [addDebugLine],
  );

  const handleAsk = useCallback(
    async (risk: RiskItem) => {
      const now = Date.now();
      // Skip if this exact clause was just opened (<1s) or its voice panel is
      // already open — avoids the repeated "Voice agent opened" log + dup POST.
      const alreadyOpen = panelMode === "voice" && voiceClauseId === risk.id;
      const rapidRepeat =
        lastOpenRef.current.key === risk.id &&
        now - lastOpenRef.current.ts < 1000;
      lastOpenRef.current = { key: risk.id, ts: now };
      if (alreadyOpen || rapidRepeat) return;

      addDebugLine("info", `Voice agent opened for: ${risk.title}`);
      // Single-clause flow: focus this clause and clear any prior multi-selection
      // so "explain these clauses" can't leak a stale selection. Wait before open.
      if (sessionId) {
        try {
          await Promise.all([
            setActiveClause(sessionId, risk.id),
            setSelectedClauses(sessionId, []),
          ]);
          addDebugLine("tool", `[Session] active_clause_id set: ${risk.id}`);
        } catch {
          addDebugLine("error", `Failed to set active clause: ${risk.id}`);
        }
      }
      openVoicePanel(risk.id);
    },
    [addDebugLine, openVoicePanel, sessionId, panelMode, voiceClauseId],
  );

  const handleGenerate = useCallback(
    (risk: RiskItem) => {
      addDebugLine("info", `Message panel opened for: ${risk.title}`);
      openMessagePanel([risk.id]);
    },
    [addDebugLine, openMessagePanel],
  );

  const handleGenerateSelected = useCallback(
    (risks: RiskItem[]) => {
      addDebugLine("info", `Message panel opened for ${risks.length} risk(s)`);
      openMessagePanel(risks.map((r) => r.id));
    },
    [addDebugLine, openMessagePanel],
  );

  const handleCallAgent = useCallback(async () => {
    const now = Date.now();
    const alreadyOpen = panelMode === "voice" && voiceClauseId === null;
    const rapidRepeat =
      lastOpenRef.current.key === "__general__" &&
      now - lastOpenRef.current.ts < 1000;
    lastOpenRef.current = { key: "__general__", ts: now };
    if (alreadyOpen || rapidRepeat) return;

    addDebugLine("info", "Voice agent opened (action bar)");

    // General call. Clear active_clause_id so a stale single-clause focus can't
    // dominate. The selected clauses are synced (and kept in sync) by the effect
    // below, which also handles the user changing the selection while open.
    if (sessionId) {
      try {
        await setActiveClause(sessionId, "");
        addDebugLine("tool", "[Session] active_clause_id cleared");
      } catch {
        /* non-fatal */
      }
    }
    openVoicePanel(null);
  }, [addDebugLine, openVoicePanel, sessionId, panelMode, voiceClauseId]);

  const handleHome = useCallback(() => {
    clearSession();
    router.push("/");
  }, [clearSession, router]);

  if (!_hasHydrated) return null;
  if (!riskReport || !sessionId) return null;

  const selectedRisks = riskReport.risks.filter((r) =>
    selectedIds.includes(r.id),
  );
  const panelOpen = panelMode !== "none";
  return (
    <div className="min-h-screen bg-slate-50/30 relative overflow-hidden font-sans">
      <div className="fixed inset-0 pointer-events-none z-0">
        <div className="absolute top-[-5%] left-[-5%] w-[45%] h-[45%] bg-[#7aadff15] rounded-full blur-[120px]"></div>
        <div className="absolute bottom-[-5%] right-[-5%] w-[35%] h-[35%] bg-[#67a1ff10] rounded-full blur-[120px]"></div>
      </div>

      <Nav onHome={handleHome} showNewContract />

      <div className="relative z-[100] w-full mx-auto px-[5%] py-10">
        <div className="flex flex-col lg:flex-row gap-8 w-full">
          <div
            className={`flex transition-all duration-500 ease-in-out w-full ${panelOpen ? " mr-[400px]" : "mr-0"}`}
          >
            <div className="flex-1 min-w-0 space-y-2">
              <header className="flex flex-col md:flex-row md:items-start justify-between gap-6">
                <div className="mb-3">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="px-2 py-1 rounded-md bg-[#67a1ff15] text-[#67a1ff] text-[10px] font-black uppercase tracking-widest">
                      Analysis Report
                    </span>
                    <span className="text-slate-300 text-xs">•</span>
                    <span className="text-slate-500 text-xs font-medium">
                      Session {sessionId.slice(0, 8)}
                    </span>
                  </div>
                  <h1 className="text-2xl font-black text-[#202020] tracking-tight leading-none">
                    {riskReport.contract_type}
                  </h1>
                </div>
                <SeverityBadge severity={riskReport.overall_risk} />
              </header>

              <StatsGrid report={riskReport} />

              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 py-1 border-slate-100">
                <FilterTabs
                  active={filter}
                  onChange={handleFilterChange}
                  report={riskReport}
                />
                <SearchInput value={search} onChange={setSearch} />
              </div>

              <RiskList
                risks={riskReport.risks}
                filter={filter}
                search={search}
                selectedIds={selectedIds}
                onToggleSelect={toggleSelect}
                onAsk={handleAsk}
                onGenerate={handleGenerate}
              />
            </div>
          </div>
          <div
            className={`fixed top-0 right-0 h-full  w-[450px] bg-white shadow-md transition-transform duration-500 ease-in-out z-[200] ${panelOpen ? "translate-x-0" : "translate-x-full"}`}
          >
            {panelMode === "message" && (
              <MessagePanel
                riskIds={panelRiskIds}
                risks={riskReport.risks}
                sessionId={sessionId}
                onClose={closePanel}
                onDebugLine={addDebugLine}
              />
            )}
            {panelMode === "voice" && (
              <VoicePanel
                sessionId={sessionId}
                riskReport={riskReport}
                initialClauseId={voiceClauseId}
                selectedClauseIds={voiceClauseId ? [] : selectedIds}
                onClose={closePanel}
                onDebugLine={addDebugLine}
                useLive={process.env.NEXT_PUBLIC_VOICE_MODE === "live"}
              />
            )}
          </div>
        </div>
      </div>

      <ActionBar
        selectedCount={selectedIds.length}
        selectedRisks={selectedRisks}
        debugLines={debugLines}
        termOpen={termOpen}
        onToggleTerm={() => setTermOpen((o) => !o)}
        onGenerateSelected={handleGenerateSelected}
        onCallAgent={handleCallAgent}
      />

      <Toast toast={toast} />
    </div>
  );
}
