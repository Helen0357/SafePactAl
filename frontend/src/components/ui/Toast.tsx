"use client";
import { LucideIcon } from "@/components/ui/Icon";
import type { ToastData } from "@/lib/types";

const TINT: Record<string, string> = {
  success: "var(--state-success)",
  warning: "var(--state-warning)",
  error: "var(--state-error)",
  info: "var(--state-info)",
};

interface ToastProps {
  toast: ToastData | null;
}

export function Toast({ toast }: ToastProps) {
  if (!toast) return null;

  const tint = TINT[toast.kind] ?? TINT.info;
  const icon =
    toast.icon ??
    (toast.kind === "success"
      ? "check-circle"
      : toast.kind === "error"
        ? "alert-circle"
        : "info");

  return (
    <div className="toast-live">
      <span className="toast-ic" style={{ color: tint }}>
        <LucideIcon name={icon} size={18} />
      </span>
      <div>
        <h4>{toast.title}</h4>
        {toast.body && <p>{toast.body}</p>}
      </div>
    </div>
  );
}
