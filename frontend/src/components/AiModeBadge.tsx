"use client";

import React from "react";
import { useFactoryStore } from "@/store/useFactoryStore";

/**
 * Discloses whether the last run actually used the LLM. Numbers always come from the
 * solver; this tells the viewer whether extraction/narration was Gemini or a fallback.
 */
export function AiModeBadge({ className = "" }: { className?: string }) {
  const aiMode = useFactoryStore((s) => s.aiMode);
  if (!aiMode) return null;

  const styles =
    aiMode.overall === "llm"
      ? "bg-emerald-100 text-emerald-900 border-emerald-300"
      : aiMode.overall === "mixed"
      ? "bg-amber-100 text-amber-900 border-amber-300"
      : "bg-charcoal-900/10 text-charcoal-800 border-charcoal-900/20";
  const label =
    aiMode.overall === "llm"
      ? `LLM: ${aiMode.model}`
      : aiMode.overall === "mixed"
      ? "LLM partially unavailable"
      : "LLM offline — rule-based fallback";

  return (
    <span
      role="status"
      title={aiMode.note}
      className={`inline-flex items-center gap-1 text-[10px] font-mono font-bold px-2 py-0.5 rounded-full border ${styles} ${className}`}
    >
      {label}
    </span>
  );
}
