"use client";
import { LucideIcon } from "@/components/ui/Icon";
import type { DebugLine } from "@/lib/types";
import { useEffect, useRef } from "react";

interface DebugTerminalProps {
  open: boolean;
  onToggle: () => void;
  lines: DebugLine[];
}

export function DebugTerminal({ open, onToggle, lines }: DebugTerminalProps) {
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [open, lines]);

  return (
    <div className="mx-auto max-w-6xl px-6 mb-4">
      <div
        className={`bg-slate-900 rounded-3xl overflow-hidden transition-all duration-500 ${open ? "h-48" : "h-12"}`}
      >
        <button
          className="w-full flex items-center justify-between px-6 py-3 text-white/50 hover:text-white transition-colors"
          onClick={onToggle}
        >
          <div className="flex items-center gap-3">
            <LucideIcon name="terminal" size={14} className="text-[#67a1ff]" />
            <span className="text-[11px] font-black uppercase tracking-widest">
              Agent Activity Logs
            </span>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-[10px] bg-white/10 px-2 py-0.5 rounded-full">
              {lines.length} events
            </span>
            <LucideIcon name={open ? "chevron-down" : "chevron-up"} size={16} />
          </div>
        </button>

        <div
          ref={bodyRef}
          className="px-6 pb-4 h-32 overflow-y-auto font-mono text-[11px] space-y-1 scrollbar-hide"
        >
          {lines.map((line, i) => (
            <div key={i} className="flex gap-3 border-b border-white/5 py-1">
              <span
                className={`uppercase font-black ${line.kind === "agent" ? "text-[#67a1ff]" : "text-white/30"}`}
              >
                [{line.kind}]
              </span>
              <span className="text-white/70">{line.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
