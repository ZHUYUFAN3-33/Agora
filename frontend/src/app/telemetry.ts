/**
 * Client-side behavior telemetry -> POST /api/telemetry/<room> -> {room}_ux.jsonl
 *
 * Records what the user DID with the interface, which no server-side log can see: whether
 * an option chip that was shown ever got clicked, how long the decision map was actually
 * on screen, how long someone sat before replying, drafts they wrote and deleted.
 *
 * PRIVACY: counts and durations only. Never draft text, never per-key timing. The
 * transcripts in this system cover layoffs, burnout and family conflict, and a keystroke
 * stream would reconstruct exactly the content a user decided not to send. Anything added
 * here ships inside the zip the user can download of their own session.
 */

import { authFetch } from "./auth";

type Props = Record<string, unknown>;

interface BufferedEvent {
  event: string;
  client_ts: number;
  props: Props;
}

const FLUSH_INTERVAL_MS = 2000;
const FLUSH_AT_COUNT = 25;

let roomId: string | null = null;
let buffer: BufferedEvent[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
let listenersBound = false;

function clearTimer() {
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
}

/**
 * Best-effort send on page close. sendBeacon defaults to Content-Type text/plain, which
 * Flask's get_json() refuses to parse -- the Blob type below is what makes it land. The
 * server also passes force=True as the other half of that fix.
 */
function flushViaBeacon(room: string, events: BufferedEvent[]) {
  if (typeof navigator === "undefined" || !navigator.sendBeacon) return false;
  const body = new Blob([JSON.stringify({ room_id: room, events })], {
    type: "application/json",
  });
  // No Authorization header is possible on a beacon. Rooms without an owner accept it;
  // for owned rooms the visibilitychange flush below is the one that carries auth, and
  // this is the last-resort duplicate-safe attempt.
  return navigator.sendBeacon(`/api/telemetry/${encodeURIComponent(room)}`, body);
}

function bindUnloadListeners() {
  if (listenersBound || typeof document === "undefined") return;
  listenersBound = true;
  // visibilitychange fires before pagehide on mobile and is the reliable one; both are
  // bound because neither alone covers every browser's close path.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") void flush();
  });
  window.addEventListener("pagehide", () => {
    if (roomId && buffer.length) {
      const pending = buffer;
      buffer = [];
      clearTimer();
      flushViaBeacon(roomId, pending);
    }
  });
}

/** Point the buffer at a room. Flushes whatever the previous room had pending. */
export function setTelemetryRoom(next: string | null) {
  if (next === roomId) return;
  void flush();
  roomId = next;
  bindUnloadListeners();
}

export function emit(event: string, props: Props = {}) {
  if (!roomId) return;
  buffer.push({ event, client_ts: Date.now(), props });
  if (buffer.length >= FLUSH_AT_COUNT) {
    void flush();
    return;
  }
  if (timer === null) {
    timer = setTimeout(() => void flush(), FLUSH_INTERVAL_MS);
  }
}

export async function flush(): Promise<void> {
  clearTimer();
  if (!roomId || buffer.length === 0) return;
  const room = roomId;
  const events = buffer;
  buffer = [];
  try {
    await authFetch(`/telemetry/${encodeURIComponent(room)}`, {
      method: "POST",
      body: JSON.stringify({ room_id: room, events }),
    });
  } catch {
    // Telemetry must never affect the session. Dropped events are dropped.
  }
}

/**
 * Accumulates open/docked/closed time for a panel. The decision map stays MOUNTED while
 * docked, so a naive open-to-unmount dwell would report the user staring at the map when
 * they were actually reading chat. Docked time is tracked separately and subtracted.
 */
export class DwellTracker {
  private openedAt: number | null = null;
  private dockedAt: number | null = null;
  private dockedMs = 0;

  open() {
    this.openedAt = Date.now();
    this.dockedAt = null;
    this.dockedMs = 0;
  }

  dock() {
    if (this.openedAt !== null && this.dockedAt === null) this.dockedAt = Date.now();
  }

  undock() {
    if (this.dockedAt !== null) {
      this.dockedMs += Date.now() - this.dockedAt;
      this.dockedAt = null;
    }
  }

  /** Returns null when it was never opened, so callers can skip emitting a close event. */
  close(): { dwell_ms: number; docked_ms: number; focused_ms: number } | null {
    if (this.openedAt === null) return null;
    this.undock();
    const dwell = Date.now() - this.openedAt;
    const result = {
      dwell_ms: dwell,
      docked_ms: this.dockedMs,
      focused_ms: Math.max(0, dwell - this.dockedMs),
    };
    this.openedAt = null;
    this.dockedMs = 0;
    return result;
  }

  get isOpen() {
    return this.openedAt !== null;
  }
}
