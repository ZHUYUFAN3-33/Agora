import React from "react";
import { getUiFont, labelCaseClass, t, userLabel, type UiLang } from "../i18n/ui";
import type { RiverData, RiverLedgerEntry, RiverLedgerPoint } from "./DecisionRiver";

/**
 * OptionLedger — the decision map's landing surface.
 *
 * One card per option: what was said for it, what was said against it, who
 * backed it. Deliberately NOT a criteria x options matrix. A matrix needs a
 * stable criterion vocabulary, and measured on real rooms the automatic one is
 * not stable (the same criterion clustered as both "stability" and "financial
 * risks"; option names came out as row names; 40-44% of rows were speech acts
 * rather than criteria) — which left zero rows where both columns were filled.
 * Worse for a first-time reader, a sparsely filled matrix makes a claim it
 * cannot support: an empty cell reads as "nobody weighed this" even when
 * somebody did.
 *
 * Deleting the row axis keeps the property that actually mattered — the view
 * does not depend on the shape the conversation happened to take — while
 * costing the reader no new concept at all. It is a pros-and-cons list.
 *
 * Every line is a real sentence somebody said, attributed, and clicks through
 * to that moment in the transcript.
 */

function statusStyle(status: string): { bg: string; fg: string } | null {
  if (status === "chosen") return { bg: "#059669", fg: "#ffffff" };
  if (status === "rejected") return { bg: "rgba(0,0,0,0.06)", fg: "rgba(0,0,0,0.45)" };
  return null;
}

/**
 * Backend speaker ids are not names. `intake` is the setup form the reader
 * filled in themselves — printed raw it reads as a fourth participant who was
 * in their private conversation, when the truth is the opposite: they raised
 * it. `agent` is a placeholder with no information at all.
 */
function speakerName(who: string | null | undefined, lang: UiLang, userName?: string): string | null {
  const k = (who || "").trim();
  if (!k || k === "agent") return null;
  if (k === "intake") return t(lang, "map.ledger.fromIntake");
  if (k === "user" || k === "u") return userLabel(lang, userName);
  return k;
}

function PointRow({
  point,
  sign,
  lang,
  userName,
  onPick,
}: {
  point: RiverLedgerPoint;
  sign: "for" | "against";
  lang: UiLang;
  userName?: string;
  onPick: (turnId: string, index: number) => void;
}) {
  const color = sign === "for" ? "#059669" : "#b45309";
  return (
    <button
      type="button"
      onClick={() => onPick(point.turn_id, point.index)}
      className="w-full text-left flex gap-1.5 py-1 px-1.5 rounded-[5px] hover:bg-black/[0.04] group"
      title={t(lang, "map.jumpEvidence")}
    >
      <span className="flex-shrink-0 mt-[3px] text-[10px] leading-none" style={{ color }}>
        {sign === "for" ? "+" : "−"}
      </span>
      <span className="min-w-0">
        <span className="text-[11px] text-black/85 leading-snug">{point.text}</span>
        <span className="text-[10px] text-black/50 ml-1.5 whitespace-nowrap">
          {point.is_user ? userLabel(lang, userName) : point.speaker}
        </span>
      </span>
    </button>
  );
}

