import type { UiLang } from "./i18n/ui";

/** One sitting's intake answers, parked locally until they reach the server.
 *
 * The intake modal's confirm button hands its payload to React state and does
 * nothing else: the only request that carries intake is POST /api/start, and
 * that does not fire until the participant sends their first message. A reload,
 * a closed tab, or a scenario switch in between silently discarded everything
 * they had typed -- while the button had flashed "Saving…" and the welcome
 * screen already read "intake ready". This is what makes that promise true.
 *
 * Keyed by participant so a shared browser cannot spill one person's answers
 * into another's form.
 */
export type IntakeDraft = {
  scenario_type: string;
  lang: UiLang;
  intake: Record<string, unknown>;
  session_update?: string;
  /** Confirmed just before the intake. Kept so a room can be rebuilt after a
   *  backend restart without sending the participant back through both forms. */
  profile: Record<string, unknown> | null;
  saved_at: number;
};

/** A draft is scaffolding for one sitting, not a second copy of the record.
 *
 * Twelve hours covers a sitting that breaks for a meal or runs past midnight
 * (study_tracker itself reads a <=4h gap across midnight as one sitting) and
 * cannot reach the next one, because the protocol requires >=2 days between
 * sessions. So a stale draft can never quietly prefill the following session
 * with last time's answers: past the window it is dropped and the participant
 * gets the form, which is the behaviour the study design expects.
 */
const MAX_AGE_MS = 12 * 60 * 60 * 1000;

const KEY_PREFIX = "agora_intake_draft:";

function keyFor(userId: string): string {
  return `${KEY_PREFIX}${userId || "web_user"}`;
}

export function saveIntakeDraft(
  userId: string,
  draft: Omit<IntakeDraft, "saved_at">,
): void {
  try {
    localStorage.setItem(
      keyFor(userId),
      JSON.stringify({ ...draft, saved_at: Date.now() }),
    );
  } catch {
    /* private mode, or a full quota: a safety net must never block the study */
  }
}

export function loadIntakeDraft(userId: string): IntakeDraft | null {
  try {
    const raw = localStorage.getItem(keyFor(userId));
    if (!raw) return null;
    const d = JSON.parse(raw);
    if (!d?.scenario_type || !d.intake || typeof d.intake !== "object") return null;
    if (!Number.isFinite(d.saved_at) || Date.now() - d.saved_at > MAX_AGE_MS) {
      clearIntakeDraft(userId);
      return null;
    }
    return {
      scenario_type: String(d.scenario_type),
      lang: d.lang === "zh" ? "zh" : "en",
      intake: d.intake as Record<string, unknown>,
      session_update:
        typeof d.session_update === "string" ? d.session_update : undefined,
      profile:
        d.profile && typeof d.profile === "object"
          ? (d.profile as Record<string, unknown>)
          : null,
      saved_at: d.saved_at,
    };
  } catch {
    return null;
  }
}

export function clearIntakeDraft(userId: string): void {
  try {
    localStorage.removeItem(keyFor(userId));
  } catch {
    /* ignore */
  }
}
