"use client";
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { RiskReport, DebugLine } from "@/lib/types";

interface AppStore {
  sessionId: string | null;
  riskReport: RiskReport | null;
  selectedIds: string[];
  debugLines: DebugLine[];
  _hasHydrated: boolean;

  setSession: (sessionId: string, riskReport: RiskReport) => void;
  clearSession: () => void;
  toggleSelect: (id: string) => void;
  clearSelection: () => void;
  addDebugLine: (kind: DebugLine["kind"], text: string) => void;
  setHasHydrated: (v: boolean) => void;
}

export const useStore = create<AppStore>()(
  persist(
    (set) => ({
      sessionId: null,
      riskReport: null,
      selectedIds: [],
      debugLines: [],
      _hasHydrated: false,

      setSession: (sessionId, riskReport) =>
        set({ sessionId, riskReport, selectedIds: [], debugLines: [] }),

      clearSession: () =>
        set({
          sessionId: null,
          riskReport: null,
          selectedIds: [],
          debugLines: [],
        }),

      toggleSelect: (id) =>
        set((state) => {
          const has = state.selectedIds.includes(id);
          return {
            selectedIds: has
              ? state.selectedIds.filter((x) => x !== id)
              : [...state.selectedIds, id],
          };
        }),

      clearSelection: () => set({ selectedIds: [] }),

      addDebugLine: (kind, text) =>
        set((state) => ({
          debugLines: [...state.debugLines, { kind, text }],
        })),

      setHasHydrated: (v) => set({ _hasHydrated: v }),
    }),
    {
      name: "protectme-session",
      storage: createJSONStorage(() => {
        if (typeof window === "undefined") return sessionStorage;
        return localStorage;
      }),
      partialize: (state) => ({
        sessionId: state.sessionId,
        riskReport: state.riskReport,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    },
  ),
);
