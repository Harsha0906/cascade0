"use client";

import { createContext, useContext } from "react";

export interface ShellInfo {
  factoryId: string;
  factoryName: string;
  role: "owner" | "approver" | "viewer" | string;
  email: string | null;
}

const Ctx = createContext<ShellInfo | null>(null);
export const ShellProvider = Ctx.Provider;

export function useShell(): ShellInfo {
  return (
    useContext(Ctx) ?? { factoryId: "", factoryName: "", role: "viewer", email: null }
  );
}

/** Owners and approvers may edit; viewers only read. */
export function useCanEdit(): boolean {
  const { role } = useShell();
  return role === "owner" || role === "approver";
}
