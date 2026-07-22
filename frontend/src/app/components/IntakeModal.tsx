import React, { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "motion/react";
import { API_BASE, type Scene } from "../data/agents";
import { monoFont } from "../pages/chatConstants";

type FieldOption = { value: string; label: { en?: string; zh?: string } | string };
type TemplateField = {
  key: string;
  type: string;
  optional?: boolean;
  sensitive?: boolean;
  question: { en?: string; zh?: string } | string;
  options?: FieldOption[];
};

type ScenarioTemplate = {
  label?: { en?: string; zh?: string };
  profile_fields?: TemplateField[];
  scenario_fields?: TemplateField[];
};

function enLabel(q: TemplateField["question"] | FieldOption["label"]): string {
  if (typeof q === "string") return q;
  return q?.en || q?.zh || "";
}

function parseList(raw: string): string[] {
  return raw
    .split(/\n|,/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function fieldKey(layer: "profile" | "intake", key: string) {
  return `${layer}:${key}`;
}

export type Agora2IntakePayload = {
  scenario_type: string;
  lang: "en";
  profile: Record<string, unknown>;
  intake: Record<string, unknown>;
};

export function IntakeModal({
  scene,
  onClose,
  onConfirm,
}: {
  scene: Scene;
  onClose: () => void;
  onConfirm: (payload: Agora2IntakePayload) => void;
}) {
  const [template, setTemplate] = useState<ScenarioTemplate | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [profileValues, setProfileValues] = useState<Record<string, string>>({});
  const [intakeValues, setIntakeValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [clearedErrors, setClearedErrors] = useState<Record<string, boolean>>({});
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    setTemplate(null);
    setShowErrors(false);
    setClearedErrors({});
    fetch(`${API_BASE}/agora2/template/${scene.id}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`Failed to load template (${r.status})`);
        return r.json();
      })
      .then((data: ScenarioTemplate) => {
        if (cancelled) return;
        setTemplate(data);
        const p: Record<string, string> = {};
        const i: Record<string, string> = {};
        (data.profile_fields || []).forEach((f) => { p[f.key] = ""; });
        (data.scenario_fields || []).forEach((f) => { i[f.key] = ""; });
        setProfileValues(p);
        setIntakeValues(i);
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e?.message || "Failed to load intake form");
      });
    return () => { cancelled = true; };
  }, [scene.id]);

  const title = useMemo(() => {
    const fromTmpl = template?.label?.en;
    return fromTmpl || scene.title;
  }, [template, scene.title]);

  const missingKeys = useMemo(() => {
    if (!template) return [] as string[];
    const missing: string[] = [];
    const check = (layer: "profile" | "intake", fields: TemplateField[] | undefined, values: Record<string, string>) => {
      (fields || []).forEach((f) => {
        if (!f.optional && !(values[f.key] || "").trim()) {
          missing.push(fieldKey(layer, f.key));
        }
      });
    };
    check("profile", template.profile_fields, profileValues);
    check("intake", template.scenario_fields, intakeValues);
    return missing;
  }, [template, profileValues, intakeValues]);

  const setField = (
    layer: "profile" | "intake",
    key: string,
    value: string,
  ) => {
    const id = fieldKey(layer, key);
    setClearedErrors((prev) => (prev[id] ? prev : { ...prev, [id]: true }));
    if (layer === "profile") setProfileValues((prev) => ({ ...prev, [key]: value }));
    else setIntakeValues((prev) => ({ ...prev, [key]: value }));
  };

  const clearFieldError = (layer: "profile" | "intake", key: string) => {
    const id = fieldKey(layer, key);
    setClearedErrors((prev) => (prev[id] ? prev : { ...prev, [id]: true }));
  };

  const renderField = (field: TemplateField, layer: "profile" | "intake") => {
    const values = layer === "profile" ? profileValues : intakeValues;
    const value = values[field.key] ?? "";
    const label = enLabel(field.question);
    const required = !field.optional;
    const id = fieldKey(layer, field.key);
    const invalid = showErrors && required && !value.trim() && !clearedErrors[id];
    const borderClass = invalid
      ? "border-red-500 focus:border-red-500"
      : "border-black/15 focus:border-black/40";
    const labelClass = invalid
      ? "text-[12px] text-red-600 mb-1.5 block"
      : "text-[12px] text-black/70 mb-1.5 block";

    const commonLabel = (
      <label htmlFor={id} className={labelClass} style={monoFont}>
        {label}{required ? " *" : " (optional)"}
      </label>
    );

    const wrap = (control: React.ReactNode) => (
      <div key={id} data-field-id={id} className="mb-4">
        {commonLabel}
        {control}
        {invalid && (
          <p className="text-[10px] text-red-500 mt-1" style={monoFont}>Required</p>
        )}
      </div>
    );

    if (field.type === "select" && field.options?.length) {
      return wrap(
        <select
          id={id}
          value={value}
          onFocus={() => clearFieldError(layer, field.key)}
          onChange={(e) => setField(layer, field.key, e.target.value)}
          className={`w-full text-[12px] px-3 py-2 border rounded-[6px] outline-none transition-colors bg-white ${borderClass}`}
          style={monoFont}
        >
          <option value="">Select…</option>
          {field.options.map((o) => (
            <option key={o.value} value={o.value}>{enLabel(o.label)}</option>
          ))}
        </select>,
      );
    }

    if (field.type === "list") {
      return wrap(
        <>
          <p className="text-[10px] text-[var(--app-muted-text)] mb-1.5" style={monoFont}>One item per line</p>
          <textarea
            id={id}
            rows={3}
            value={value}
            onFocus={() => clearFieldError(layer, field.key)}
            onChange={(e) => setField(layer, field.key, e.target.value)}
            className={`w-full text-[12px] px-3 py-2 border rounded-[6px] outline-none resize-none leading-relaxed transition-colors ${borderClass}`}
            style={monoFont}
          />
        </>,
      );
    }

    if (field.type === "number") {
      return wrap(
        <input
          id={id}
          type="number"
          value={value}
          onFocus={() => clearFieldError(layer, field.key)}
          onChange={(e) => setField(layer, field.key, e.target.value)}
          className={`w-full text-[12px] px-3 py-2 border rounded-[6px] outline-none transition-colors ${borderClass}`}
          style={monoFont}
        />,
      );
    }

    return wrap(
      <input
        id={id}
        type="text"
        value={value}
        onFocus={() => clearFieldError(layer, field.key)}
        onChange={(e) => setField(layer, field.key, e.target.value)}
        className={`w-full text-[12px] px-3 py-2 border rounded-[6px] outline-none transition-colors ${borderClass}`}
        style={monoFont}
      />,
    );
  };

  const handleConfirm = () => {
    if (!template || saving) return;
    if (missingKeys.length > 0) {
      setShowErrors(true);
      setClearedErrors({});
      requestAnimationFrame(() => {
        const first = missingKeys[0];
        const el = scrollRef.current?.querySelector(`[data-field-id="${first}"]`) as HTMLElement | null;
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
      return;
    }

    setSaving(true);
    const coerce = (fields: TemplateField[] | undefined, values: Record<string, string>) => {
      const out: Record<string, unknown> = {};
      (fields || []).forEach((f) => {
        const raw = (values[f.key] || "").trim();
        if (!raw) return;
        if (f.type === "number") {
          const n = Number(raw);
          out[f.key] = Number.isFinite(n) ? n : raw;
        } else if (f.type === "list") {
          out[f.key] = parseList(raw);
        } else {
          out[f.key] = raw;
        }
      });
      return out;
    };

    onConfirm({
      scenario_type: scene.id,
      lang: "en",
      profile: coerce(template.profile_fields, profileValues),
      intake: coerce(template.scenario_fields, intakeValues),
    });
    setSaving(false);
  };

  return (
      <motion.div
        initial={{ opacity: 0, scale: 0.97, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.97, y: 8 }}
        transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-[720px] bg-white rounded-[16px] shadow-[0_8px_32px_rgba(0,0,0,0.1)] overflow-hidden flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-5 border-b border-black/8">
          <div>
            <h2 className="text-[16px]" style={{ ...monoFont, fontWeight: 600 }}>Session Intake</h2>
            <p className="text-[11px] text-[var(--app-muted-text)] mt-0.5" style={monoFont}>
              {title} · complete before chat starts
            </p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-black/5 rounded-[8px] transition-colors" aria-label="Close">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        <div ref={scrollRef} className="px-6 py-5 overflow-y-auto flex-1 min-h-0">
          {loadError && (
            <p className="text-[12px] text-amber-600 border border-amber-200 bg-amber-50 px-3 py-2 rounded-[8px]" style={monoFont}>{loadError}</p>
          )}
          {!loadError && !template && (
            <p className="text-[12px] text-[var(--app-muted-text)]" style={monoFont}>Loading form…</p>
          )}
          {template && (
            <>
              {showErrors && missingKeys.length > 0 && (
                <p className="text-[12px] text-red-600 border border-red-200 bg-red-50 px-3 py-2 rounded-[8px] mb-4" style={monoFont}>
                  Please fill the highlighted required fields ({missingKeys.length} remaining).
                </p>
              )}
              <p className="text-[11px] text-[var(--app-muted-text)] tracking-wide mb-3" style={monoFont}>Profile</p>
              <div className="border border-black/10 rounded-[12px] p-4 mb-5 bg-black/[0.02]">
                {(template.profile_fields || []).map((f) => renderField(f, "profile"))}
              </div>
              <p className="text-[11px] text-[var(--app-muted-text)] tracking-wide mb-3" style={monoFont}>This session</p>
              <div className="border border-black/10 rounded-[12px] p-4 bg-black/[0.02]">
                {(template.scenario_fields || []).map((f) => renderField(f, "intake"))}
              </div>
            </>
          )}
        </div>

        <div className="px-6 py-4 border-t border-black/8 flex items-center justify-between gap-3">
          <p className="text-[10px] text-[var(--app-muted-text)]" style={monoFont}>
            {showErrors && missingKeys.length > 0
              ? `${missingKeys.length} required field${missingKeys.length === 1 ? "" : "s"} missing`
              : "Required fields marked with *"}
          </p>
          <div className="flex gap-2">
            <motion.button
              onClick={onClose}
              whileTap={{ scale: 0.97 }}
              className="px-4 py-2 text-[12px] border border-black/15 rounded-[8px] hover:bg-black/5 transition-colors"
              style={monoFont}
            >
              Cancel
            </motion.button>
            <motion.button
              onClick={handleConfirm}
              whileTap={{ scale: 0.97 }}
              disabled={!template || saving}
              className="px-4 py-2 text-[12px] bg-black text-white rounded-[8px] hover:bg-neutral-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              style={monoFont}
            >
              Continue
            </motion.button>
          </div>
        </div>
      </motion.div>
  );
}
