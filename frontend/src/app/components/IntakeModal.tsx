import React, { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "motion/react";
import { API_BASE, type Scene } from "../data/agents";
import { monoFont } from "../pages/chatConstants";
import type { UiLang } from "../i18n/ui";

export type { UiLang };

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

function pickLabel(q: TemplateField["question"] | FieldOption["label"], lang: UiLang): string {
  if (typeof q === "string") return q;
  return (lang === "zh" ? q?.zh : q?.en) || q?.en || q?.zh || "";
}

/** Strip trailing Optional markers from template copy so UI can append a single suffix. */
function stripOptionalMarker(label: string): string {
  return label
    .replace(/\s*\(\s*optional\s*\)\s*\.?$/i, "")
    .replace(/\s*[,.]?\s*optional\.?\s*$/i, "")
    .replace(/\s*（可选）\s*$/u, "")
    .replace(/\s*（可跳过）\s*$/u, "")
    .trim();
}

/** One list item per line. Commas stay inside an item (e.g. "Sony, Junior, 7000k, Tokyo"). */
function parseList(raw: string): string[] {
  return raw
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

function fieldDomId(prefix: string, key: string) {
  return `${prefix}:${key}`;
}

function authHeaders(): Record<string, string> {
  try {
    const t = JSON.parse(localStorage.getItem("agora_auth") || "{}").token;
    return t ? { Authorization: `Bearer ${t}` } : {};
  } catch {
    return {};
  }
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

const PRIORITY_DEFAULTS = ["salary", "growth", "stability", "location", "culture"];
/** Collapsed text area height (~3 lines). Longer content shows a Google Forms–style expand. */
const TEXT_COLLAPSE_MAX_PX = 72;
const TEXT_EXPAND_HINT_CHARS = 96;

/** open_in_full — stroke weight matches select chevron (2 @ 24 viewBox). */
function OpenInFullIcon({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M15 3h6v6M9 21H3v-6M21 15v6h-6M3 9V3h6" />
    </svg>
  );
}

function CloseFullscreenIcon({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7" />
    </svg>
  );
}

/** Circular icon button (Google Forms / Material). */
function ExpandIconButton({
  lang,
  onClick,
  label,
}: {
  lang: UiLang;
  onClick: () => void;
  label?: string;
}) {
  const title = label || (lang === "zh" ? "展开" : "Expand");
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onClick();
      }}
      className="absolute bottom-1 right-1 z-[1] w-8 h-8 flex items-center justify-center rounded-[8px] text-black/45 hover:bg-black/5 hover:text-black/70 transition-colors"
    >
      <OpenInFullIcon size={14} />
    </button>
  );
}

/** Full-screen editor dialog — Google Forms expand pattern. */
function ExpandTextDialog({
  open,
  title,
  value,
  lang,
  readOnly = false,
  onChange,
  onClose,
}: {
  open: boolean;
  title: string;
  value: string;
  lang: UiLang;
  readOnly?: boolean;
  onChange?: (v: string) => void;
  onClose: () => void;
}) {
  const areaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!open) return;
    const t = window.setTimeout(() => areaRef.current?.focus(), 40);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center p-4 sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/40"
        aria-label={lang === "zh" ? "关闭" : "Close"}
        onClick={onClose}
      />
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 8, scale: 0.98 }}
        transition={{ duration: 0.15 }}
        className="relative w-full max-w-[480px] max-h-[85vh] bg-white rounded-[16px] shadow-[0_8px_32px_rgba(0,0,0,0.1)] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-black/8">
          <h3 className="text-[15px] text-black truncate pr-2" style={{ ...monoFont, fontWeight: 600 }}>
            {title}
          </h3>
          <button
            type="button"
            title={lang === "zh" ? "收起" : "Collapse"}
            aria-label={lang === "zh" ? "收起" : "Collapse"}
            onClick={onClose}
            className="p-2 shrink-0 hover:bg-black/5 rounded-[8px] transition-colors text-black/60"
          >
            <CloseFullscreenIcon size={16} />
          </button>
        </div>
        <div className="flex-1 min-h-0 px-5 py-4">
          {readOnly ? (
            <div
              className="w-full min-h-[200px] max-h-[55vh] overflow-y-auto text-[12px] text-black whitespace-pre-wrap break-words leading-relaxed"
              style={monoFont}
            >
              {value}
            </div>
          ) : (
            <textarea
              ref={areaRef}
              value={value}
              onChange={(e) => onChange?.(e.target.value)}
              className="w-full min-h-[200px] max-h-[55vh] text-[12px] text-black px-0 py-0 border-0 outline-none resize-none leading-relaxed"
              style={monoFont}
            />
          )}
        </div>
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-black/8">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-[12px] bg-black text-white rounded-[8px] hover:bg-neutral-800 transition-colors"
            style={monoFont}
          >
            {lang === "zh" ? "完成" : "Done"}
          </button>
        </div>
      </motion.div>
    </div>
  );
}

