"use client";

import React, { createContext, useContext } from "react";
import { useAppearance } from "../hooks/useAppearance";

type AppearanceContextValue = ReturnType<typeof useAppearance>;

const AppearanceContext = createContext<AppearanceContextValue | null>(null);

export function AppearanceProvider({ children }: { children: React.ReactNode }) {
  const value = useAppearance();
  return (
    <AppearanceContext.Provider value={value}>
      {children}
    </AppearanceContext.Provider>
  );
}

export function useAppearanceContext() {
  const ctx = useContext(AppearanceContext);
  if (!ctx) throw new Error("useAppearanceContext must be used within AppearanceProvider");
  return ctx;
}
