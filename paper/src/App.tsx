import { useCallback, useEffect, useState, type ReactNode } from "react";

/** Only spans with clear linguistic realizations are annotated (paper footnote). */
const FOOTNOTE =
  "Only components with direct linguistic realizations are annotated; higher-level constructs are omitted as they do not map to specific text spans.";

const DECISION_CATEGORIES = [
  "Decision identity",
  "Structural authority",
  "Cognitive structure",
  "Reasoning flow",
  "Structural examples",
  "Differentiation note",
  "Constraints",
] as const;

const EXPRESSION_CATEGORIES = [
  "Core personality",
  "Lexical cues",
  "Behavioral constraints",
  "Emotional orientation",
  "Reaction to other agents",
] as const;

type Layer = "decision" | "expression";

type SpanSpec = {
  layer: Layer;
  category: (typeof DECISION_CATEGORIES)[number] | (typeof EXPRESSION_CATEGORIES)[number];
  /** Plain text segment (must appear in order in the line) */
  text: string;
};

type LineSpec = {
  speaker: string;
  /** Full line for display when mode is off */
  plain: string;
  /** Ordered pieces: either plain string or a span key we look up */
  parts: Array<string | SpanSpec>;
};

/** Dummy dialogue: fabricated for the figure; spans chosen to illustrate categories. */
const DUMMY_LINES: LineSpec[] = [
  {
    speaker: "User",
    plain:
      "I'm choosing between two offers—one pays more, the other matches what I care about in the long run.",
    parts: [
      "I'm choosing between two offers—",
      {
        layer: "decision",
        category: "Decision identity",
        text: "one pays more, the other matches what I care about in the long run",
      },
      ".",
    ],
  },
  {
    speaker: "Agent A",
    plain:
      "Let's state the objective clearly: you are comparing total reward against fit with your values, not just headline salary.",
    parts: [
      "Let's ",
      {
        layer: "decision",
        category: "Cognitive structure",
        text: "state the objective clearly",
      },
      ": you are comparing total reward against fit with your values, not just headline salary.",
    ],
  },
  {
    speaker: "Agent B",
    plain:
      "I get how tense this feels—saying that out loud already narrows the emotional noise.",
    parts: [
      {
        layer: "expression",
        category: "Emotional orientation",
        text: "I get how tense this feels",
      },
      "—saying that out loud already narrows the emotional noise.",
    ],
  },
  {
    speaker: "Agent A",
    plain:
      "Concretely: if we write the trade-off as salary vs. mission alignment, which constraint is non-negotiable for you?",
    parts: [
      "Concretely: if we write the trade-off as salary vs. mission alignment, ",
      {
        layer: "decision",
        category: "Constraints",
        text: "which constraint is non-negotiable for you",
      },
      "?",
    ],
  },
  {
    speaker: "Agent B",
    plain:
      "Building on that—I'd soften the binary and ask what 'enough' looks like on each side, so we don't talk past each other.",
    parts: [
      {
        layer: "expression",
        category: "Reaction to other agents",
        text: "Building on that",
      },
      "—I'd soften the binary and ask what 'enough' looks like on each side, so we don't talk past each other.",
    ],
  },
];

const decisionColor = "bg-[#7c3aed]/25 border-b-2 border-[#7c3aed]/80 text-neutral-900";
const expressionColor = "bg-[#e07a5f]/25 border-b-2 border-[#e07a5f]/80 text-neutral-900";

function renderLineParts(parts: LineSpec["parts"], annotated: boolean): ReactNode {
  if (!annotated) return null;
  return parts.map((p, i) => {
    if (typeof p === "string") return <span key={i}>{p}</span>;
    const cls = p.layer === "decision" ? decisionColor : expressionColor;
    return (
      <span key={i} className={cls} title={`${p.layer === "decision" ? "Decision" : "EXPRESSION"} · ${p.category}`}>
        {p.text}
      </span>
    );
  });
}

