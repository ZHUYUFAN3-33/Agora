import React, { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "motion/react";
import { API_BASE, type Scene } from "../data/agents";
import { monoFont } from "../pages/chatConstants";

type FieldOption = { value: string; label: { en?: string; zh?: string } | string };
export type TemplateField = {
  key: string;
  type: string;
  optional?: boolean;
  sensitive?: boolean;
  question: { en?: string; zh?: string } | string;
  options?: FieldOption[];
};

type FieldsTemplate = {
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

function fieldDomId(prefix: string, key: string) {
  return `${prefix}:${key}`;
}

function valuesToObject(fields: TemplateField[] | undefined, values: Record<string, string>) {
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
}

function objectToStringValues(fields: TemplateField[] | undefined, saved: Record<string, unknown>) {
  const out: Record<string, string> = {};
  (fields || []).forEach((f) => {
    const v = saved[f.key];
    if (v == null) out[f.key] = "";
    else if (Array.isArray(v)) out[f.key] = v.join("\n");
    else out[f.key] = String(v);
  });
  return out;
}

function missingRequired(fields: TemplateField[] | undefined, values: Record<string, string>, prefix: string) {
  const missing: string[] = [];
  (fields || []).forEach((f) => {
    if (!f.optional && !(values[f.key] || "").trim()) missing.push(fieldDomId(prefix, f.key));
  });
  return missing;
}

function FieldControls({
  fields,
  values,
  prefix,
  showErrors,
  clearedErrors,
  onChange,
  onFocusClear,
}: {
  fields: TemplateField[];
  values: Record<string, string>;
  prefix: string;
  showErrors: boolean;
  clearedErrors: Record<string, boolean>;
  onChange: (key: string, value: string) => void;
  onFocusClear: (key: string) => void;
}) {
  return (
    <>
      {fields.map((field) => {
        const value = values[field.key] ?? "";
        const label = enLabel(field.question);
        const required = !field.optional;
        const id = fieldDomId(prefix, field.key);
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
              onFocus={() => onFocusClear(field.key)}
              onChange={(e) => onChange(field.key, e.target.value)}
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
                onFocus={() => onFocusClear(field.key)}
                onChange={(e) => onChange(field.key, e.target.value)}
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
              onFocus={() => onFocusClear(field.key)}
              onChange={(e) => onChange(field.key, e.target.value)}
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
            onFocus={() => onFocusClear(field.key)}
            onChange={(e) => onChange(field.key, e.target.value)}
            className={`w-full text-[12px] px-3 py-2 border rounded-[6px] outline-none transition-colors ${borderClass}`}
            style={monoFont}
          />,
        );
      })}
    </>
  );
}

function FormShell({
  title,
  subtitle,
  loadError,
  loading,
  showErrors,
  missingCount,
  onClose,
  onConfirm,
  confirmLabel,
  children,
  scrollRef,
  dismissible = true,
}: {
  title: string;
  subtitle: string;
  loadError: string | null;
  loading: boolean;
  showErrors: boolean;
  missingCount: number;
  onClose?: () => void;
  onConfirm: () => void;
  confirmLabel: string;
  children: React.ReactNode;
  scrollRef: React.RefObject<HTMLDivElement | null>;
  dismissible?: boolean;
}) {
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
          <h2 className="text-[16px]" style={{ ...monoFont, fontWeight: 600 }}>{title}</h2>
          <p className="text-[11px] text-[var(--app-muted-text)] mt-0.5" style={monoFont}>{subtitle}</p>
        </div>
        {dismissible && onClose && (
          <button onClick={onClose} className="p-2 hover:bg-black/5 rounded-[8px] transition-colors" aria-label="Close">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        )}
      </div>

      <div ref={scrollRef} className="px-6 py-5 overflow-y-auto flex-1 min-h-0">
        {loadError && (
          <p className="text-[12px] text-amber-600 border border-amber-200 bg-amber-50 px-3 py-2 rounded-[8px]" style={monoFont}>{loadError}</p>
        )}
        {!loadError && loading && (
          <p className="text-[12px] text-[var(--app-muted-text)]" style={monoFont}>Loading form…</p>
        )}
        {!loadError && !loading && (
          <>
            {showErrors && missingCount > 0 && (
              <p className="text-[12px] text-red-600 border border-red-200 bg-red-50 px-3 py-2 rounded-[8px] mb-4" style={monoFont}>
                Please fill the highlighted required fields ({missingCount} remaining).
              </p>
            )}
            {children}
          </>
        )}
      </div>

      <div className="px-6 py-4 border-t border-black/8 flex items-center justify-between gap-3">
        <p className="text-[10px] text-[var(--app-muted-text)]" style={monoFont}>
          {showErrors && missingCount > 0
            ? `${missingCount} required field${missingCount === 1 ? "" : "s"} missing`
            : "Required fields marked with *"}
        </p>
        <div className="flex gap-2">
          {dismissible && onClose && (
            <motion.button
              onClick={onClose}
              whileTap={{ scale: 0.97 }}
              className="px-4 py-2 text-[12px] border border-black/15 rounded-[8px] hover:bg-black/5 transition-colors"
              style={monoFont}
            >
              Cancel
            </motion.button>
          )}
          <motion.button
            onClick={onConfirm}
            whileTap={{ scale: 0.97 }}
            disabled={loading || !!loadError}
            className="px-4 py-2 text-[12px] bg-black text-white rounded-[8px] hover:bg-neutral-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            style={monoFont}
          >
            {confirmLabel}
          </motion.button>
        </div>
      </div>
    </motion.div>
  );
}

