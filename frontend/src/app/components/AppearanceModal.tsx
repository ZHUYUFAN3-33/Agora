"use client";

import React, { useState, useEffect } from "react";
import { motion } from "motion/react";
import { getUiFont, t, type UiLang } from "../i18n/ui";

export function AppearanceModal({
  open,
  onClose,
  mutedColor,
  setMutedColor,
  reset,
  defaultColor,
  lang = "en",
}: {
  open: boolean;
  onClose: () => void;
  mutedColor: string;
  setMutedColor: (c: string) => void;
  reset: () => void;
  defaultColor: string;
  lang?: UiLang;
}) {
  const [hexInput, setHexInput] = useState(mutedColor);
  useEffect(() => { setHexInput(mutedColor); }, [mutedColor]);
  const font = getUiFont(lang);

  const applyHex = () => {
    const v = hexInput.trim();
    if (/^#[0-9A-Fa-f]{6}$/.test(v)) setMutedColor(v);
    else setHexInput(mutedColor);
  };

  if (!open) return null;

  const presets = [
    { label: t(lang, "appearance.presetDeep"), color: "#3A3A3A" },
    { label: t(lang, "appearance.presetDark"), color: "#5F5F5F" },
    { label: t(lang, "appearance.presetMid"), color: "#7F7F7F" },
    { label: t(lang, "appearance.presetLight"), color: "#9C9C9C" },
  ];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
      className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-6"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.97, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.97, y: 8 }}
        transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-[400px] bg-white rounded-[16px] shadow-[0_8px_32px_rgba(0,0,0,0.1)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-5 border-b border-black/8">
          <div>
            <h2 className="text-[16px]" style={{ ...font, fontWeight: 600 }}>
              {t(lang, "appearance.title")}
            </h2>
            <p className="text-[11px] mt-0.5" style={{ ...font, color: "var(--app-muted-text)" }}>
              {t(lang, "appearance.subtitle")}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-black/5 rounded-[8px] transition-colors"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div className="p-6 flex flex-col gap-4">
          <div>
            <label className="text-[10px] uppercase tracking-widest mb-2 block" style={{ ...font, color: "var(--app-muted-text)" }}>
              {t(lang, "appearance.secondary")}
            </label>
            <div className="flex items-center gap-3">
              <input
                type="color"
                value={mutedColor}
                onChange={(e) => setMutedColor(e.target.value)}
                className="w-12 h-10 rounded-[8px] border border-black/15 cursor-pointer p-0"
              />
              <input
                type="text"
                value={hexInput}
                onChange={(e) => setHexInput(e.target.value)}
                onBlur={applyHex}
                onKeyDown={(e) => { if (e.key === "Enter") applyHex(); }}
                className="flex-1 text-[12px] px-3 py-2 border border-black/15 rounded-[8px] outline-none focus:border-black/40 font-mono"
                placeholder="#5F5F5F"
                maxLength={7}
              />
            </div>
          </div>
          <div>
            <div className="flex flex-wrap gap-2">
              {presets.map((p) => (
                <button
                  key={p.color}
                  onClick={() => setMutedColor(p.color)}
                  className="px-3 py-1.5 rounded-[8px] border border-black/15 hover:border-black/30 transition-colors text-[11px]"
                  style={{ ...font, color: p.color, borderColor: mutedColor === p.color ? p.color : undefined }}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          <div className="pt-2">
            <button
              onClick={reset}
              className="text-[11px] hover:underline"
              style={{ ...font, color: "var(--app-muted-text)" }}
            >
              {t(lang, "appearance.reset")} ({defaultColor})
            </button>
          </div>
        </div>
        <div className="flex justify-end px-6 py-4 border-t border-black/8">
          <motion.button
            onClick={onClose}
            whileTap={{ scale: 0.97 }}
            className="px-4 py-2 text-[12px] bg-black text-white rounded-[8px] hover:bg-neutral-800 transition-colors"
            style={font}
          >
            {t(lang, "appearance.done")}
          </motion.button>
        </div>
      </motion.div>
    </motion.div>
  );
}