export default function App() {
  const [paperMode, setPaperMode] = useState(false);

  const onKey = useCallback((e: KeyboardEvent) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target as HTMLElement | null;
    if (t && ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
    if (e.key === "x" || e.key === "X") {
      e.preventDefault();
      setPaperMode((v) => !v);
    }
  }, []);

  useEffect(() => {
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onKey]);

  return (
    <div className="min-h-screen p-6 md:p-10 max-w-[1400px] mx-auto">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-neutral-900">Frame 22</h1>
          <p className="text-sm text-neutral-500 mt-1">
            Press <kbd className="px-1.5 py-0.5 rounded border border-neutral-300 bg-white text-xs font-mono">x</kbd>{" "}
            to {paperMode ? "hide" : "show"} linguistic annotations (dummy dialogue for the paper).
          </p>
        </div>
        <div
          className={`text-xs font-mono px-3 py-1.5 rounded-full border ${
            paperMode ? "border-emerald-600 bg-emerald-50 text-emerald-800" : "border-neutral-300 bg-white text-neutral-600"
          }`}
        >
          {paperMode ? "Annotation mode ON" : "Annotation mode OFF"}
        </div>
      </header>

      {/* Scene Layer */}
      <section className="mb-6">
        <div className="flex items-baseline justify-between mb-2">
          <h2 className="text-sm font-semibold text-neutral-800">Scene Layer</h2>
          <span className="text-xs text-neutral-500">Shared across all agents</span>
        </div>
        <div className="bg-neutral-900 text-white rounded-lg p-4 grid grid-cols-1 md:grid-cols-3 gap-3">
          <ScenePanel
            title="Task"
            items={["Decision objective", "Decision nature", "Temporal boundary"]}
          />
          <ScenePanel
            title="Facts"
            items={["Option space", "Domain knowledge", "Evaluation dimensions", "Trade-offs"]}
          />
          <ScenePanel
            title="Output policy"
            items={[
              "Scope boundaries",
              "Interaction strategy sequence",
              "Rules for information use",
              "Recommendation timing",
            ]}
          />
        </div>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6 items-start">
        {/* Response Examples */}
        <section>
          <div className="flex items-baseline justify-between mb-2">
            <h2 className="text-sm font-semibold text-neutral-800">Response Examples</h2>
            <span className="text-xs text-neutral-500">UI panel</span>
          </div>
          <div className="min-h-[320px] rounded-lg border border-neutral-200 bg-white p-5 shadow-sm">
            {!paperMode ? (
              <div className="space-y-4 text-sm leading-relaxed text-neutral-800">
                {DUMMY_LINES.map((line, idx) => (
                  <p key={idx}>
                    <span className="font-semibold text-neutral-600">{line.speaker}: </span>
                    {line.plain}
                  </p>
                ))}
                <p className="text-xs text-neutral-400 pt-4 border-t border-neutral-100">{FOOTNOTE}</p>
              </div>
            ) : (
              <div className="space-y-4 text-sm leading-relaxed text-neutral-800">
                {DUMMY_LINES.map((line, idx) => (
                  <p key={idx}>
                    <span className="font-semibold text-neutral-600">{line.speaker}: </span>
                    {renderLineParts(line.parts, true)}
                  </p>
                ))}
                <div className="flex flex-wrap gap-4 pt-3 text-xs">
                  <span className="inline-flex items-center gap-2">
                    <span className="h-3 w-3 rounded-sm bg-[#7c3aed]" />
                    Decision layer
                  </span>
                  <span className="inline-flex items-center gap-2">
                    <span className="h-3 w-3 rounded-sm bg-[#e07a5f]" />
                    EXPRESSION
                  </span>
                </div>
                <p className="text-xs text-neutral-500 pt-2 border-t border-neutral-100">{FOOTNOTE}</p>
              </div>
            )}
          </div>
        </section>

        {/* Right: layer legend + category chips */}
        <aside className="space-y-6">
          <LayerBlock
            title="Decision Layer"
            subtitle="Per-agent"
            accentClass="bg-[#7c3aed]"
            categories={[...DECISION_CATEGORIES]}
          />
          <LayerBlock
            title="EXPRESSION"
            subtitle="EXPRESSION FROM TEXT"
            accentClass="bg-[#e07a5f]"
            categories={[...EXPRESSION_CATEGORIES]}
          />
        </aside>
      </div>
    </div>
  );
}

function ScenePanel({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="bg-white text-neutral-900 rounded-md p-3 text-xs">
      <p className="font-semibold text-neutral-800 mb-2">{title}</p>
      <ul className="space-y-1 text-neutral-600 list-disc list-inside">
        {items.map((it) => (
          <li key={it}>{it}</li>
        ))}
      </ul>
    </div>
  );
}

function LayerBlock({
  title,
  subtitle,
  accentClass,
  categories,
}: {
  title: string;
  subtitle: string;
  accentClass: string;
  categories: string[];
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        <span className={`h-3 w-3 rounded-sm ${accentClass}`} />
        <h3 className="text-sm font-semibold text-neutral-900">{title}</h3>
      </div>
      <p className="text-xs text-neutral-500 mb-3">{subtitle}</p>
      <ul className="space-y-2">
        {categories.map((c) => (
          <li key={c}>
            <span className="block w-full text-left text-xs px-3 py-2 rounded-md bg-neutral-900 text-white font-medium">
              {c}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
