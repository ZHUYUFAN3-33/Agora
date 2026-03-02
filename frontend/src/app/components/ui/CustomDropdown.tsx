"use client";

import React, { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "motion/react";

export interface CustomDropdownOption {
  value: string;
  label: string;
}

interface CustomDropdownProps {
  value: string;
  onChange: (value: string) => void;
  options: CustomDropdownOption[];
  placeholder?: string;
  className?: string;
  triggerClassName?: string;
  size?: "sm" | "md";
  disabled?: boolean;
  style?: React.CSSProperties;
}

export function CustomDropdown({
  value,
  onChange,
  options,
  placeholder = "Select...",
  className = "",
  triggerClassName = "",
  size = "md",
  disabled = false,
  style,
}: CustomDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  const selected = options.find((o) => o.value === value);
  const displayLabel = selected?.label ?? placeholder;

  const sizeClasses = size === "sm" ? "text-[11px] px-2 py-1.5 rounded-[6px]" : "text-[13px] px-4 py-2.5 rounded-[10px]";

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => !disabled && setOpen((o) => !o)}
        className={`w-full flex items-center justify-between gap-2 border border-black/15 outline-none cursor-pointer bg-white hover:border-black/25 focus:border-black/40 transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${sizeClasses} ${triggerClassName}`}
        style={style}
      >
        <span className="truncate text-left" style={style}>{displayLabel}</span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className={`flex-shrink-0 opacity-40 transition-transform ${open ? "rotate-180" : ""}`}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className={`absolute top-full left-0 right-0 mt-1 z-50 bg-white border border-black/15 shadow-[0_2px_12px_rgba(0,0,0,0.06)] overflow-hidden max-h-[220px] overflow-y-auto ${size === "sm" ? "rounded-[6px]" : "rounded-[10px]"}`}
            style={{ minWidth: "100%" }}
          >
            {options.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  onChange(opt.value);
                  setOpen(false);
                }}
                className={`w-full text-left px-4 py-2.5 hover:bg-black/5 transition-colors ${opt.value === value ? "bg-black/5 font-medium" : ""}`}
                style={{ fontSize: size === "sm" ? "11px" : "13px", ...style }}
              >
                {opt.label}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