/** Text field: clamped preview + Google Forms–style expand icon → dialog. */
function ExpandableTextField({
  id,
  value,
  borderClass,
  onChange,
  onFocusClear,
  lang,
  label,
}: {
  id: string;
  value: string;
  borderClass: string;
  onChange: (v: string) => void;
  onFocusClear: () => void;
  lang: UiLang;
  label?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const prev = el.style.maxHeight;
    el.style.maxHeight = `${TEXT_COLLAPSE_MAX_PX}px`;
    const needs = el.scrollHeight > TEXT_COLLAPSE_MAX_PX + 1 || value.length > TEXT_EXPAND_HINT_CHARS;
    el.style.maxHeight = prev;
    setOverflows(needs);
  }, [value]);

  return (
    <div className="relative">
      <textarea
        ref={ref}
        id={id}
        value={value}
        rows={3}
        onFocus={onFocusClear}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full text-[12px] px-3 py-2 pr-11 border rounded-[6px] outline-none transition-colors resize-none overflow-hidden ${borderClass}`}
        style={{
          ...monoFont,
          maxHeight: TEXT_COLLAPSE_MAX_PX,
        }}
      />
      {overflows && (
        <ExpandIconButton lang={lang} onClick={() => setOpen(true)} />
      )}
      <ExpandTextDialog
        open={open}
        title={label || (lang === "zh" ? "编辑回答" : "Edit answer")}
        value={value}
        lang={lang}
        onChange={onChange}
        onClose={() => setOpen(false)}
      />
    </div>
  );
}

/** Single list row: clamp long lines; expand opens full dialog. */
function ExpandableListItem({
  item,
  lang,
  onRemove,
  onChange,
}: {
  item: string;
  lang: UiLang;
  onRemove: () => void;
  onChange: (next: string) => void;
}) {
  const textRef = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    setOverflows(el.scrollHeight > el.clientHeight + 1 || item.length > TEXT_EXPAND_HINT_CHARS);
  }, [item]);

  return (
    <li className="flex items-start gap-2">
      <div className="relative flex-1 min-w-0">
        <span
          ref={textRef}
          className="block text-[12px] px-3 py-2 pr-11 border border-black/10 rounded-[6px] bg-white whitespace-pre-wrap break-words line-clamp-2"
          style={monoFont}
        >
          {item}
        </span>
        {overflows && (
          <ExpandIconButton lang={lang} onClick={() => setOpen(true)} />
        )}
        <ExpandTextDialog
          open={open}
          title={lang === "zh" ? "编辑选项" : "Edit option"}
          value={item}
          lang={lang}
          onChange={onChange}
          onClose={() => setOpen(false)}
        />
      </div>
      <button
        type="button"
        className="text-[11px] text-red-600 px-2 py-1 hover:bg-red-50 rounded shrink-0 mt-0.5"
        style={monoFont}
        onClick={onRemove}
      >
        {lang === "zh" ? "删除" : "Remove"}
      </button>
    </li>
  );
}

function ListEditor({
  id,
  value,
  invalid,
  borderClass,
  onChange,
  onFocusClear,
  lang,
}: {
  id: string;
  value: string;
  invalid: boolean;
  borderClass: string;
  onChange: (v: string) => void;
  onFocusClear: () => void;
  lang: UiLang;
}) {
  const items = parseList(value);
  const [draft, setDraft] = useState("");
  const setItems = (next: string[]) => onChange(next.join("\n"));
  return (
    <div>
      <p className="text-[10px] text-[var(--app-muted-text)] mb-1.5" style={monoFont}>
        {lang === "zh"
          ? "可添加多条；每条用回车/添加整段提交，逗号不会拆成多条"
          : "Add multiple items — Enter/Add commits the whole line; commas stay in one entry"}
      </p>
      <ul className="flex flex-col gap-1.5 mb-2">
        {items.map((item, i) => (
          <ExpandableListItem
            key={`${item}-${i}`}
            item={item}
            lang={lang}
            onRemove={() => setItems(items.filter((_, j) => j !== i))}
            onChange={(next) => {
              const copy = [...items];
              copy[i] = next;
              setItems(copy);
            }}
          />
        ))}
      </ul>
      <div className="flex gap-2">
        <input
          id={id}
          type="text"
          value={draft}
          onFocus={onFocusClear}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              const t = draft.trim();
              if (t) {
                setItems([...items, t]);
                setDraft("");
              }
            }
          }}
          placeholder={lang === "zh" ? "输入后回车添加" : "Type and press Enter"}
          className={`flex-1 text-[12px] px-3 py-2 border rounded-[6px] outline-none transition-colors ${borderClass}`}
          style={monoFont}
        />
        <button
          type="button"
          className="px-3 py-2 text-[12px] bg-black text-white rounded-[6px] disabled:opacity-40"
          style={monoFont}
          disabled={!draft.trim()}
          onClick={() => {
            const t = draft.trim();
            if (!t) return;
            setItems([...items, t]);
            setDraft("");
          }}
        >
          {lang === "zh" ? "添加" : "Add"}
        </button>
      </div>
      {invalid && items.length === 0 && (
        <p className="text-[10px] text-red-500 mt-1" style={monoFont}>
          {lang === "zh" ? "必填" : "Required"}
        </p>
      )}
    </div>
  );
}

function PriorityRanker({
  id,
  value,
  borderClass,
  onChange,
  onFocusClear,
  lang,
}: {
  id: string;
  value: string;
  borderClass: string;
  onChange: (v: string) => void;
  onFocusClear: () => void;
  lang: UiLang;
}) {
  const items = parseList(value);
  const list = items.length ? items : [...PRIORITY_DEFAULTS];
  useEffect(() => {
    if (!items.length) onChange(PRIORITY_DEFAULTS.join("\n"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const move = (i: number, dir: -1 | 1) => {
    const next = [...list];
    const j = i + dir;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next.join("\n"));
  };

  return (
    <div id={id} onFocus={onFocusClear}>
      <p className="text-[10px] text-[var(--app-muted-text)] mb-1.5" style={monoFont}>
        {lang === "zh" ? "用上下箭头调整优先级" : "Use arrows to rank (highest first)"}
      </p>
      <ul className="flex flex-col gap-1.5">
        {list.map((item, i) => (
          <li key={`${item}-${i}`} className={`flex items-center gap-2 px-2 py-1.5 border rounded-[6px] bg-white ${borderClass}`}>
            <span className="text-[11px] text-black/40 w-5" style={monoFont}>{i + 1}</span>
            <span className="flex-1 text-[12px]" style={monoFont}>{item}</span>
            <button type="button" className="text-[11px] px-2 py-1 hover:bg-black/5 rounded" style={monoFont} onClick={() => move(i, -1)} disabled={i === 0}>↑</button>
            <button type="button" className="text-[11px] px-2 py-1 hover:bg-black/5 rounded" style={monoFont} onClick={() => move(i, 1)} disabled={i === list.length - 1}>↓</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function FieldControls({
  fields,
  values,
  prefix,
  showErrors,
  clearedErrors,
  onChange,
  onFocusClear,
  lang,
}: {
  fields: TemplateField[];
  values: Record<string, string>;
  prefix: string;
  showErrors: boolean;
  clearedErrors: Record<string, boolean>;
  onChange: (key: string, value: string) => void;
  onFocusClear: (key: string) => void;
  lang: UiLang;
}) {
  return (
    <>
      {fields.map((field) => {
        const value = values[field.key] ?? "";
        const label = stripOptionalMarker(pickLabel(field.question, lang));
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
            {label}{required ? " *" : (lang === "zh" ? "（可跳过）" : " (optional)")}
          </label>
        );

        const wrap = (control: React.ReactNode) => (
          <div key={id} data-field-id={id} className="mb-4">
            {commonLabel}
            {control}
            {invalid && field.type !== "list" && (
              <p className="text-[10px] text-red-500 mt-1" style={monoFont}>
                {lang === "zh" ? "必填" : "Required"}
              </p>
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
              className={`w-full text-[12px] pl-3 pr-9 py-2 border rounded-[6px] outline-none transition-colors bg-white appearance-none bg-no-repeat ${borderClass}`}
              style={{
                ...monoFont,
                backgroundImage:
                  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23000000' stroke-opacity='0.45' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E\")",
                backgroundPosition: "right 12px center",
                backgroundSize: "12px 12px",
              }}
            >
              <option value="">{lang === "zh" ? "请选择…" : "Select…"}</option>
              {field.options.map((o) => (
                <option key={o.value} value={o.value}>{pickLabel(o.label, lang)}</option>
              ))}
            </select>,
          );
        }

        if (field.type === "list" && field.key === "priority_ranking") {
          return wrap(
            <PriorityRanker
              id={id}
              value={value}
              borderClass={borderClass}
              onChange={(v) => onChange(field.key, v)}
              onFocusClear={() => onFocusClear(field.key)}
              lang={lang}
            />,
          );
        }

        if (field.type === "list") {
          return wrap(
            <ListEditor
              id={id}
              value={value}
              invalid={invalid}
              borderClass={borderClass}
              onChange={(v) => onChange(field.key, v)}
              onFocusClear={() => onFocusClear(field.key)}
              lang={lang}
            />,
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
          <ExpandableTextField
            id={id}
            value={value}
            borderClass={borderClass}
            onChange={(v) => onChange(field.key, v)}
            onFocusClear={() => onFocusClear(field.key)}
            lang={lang}
            label={label}
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
  lang,
  instantExit = false,
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
  lang: UiLang;
  /** Skip exit motion when handing off to the next step (avoids backdrop flash). */
  instantExit?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.97, y: 16 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={
        instantExit
          ? { opacity: 0, transition: { duration: 0 } }
          : { opacity: 0, scale: 0.97, y: 8 }
      }
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
          <p className="text-[12px] text-[var(--app-muted-text)]" style={monoFont}>
            {lang === "zh" ? "加载表单…" : "Loading form…"}
          </p>
        )}
        {!loadError && !loading && (
          <>
            {showErrors && missingCount > 0 && (
              <p className="text-[12px] text-red-600 border border-red-200 bg-red-50 px-3 py-2 rounded-[8px] mb-4" style={monoFont}>
                {lang === "zh"
                  ? `请填写标红的必填项（还剩 ${missingCount} 项）`
                  : `Please fill the highlighted required fields (${missingCount} remaining).`}
              </p>
            )}
            {children}
          </>
        )}
      </div>

      <div className="px-6 py-4 border-t border-black/8 flex items-center justify-between gap-3">
        <p className="text-[10px] text-[var(--app-muted-text)]" style={monoFont}>
          {lang === "zh" ? "带 * 为必填" : "Required fields marked with *"}
        </p>
        <div className="flex gap-2">
          {dismissible && onClose && (
            <motion.button
              onClick={onClose}
              whileTap={{ scale: 0.97 }}
              className="px-4 py-2 text-[12px] border border-black/15 rounded-[8px] hover:bg-black/5 transition-colors"
              style={monoFont}
            >
              {lang === "zh" ? "取消" : "Cancel"}
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

/** Scenario-specific profile — shown after scene pick; prefills saved values. */
export function ProfileModal({
  userId,
  scenarioType,
  lang,
  onConfirm,
  onClose,
  dismissible = false,
  instantExit = false,
}: {
  userId: string;
  scenarioType: string;
  lang: UiLang;
  onConfirm: (profile: Record<string, unknown>) => void;
  onClose?: () => void;
  dismissible?: boolean;
  instantExit?: boolean;
}) {
  const [template, setTemplate] = useState<FieldsTemplate | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [clearedErrors, setClearedErrors] = useState<Record<string, boolean>>({});
  const [hadSaved, setHadSaved] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    setTemplate(null);
    Promise.all([
      fetch(`${API_BASE}/agora2/profile-template?scenario_type=${encodeURIComponent(scenarioType)}`).then(async (r) => {
        if (!r.ok) throw new Error(`Failed to load profile form (${r.status})`);
        return r.json();
      }),
      fetch(`${API_BASE}/me/profile?scenario_type=${encodeURIComponent(scenarioType)}`, {
        headers: authHeaders(),
      }).then(async (r) => {
        if (!r.ok) return { profile: {} };
        return r.json();
      }),
    ])
      .then(([tmpl, saved]) => {
        if (cancelled) return;
        setTemplate(tmpl);
        const mapped = objectToStringValues(tmpl.profile_fields, saved.profile || {});
        setValues(mapped);
        setHadSaved(Object.values(mapped).some((v) => String(v).trim()));
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e?.message || "Failed to load profile form");
      });
    return () => { cancelled = true; };
  }, [userId, scenarioType]);

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
      const res = await fetch(`${API_BASE}/me/profile`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ profile, scenario_type: scenarioType }),
      });
      // A 401 from an expired token used to read exactly like success here, so a
      // profile could silently never reach the server. Chat keeps it in the intake
      // draft either way, so this stays non-blocking -- but say so in the console
      // rather than letting the failure leave no trace at all.
      if (!res.ok) console.warn(`profile save failed (${res.status})`);
    } catch {
      /* offline: continue with the local profile */
    }
    onConfirm(profile);
    setSaving(false);
  };

  return (
    <FormShell
      title={lang === "zh" ? "用户档案" : "Your profile"}
      subtitle={
        hadSaved
          ? (lang === "zh" ? "已载入上次保存的值 · 确认或修改后继续" : "Saved values loaded · confirm or edit")
          : (lang === "zh" ? "按场景填写一次，之后可复用" : "Fill once for this scenario · reused later")
      }
      loadError={loadError}
      loading={!template && !loadError}
      showErrors={showErrors}
      missingCount={missingKeys.length}
      onClose={onClose}
      onConfirm={() => void handleConfirm()}
      confirmLabel={saving ? (lang === "zh" ? "保存中…" : "Saving…") : (lang === "zh" ? "确认继续" : "Confirm & continue")}
      scrollRef={scrollRef}
      dismissible={dismissible}
      lang={lang}
      instantExit={instantExit}
    >
      {template && (
        <div className="border border-black/10 rounded-[12px] p-4 bg-black/[0.02]">
          <FieldControls
            fields={template.profile_fields || []}
            values={values}
            prefix="profile"
            showErrors={showErrors}
            clearedErrors={clearedErrors}
            lang={lang}
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
  lang: UiLang;
  intake: Record<string, unknown>;
  session_update?: string;
};

/** Scene-specific intake — after profile; optional session_update for return visits. */
export function IntakeModal({
  scene,
  lang,
  sessionCount = 0,
  lastIntake = null,
  onClose,
  onConfirm,
}: {
  scene: Scene;
  lang: UiLang;
  sessionCount?: number;
  lastIntake?: Record<string, unknown> | null;
  onClose: () => void;
  onConfirm: (payload: Agora2IntakePayload) => void;
}) {
  const [template, setTemplate] = useState<FieldsTemplate | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [intakeValues, setIntakeValues] = useState<Record<string, string>>({});
  const [sessionUpdate, setSessionUpdate] = useState("");
  const [saving, setSaving] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [clearedErrors, setClearedErrors] = useState<Record<string, boolean>>({});
  const scrollRef = useRef<HTMLDivElement>(null);
  const isReturn = sessionCount > 0;

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
        const prefill = lastIntake || {};
        setIntakeValues(objectToStringValues(data.scenario_fields, prefill as Record<string, unknown>));
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e?.message || "Failed to load intake form");
      });
    return () => { cancelled = true; };
  }, [scene.id, lastIntake]);

  const title = useMemo(
    () => (lang === "zh" ? template?.label?.zh : template?.label?.en) || scene.title,
    [template, scene.title, lang],
  );
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
      lang,
      intake: valuesToObject(template.scenario_fields, intakeValues),
      session_update: sessionUpdate.trim() || undefined,
    });
    setSaving(false);
  };

  return (
    <FormShell
      title={lang === "zh" ? "本次会话" : "This session"}
      subtitle={
        isReturn
          ? (lang === "zh"
            ? `${title} · 第 ${sessionCount + 1} 次 · 可先写新情况，再确认/修改表单`
            : `${title} · Session ${sessionCount + 1} · note what's new, then confirm intake`)
          : (lang === "zh" ? `${title} · 仅用于本次决策` : `${title} · details for this decision only`)
      }
      loadError={loadError}
      loading={!template && !loadError}
      showErrors={showErrors}
      missingCount={missingKeys.length}
      onClose={onClose}
      onConfirm={handleConfirm}
      confirmLabel={saving ? (lang === "zh" ? "保存中…" : "Saving…") : (lang === "zh" ? "开始准备对话" : "Continue")}
      scrollRef={scrollRef}
      dismissible
      lang={lang}
    >
      {isReturn && (
        <div className="mb-5 border border-black/10 rounded-[12px] p-4 bg-amber-50/40">
          <label className="text-[12px] text-black/70 mb-1.5 block" style={monoFont}>
            {lang === "zh" ? "距上次以来有什么新情况？" : "What's new since last time?"}
          </label>
          <textarea
            rows={3}
            value={sessionUpdate}
            onChange={(e) => setSessionUpdate(e.target.value)}
            placeholder={lang === "zh" ? "简短补充即可（可跳过）" : "Brief update (optional)"}
            className="w-full text-[12px] px-3 py-2 border border-black/15 rounded-[6px] outline-none resize-none"
            style={monoFont}
          />
        </div>
      )}
      {template && (
        <div className="border border-black/10 rounded-[12px] p-4 bg-black/[0.02]">
          <FieldControls
            fields={template.scenario_fields || []}
            values={intakeValues}
            prefix="intake"
            showErrors={showErrors}
            clearedErrors={clearedErrors}
            lang={lang}
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

/** Lightweight past-session memory list. */
export function MemoryHistoryPanel({
  scenarioType,
  lang,
  onClose,
}: {
  scenarioType: string;
  lang: UiLang;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<Array<{ date?: string; summary?: string; open_threads?: string[] }>>([]);
  const [count, setCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/agora2/memory?scenario_type=${encodeURIComponent(scenarioType)}`, {
      headers: authHeaders(),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(`Failed (${r.status})`);
        return r.json();
      })
      .then((data) => {
        if (cancelled) return;
        setCount(data.session_count || 0);
        setRows(data.recent || []);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || "Failed");
      });
    return () => { cancelled = true; };
  }, [scenarioType]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
      className="w-full max-w-[560px] bg-white rounded-[16px] shadow-[0_8px_32px_rgba(0,0,0,0.1)] overflow-hidden"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex items-center justify-between px-5 py-4 border-b border-black/8">
        <div>
          <h2 className="text-[15px]" style={{ ...monoFont, fontWeight: 600 }}>
            {lang === "zh" ? "历史摘要" : "Past session memory"}
          </h2>
          <p className="text-[11px] text-[var(--app-muted-text)] mt-0.5" style={monoFont}>
            {lang === "zh" ? `共 ${count} 次会话` : `${count} session(s) so far`}
          </p>
        </div>
        <button type="button" onClick={onClose} className="p-2 hover:bg-black/5 rounded-[8px]">✕</button>
      </div>
      <div className="px-5 py-4 max-h-[60vh] overflow-y-auto">
        {error && <p className="text-[12px] text-red-600" style={monoFont}>{error}</p>}
        {!error && rows.length === 0 && (
          <p className="text-[12px] text-[var(--app-muted-text)]" style={monoFont}>
            {lang === "zh" ? "还没有跨 session 记忆（完成一次 Summary 后会出现）" : "No memory yet — appears after you run Summary once."}
          </p>
        )}
        <ul className="flex flex-col gap-3">
          {rows.map((r, i) => (
            <li key={i} className="border border-black/10 rounded-[10px] p-3">
              <p className="text-[10px] text-black/50 mb-1" style={monoFont}>{r.date || "—"}</p>
              <p className="text-[12px] leading-relaxed whitespace-pre-wrap" style={monoFont}>{r.summary || "—"}</p>
              {(r.open_threads || []).length > 0 && (
                <p className="text-[11px] text-black/60 mt-2" style={monoFont}>
                  {(lang === "zh" ? "未竟话题：" : "Open threads: ") + (r.open_threads || []).join(lang === "zh" ? "；" : "; ")}
                </p>
              )}
            </li>
          ))}
        </ul>
      </div>
    </motion.div>
  );
}
