"use client";
import * as LucideIcons from "lucide-react";
import React from "react";

interface IconProps {
  name: string;
  size?: number;
  strokeWidth?: number;
  className?: string;
  color?: string;
  style?: React.CSSProperties;
}

const ICON_MAP: Record<string, string> = {
  "alert-triangle": "TriangleAlert",
  "alert-circle": "CircleAlert",
  "help-circle": "CircleHelp",
  "shield-alert": "ShieldAlert",
  "message-circle": "MessageCircle",
  "search-x": "SearchCode",
  plus: "Plus",
  mic: "Mic",
  phone: "Phone",
};

function toPascal(name: string): string {
  return name
    .split("-")
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join("");
}

export function LucideIcon({
  name,
  size = 18,
  strokeWidth = 1.75,
  className,
  color,
  style,
}: IconProps) {
  const pascalName = ICON_MAP[name] || toPascal(name);

  const IconComponent = (LucideIcons as any)[pascalName];

  if (!IconComponent) {
    console.warn(
      `Icon "${name}" (as ${pascalName}) not found in lucide-react.`,
    );
    const Fallback = LucideIcons.CircleHelp || LucideIcons.HelpCircle;

    if (!Fallback) return null;

    return (
      <Fallback
        size={size}
        strokeWidth={strokeWidth}
        className={className}
        color={color}
      />
    );
  }

  return (
    <IconComponent
      size={size}
      strokeWidth={strokeWidth}
      className={className}
      color={color}
      style={style}
    />
  );
}