/** Shared basic profile — shown when entering Chat (before scene). */
export function ProfileModal({
  userId,
  onConfirm,
  onClose,
  dismissible = false,
}: {
  userId: string;
  onConfirm: (profile: Record<string, unknown>) => void;
  onClose?: () => void;
  dismissible?: boolean;
}) {
  const [template, setTemplate] = useState<FieldsTemplate | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [clearedErrors, setClearedErrors] = useState<Record<string, boolean>>({});
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    setTemplate(null);
    Promise.all([
      fetch(`${API_BASE}/agora2/profile-template`).then(async (r) => {
        if (!r.ok) throw new Error(`Failed to load profile form (${r.status})`);
        return r.json();
      }),
      fetch(`${API_BASE}/agora2/profile/${encodeURIComponent(userId)}`).then(async (r) => {
        if (!r.ok) return { profile: {} };
        return r.json();
      }),
    ])
      .then(([tmpl, saved]) => {
        if (cancelled) return;
        setTemplate(tmpl);
        setValues(objectToStringValues(tmpl.profile_fields, saved.profile || {}));
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e?.message || "Failed to load profile form");
      });
    return () => { cancelled = true; };
  }, [userId]);

  const missingKeys = useMemo(
    () => missingRequired(template?.profile_fields, values, "profile"),
    [template, values],
  );

  const handleConfirm = async () => {
    if (!template || saving) return;
    if (missingKeys.length > 0) {
      setShowErrors(true);
      setClearedErrors({});
      requestAnimationFrame(() => {
        const el = scrollRef.current?.querySelector(`[data-field-id="${missingKeys[0]}"]`) as HTMLElement | null;
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
      return;
    }
    setSaving(true);
    const profile = valuesToObject(template.profile_fields, values);
    try {
      await fetch(`${API_BASE}/agora2/profile/${encodeURIComponent(userId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile }),
      });
    } catch {
      /* still continue with local profile */
    }
    onConfirm(profile);
    setSaving(false);
  };

  return (
    <FormShell
      title="Your profile"
      subtitle="Basic info used across scenarios · you can update later"
      loadError={loadError}
      loading={!template && !loadError}
      showErrors={showErrors}
      missingCount={missingKeys.length}
      onClose={onClose}
      onConfirm={() => void handleConfirm()}
      confirmLabel={saving ? "Saving…" : "Continue"}
      scrollRef={scrollRef}
      dismissible={dismissible}
    >
      {template && (
        <div className="border border-black/10 rounded-[12px] p-4 bg-black/[0.02]">
          <FieldControls
            fields={template.profile_fields || []}
            values={values}
            prefix="profile"
            showErrors={showErrors}
            clearedErrors={clearedErrors}
            onChange={(key, value) => {
              const id = fieldDomId("profile", key);
              setClearedErrors((prev) => (prev[id] ? prev : { ...prev, [id]: true }));
              setValues((prev) => ({ ...prev, [key]: value }));
            }}
            onFocusClear={(key) => {
              const id = fieldDomId("profile", key);
              setClearedErrors((prev) => (prev[id] ? prev : { ...prev, [id]: true }));
            }}
          />
        </div>
      )}
    </FormShell>
  );
}

export type Agora2IntakePayload = {
  scenario_type: string;
  lang: "en";
  intake: Record<string, unknown>;
};

/** Scene-specific intake only — shown after selecting a scenario. */
export function IntakeModal({
  scene,
  onClose,
  onConfirm,
}: {
  scene: Scene;
  onClose: () => void;
  onConfirm: (payload: Agora2IntakePayload) => void;
}) {
  const [template, setTemplate] = useState<FieldsTemplate | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
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
      .then((data: FieldsTemplate) => {
        if (cancelled) return;
        setTemplate(data);
        const i: Record<string, string> = {};
        (data.scenario_fields || []).forEach((f) => { i[f.key] = ""; });
        setIntakeValues(i);
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e?.message || "Failed to load intake form");
      });
    return () => { cancelled = true; };
  }, [scene.id]);

  const title = useMemo(() => template?.label?.en || scene.title, [template, scene.title]);
  const missingKeys = useMemo(
    () => missingRequired(template?.scenario_fields, intakeValues, "intake"),
    [template, intakeValues],
  );

  const handleConfirm = () => {
    if (!template || saving) return;
    if (missingKeys.length > 0) {
      setShowErrors(true);
      setClearedErrors({});
      requestAnimationFrame(() => {
        const el = scrollRef.current?.querySelector(`[data-field-id="${missingKeys[0]}"]`) as HTMLElement | null;
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
      return;
    }
    setSaving(true);
    onConfirm({
      scenario_type: scene.id,
      lang: "en",
      intake: valuesToObject(template.scenario_fields, intakeValues),
    });
    setSaving(false);
  };

  return (
    <FormShell
      title="This session"
      subtitle={`${title} · details for this decision only`}
      loadError={loadError}
      loading={!template && !loadError}
      showErrors={showErrors}
      missingCount={missingKeys.length}
      onClose={onClose}
      onConfirm={handleConfirm}
      confirmLabel={saving ? "Saving…" : "Continue"}
      scrollRef={scrollRef}
      dismissible
    >
      {template && (
        <div className="border border-black/10 rounded-[12px] p-4 bg-black/[0.02]">
          <FieldControls
            fields={template.scenario_fields || []}
            values={intakeValues}
            prefix="intake"
            showErrors={showErrors}
            clearedErrors={clearedErrors}
            onChange={(key, value) => {
              const id = fieldDomId("intake", key);
              setClearedErrors((prev) => (prev[id] ? prev : { ...prev, [id]: true }));
              setIntakeValues((prev) => ({ ...prev, [key]: value }));
            }}
            onFocusClear={(key) => {
              const id = fieldDomId("intake", key);
              setClearedErrors((prev) => (prev[id] ? prev : { ...prev, [id]: true }));
            }}
          />
        </div>
      )}
    </FormShell>
  );
}