function LedgerCard({
  entry,
  lang,
  userName,
  onPick,
}: {
  entry: RiverLedgerEntry;
  lang: UiLang;
  userName?: string;
  onPick: (turnId: string, index: number) => void;
}) {
  const st = statusStyle(entry.status);
  // "raised by" used to label a list that also held endorsers, which inflated
  // how much independent support an option looked like it had.
  const fromIntake = (entry.proposed_by || "").trim() === "intake";
  const raisedBy = speakerName(entry.proposed_by, lang, userName);
  const alsoBacked = (entry.endorsed_by || [])
    .map((b) => speakerName(b, lang, userName))
    .filter((b): b is string => !!b);
  const sep = lang === "en" ? ", " : "、";
  const empty = entry.case_for.length === 0 && entry.case_against.length === 0;
  return (
    <div
      className={`rounded-[10px] border bg-white overflow-hidden ${
        entry.status === "chosen" ? "border-[#059669]/45" : "border-black/12"
      }`}
      style={{ boxShadow: "0 1px 0 rgba(0,0,0,0.03), 0 6px 18px rgba(0,0,0,0.05)" }}
    >
      <div className="px-3 pt-2.5 pb-2 border-b border-black/8">
        <div className="flex items-start gap-2">
          <p className="text-[12.5px] text-black leading-snug flex-1 min-w-0">{entry.label}</p>
          {st && (
            <span
              className={`flex-shrink-0 px-1.5 py-[2px] rounded-[4px] text-[9px] ${labelCaseClass(lang)}`}
              style={{ background: st.bg, color: st.fg }}
            >
              {t(lang, `map.status.${entry.status}`)}
            </span>
          )}
        </div>
        {(raisedBy || alsoBacked.length > 0) && (
          <p className="text-[10px] text-black/50 mt-1">
            {raisedBy && (
              <>
                {/* "raised by <a person>" but "from <what you told us>" — the
                    intake source is a thing the reader said, not a speaker. */}
                {fromIntake ? raisedBy : `${t(lang, "map.ledger.raisedBy")} ${raisedBy}`}
              </>
            )}
            {alsoBacked.length > 0 && (
              <>
                {raisedBy ? " · " : ""}
                {t(lang, "map.ledger.alsoBacked")} {alsoBacked.join(sep)}
              </>
            )}
          </p>
        )}
      </div>

      {empty ? (
        <p className="px-3 py-3 text-[11px] text-black/35">{t(lang, "map.ledger.nothingSaid")}</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-black/8">
          <div className="px-2 py-2">
            <p className={`text-[9px] tracking-wider text-[#059669] px-1.5 mb-0.5 ${labelCaseClass(lang)}`}>
              {t(lang, "map.ledger.for")}
            </p>
            {entry.case_for.length ? (
              entry.case_for.map((p, i) => (
                <PointRow key={`${p.turn_id}-${i}-for`} point={p} sign="for" lang={lang} userName={userName} onPick={onPick} />
              ))
            ) : (
              <p className="text-[10px] text-black/30 px-1.5 py-1">{t(lang, "map.ledger.none")}</p>
            )}
          </div>
          <div className="px-2 py-2">
            <p className={`text-[9px] tracking-wider text-[#b45309] px-1.5 mb-0.5 ${labelCaseClass(lang)}`}>
              {t(lang, "map.ledger.against")}
            </p>
            {entry.case_against.length ? (
              entry.case_against.map((p, i) => (
                <PointRow key={`${p.turn_id}-${i}-against`} point={p} sign="against" lang={lang} userName={userName} onPick={onPick} />
              ))
            ) : (
              <p className="text-[10px] text-black/30 px-1.5 py-1">{t(lang, "map.ledger.none")}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function OptionLedger({
  river,
  lang = "en",
  userName,
  onPick,
}: {
  river: RiverData;
  lang?: UiLang;
  userName?: string;
  onPick: (turnId: string, index: number) => void;
}) {
  const font = getUiFont(lang);
  const ledger = river.ledger || [];
  const g = river.guidance || {};
  const chosen = river.verdict?.chosen_label;

  if (!ledger.length) return null;

  return (
    <div className="h-full overflow-y-auto px-4 py-4" style={font}>
      <div className="max-w-[880px] mx-auto">
        <p className="text-[13px] text-black mb-3">
          {chosen ? (
            <>
              <span className="inline-block w-2 h-2 rounded-full bg-[#059669] mr-2 align-middle" />
              {t(lang, "map.ledger.headlineChosen")}
              <span className="text-black"> {chosen}</span>
            </>
          ) : (
            <>
              <span className="inline-block w-2 h-2 rounded-full bg-black/25 mr-2 align-middle" />
              {t(lang, "map.ledger.headlineOpen")}
            </>
          )}
        </p>

        {/* Above the cards on purpose: what was never answered and what only
            the reader can decide IS the answer; the cards are the evidence for
            it. Below an unbounded scroll of cards these were reachable only by
            a reader who already knew to look. */}
        {(g.against?.length || g.would_change?.length || g.your_call?.length) && (
          <div className="mb-4 rounded-[10px] border border-black/10 bg-white px-3.5 py-3">
            {(["against", "would_change", "your_call"] as const).map((k) =>
              g[k]?.length ? (
                <div key={k} className="mb-2.5 last:mb-0">
                  <p className="text-[11px] text-black/60">{t(lang, `map.guidance.${k}`)}</p>
                  <ul className="mt-1">
                    {g[k]!.map((line, i) => (
                      <li key={i} className="text-[12.5px] text-black/80 leading-relaxed pl-3.5 -indent-3.5">
                        · {line}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null,
            )}
          </div>
        )}

        <div className="flex flex-col gap-3">
          {ledger.map((entry) => (
            <LedgerCard key={entry.option_id} entry={entry} lang={lang} userName={userName} onPick={onPick} />
          ))}
        </div>
      </div>
    </div>
  );
}
