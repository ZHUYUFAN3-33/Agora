import { useEffect, useState, useCallback } from "react";

const STORAGE_KEY = "agora_appearance_muted";
const DEFAULT = "#5F5F5F";

export function useAppearance() {
  const [mutedColor, setMutedColorState] = useState<string>(() => {
    if (typeof window === "undefined") return DEFAULT;
    return localStorage.getItem(STORAGE_KEY) || DEFAULT;
  });

  const applyColor = useCallback((color: string) => {
    document.documentElement.style.setProperty("--app-muted-text", color);
  }, []);

  useEffect(() => {
    applyColor(mutedColor);
  }, [mutedColor, applyColor]);

  const setMutedColor = useCallback((color: string) => {
    setMutedColorState(color);
    localStorage.setItem(STORAGE_KEY, color);
    applyColor(color);
  }, [applyColor]);

  const reset = useCallback(() => {
    setMutedColor(DEFAULT);
  }, [setMutedColor]);

  return { mutedColor, setMutedColor, reset, defaultColor: DEFAULT };
}
