import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { authFetch, getAuth, logoutRequest } from "../auth";
import { monoFont } from "./chatConstants";

type AdminUser = {
  user_id: string;
  is_admin: boolean;
  created_at: string;
  profile_updated_at?: string | null;
  profile: Record<string, unknown>;
  profile_complete?: boolean;
  profile_field_count?: number;
};

type AdminRoom = {
  room_id: string;
  scenario_type?: string;
  title?: string;
  phase?: string;
  updated_at?: string;
  concluded?: boolean;
};

type MemoryRec = {
  session_id: string;
  scenario_type?: string;
  date?: string;
  summary?: string;
  open_threads?: string[];
};

export default function Admin() {
  const navigate = useNavigate();
  const auth = getAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [newPassword, setNewPassword] = useState("");
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [addId, setAddId] = useState("");
  const [addPassword, setAddPassword] = useState("");
  const [addAsAdmin, setAddAsAdmin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rooms, setRooms] = useState<AdminRoom[]>([]);
  const [memory, setMemory] = useState<MemoryRec[]>([]);
  const [roomDetail, setRoomDetail] = useState<string | null>(null);
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());

  const reloadUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch("/admin/users");
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Failed to load users");
      const list: AdminUser[] = data.users || [];
      setUsers(list);
      setSelected((prev) => {
        if (!prev) return null;
        return list.find((u) => u.user_id === prev.user_id) || null;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!auth?.token) {
      navigate("/", { replace: true });
      return;
    }
    if (!auth.is_admin) {
      navigate("/chat", { replace: true });
      return;
    }
    void reloadUsers();
  }, [auth?.token, auth?.is_admin, navigate, reloadUsers]);

  const resetPassword = async () => {
    if (!selected) return;
    setActionMsg(null);
    if (newPassword.length < 4) {
      setActionMsg("Password must be at least 4 characters");
      return;
    }
    setBusy(true);
    try {
      const res = await authFetch(`/admin/users/${encodeURIComponent(selected.user_id)}/password`, {
        method: "POST",
        body: JSON.stringify({ password: newPassword }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setActionMsg(data.error || "Reset failed");
        return;
      }
      setActionMsg(`Password reset for ${selected.user_id}`);
      setNewPassword("");
    } finally {
      setBusy(false);
    }
  };

  const addUser = async () => {
    setActionMsg(null);
    setBusy(true);
    try {
      const res = await authFetch("/admin/users", {
        method: "POST",
        body: JSON.stringify({
          user_id: addId.trim(),
          password: addPassword,
          is_admin: addAsAdmin,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setActionMsg(data.error || "Create failed");
        return;
      }
      setAddId("");
      setAddPassword("");
      setAddAsAdmin(false);
      setActionMsg(`Created user ${data.user_id}`);
      await reloadUsers();
      if (data.user_id) {
        setSelected({
          user_id: data.user_id,
          is_admin: !!data.is_admin,
          created_at: data.created_at || "",
          profile_updated_at: data.profile_updated_at,
          profile: data.profile || {},
          profile_complete: data.profile_complete,
          profile_field_count: data.profile_field_count ?? 0,
        });
      }
    } finally {
      setBusy(false);
    }
  };

  const deleteUser = async () => {
    if (!selected) return;
    if (selected.user_id === auth?.user_id) {
      setActionMsg("Cannot delete your own account");
      return;
    }
    if (!window.confirm(`Delete user "${selected.user_id}"? This cannot be undone.`)) return;
    setActionMsg(null);
    setBusy(true);
    try {
      const res = await authFetch(`/admin/users/${encodeURIComponent(selected.user_id)}`, {
        method: "DELETE",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setActionMsg(data.error || "Delete failed");
        return;
      }
      setActionMsg(`Deleted ${selected.user_id}`);
      setCheckedIds((prev) => {
        const next = new Set(prev);
        next.delete(selected.user_id);
        return next;
      });
      setSelected(null);
      setNewPassword("");
      await reloadUsers();
    } finally {
      setBusy(false);
    }
  };

  const loadUserSessions = useCallback(async (userId: string) => {
    setRooms([]);
    setMemory([]);
    setRoomDetail(null);
    try {
      const res = await authFetch(`/admin/users/${encodeURIComponent(userId)}/rooms`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return;
      setRooms(data.rooms || []);
      setMemory(data.session_memory || []);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (selected?.user_id) void loadUserSessions(selected.user_id);
  }, [selected?.user_id, loadUserSessions]);

  const toggleChecked = (userId: string) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  };

  const toggleCheckAll = () => {
    setCheckedIds((prev) => {
      if (prev.size === users.length) return new Set();
      return new Set(users.map((u) => u.user_id));
    });
  };

  const exportUsers = async (ids: string[]) => {
    if (ids.length === 0) {
      setActionMsg("Select at least one user to export");
      return;
    }
    setBusy(true);
    setActionMsg(null);
    try {
      const qs = ids.map((id) => `user_id=${encodeURIComponent(id)}`).join("&");
      const res = await authFetch(`/admin/export?${qs}`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setActionMsg(data.error || "Export failed");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const cd = res.headers.get("Content-Disposition") || "";
      const m = /filename="?([^"]+)"?/i.exec(cd);
      a.download = m?.[1] || (ids.length === 1 ? `agora_export_${ids[0]}.zip` : `agora_export_${ids.length}users.zip`);
      a.click();
      URL.revokeObjectURL(url);
      setActionMsg(`Exported ${ids.length} user${ids.length === 1 ? "" : "s"}`);
    } finally {
      setBusy(false);
    }
  };

  const exportSelected = () => void exportUsers(Array.from(checkedIds));

  const openRoom = async (roomId: string) => {
    setBusy(true);
    try {
      const res = await authFetch(`/admin/rooms/${encodeURIComponent(roomId)}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setActionMsg(data.error || "Failed to load room");
        return;
      }
      setRoomDetail(JSON.stringify(data, null, 2));
    } finally {
      setBusy(false);
    }
  };

  const deleteRoom = async (roomId: string, title?: string) => {
    if (!selected) return;
    const label = title || roomId;
    if (!window.confirm(`Delete session "${label}"?\nRoom ${roomId} — messages, intake, and memory for this session will be removed. User profile is kept.`)) {
      return;
    }
    setBusy(true);
    setActionMsg(null);
    try {
      const res = await authFetch(`/admin/rooms/${encodeURIComponent(roomId)}`, {
        method: "DELETE",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setActionMsg(data.error || "Delete session failed");
        return;
      }
      setActionMsg(`Deleted session ${roomId}`);
      setRoomDetail(null);
      await loadUserSessions(selected.user_id);
    } finally {
      setBusy(false);
    }
  };

  const deleteMemory = async (rec: MemoryRec) => {
    if (!selected) return;
    if (!window.confirm(`Delete memory summary for session ${rec.session_id}?`)) return;
    setBusy(true);
    setActionMsg(null);
    try {
      const qs = rec.scenario_type
        ? `?scenario_type=${encodeURIComponent(rec.scenario_type)}`
        : "";
      const res = await authFetch(
        `/admin/users/${encodeURIComponent(selected.user_id)}/memory/${encodeURIComponent(rec.session_id)}${qs}`,
        { method: "DELETE" },
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setActionMsg(data.error || "Delete memory failed");
        return;
      }
      setActionMsg(`Deleted memory ${rec.session_id}`);
      await loadUserSessions(selected.user_id);
    } finally {
      setBusy(false);
    }
  };

  const setAdminRole = async (makeAdmin: boolean) => {
    if (!selected) return;
    setActionMsg(null);
    setBusy(true);
    try {
      const res = await authFetch(`/admin/users/${encodeURIComponent(selected.user_id)}/admin`, {
        method: "POST",
        body: JSON.stringify({ is_admin: makeAdmin }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setActionMsg(data.error || "Update failed");
        return;
      }
      setActionMsg(makeAdmin ? `Granted admin to ${selected.user_id}` : `Removed admin from ${selected.user_id}`);
      await reloadUsers();
      if (data.user) {
        setSelected({
          user_id: data.user.user_id,
          is_admin: !!data.user.is_admin,
          created_at: data.user.created_at || "",
          profile_updated_at: data.user.profile_updated_at,
          profile: data.user.profile || {},
          profile_complete: data.user.profile_complete,
          profile_field_count: Object.keys(data.user.profile || {}).length,
        });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-white text-black">
      <header className="h-[56px] border-b border-black/8 flex items-center justify-between px-4">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => navigate("/chat")}
            className="text-[12px] text-black/60 hover:text-black"
            style={monoFont}
          >
            ← Chat
          </button>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5" title={auth?.user_id || "admin"}>
            <div className="w-[7px] h-[7px] rounded-[1.5px] bg-red-500 flex-shrink-0" />
            <span className="text-[10px] tracking-widest text-black" style={monoFont}>
              {(auth?.user_id || "admin").toUpperCase()}
            </span>
          </div>
          <button
            type="button"
            onClick={async () => { await logoutRequest(); navigate("/"); }}
            className="text-[11px] text-black/60 hover:text-black"
            style={monoFont}
          >
            Logout
          </button>
        </div>
      </header>

      <div className="max-w-[1100px] mx-auto p-4 grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4">
        <section className="border border-black/10 rounded-[12px] overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-black/8 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <label className="flex items-center gap-1.5 text-[11px] text-[var(--app-muted-text)] cursor-pointer" style={monoFont}>
                <input
                  type="checkbox"
                  checked={users.length > 0 && checkedIds.size === users.length}
                  onChange={toggleCheckAll}
                  disabled={users.length === 0}
                />
                Users ({users.length})
              </label>
              {checkedIds.size > 0 && (
                <span className="text-[10px] text-black/50" style={monoFont}>{checkedIds.size} selected</span>
              )}
            </div>
            <button
              type="button"
              disabled={busy || checkedIds.size === 0}
              onClick={exportSelected}
              className="h-[28px] px-2.5 bg-black text-white rounded-[6px] text-[11px] hover:bg-neutral-800 disabled:opacity-40 flex-shrink-0"
              style={monoFont}
            >
              Export ({checkedIds.size})
            </button>
          </div>
          <div className="px-3 py-3 border-b border-black/8 flex flex-col gap-2 bg-black/[0.015]">
            <p className="text-[10px] text-[var(--app-muted-text)]" style={monoFont}>Add user</p>
            <input
              type="text"
              value={addId}
              onChange={(e) => setAddId(e.target.value)}
              placeholder="User ID"
              className="h-[36px] px-2 border border-black/15 rounded-[8px] text-[12px] outline-none"
              style={monoFont}
            />
            <input
              type="text"
              value={addPassword}
              onChange={(e) => setAddPassword(e.target.value)}
              placeholder="Password"
              className="h-[36px] px-2 border border-black/15 rounded-[8px] text-[12px] outline-none"
              style={monoFont}
            />
            <label className="flex items-center gap-2 text-[11px] text-black/70" style={monoFont}>
              <input
                type="checkbox"
                checked={addAsAdmin}
                onChange={(e) => setAddAsAdmin(e.target.checked)}
              />
              Make admin
            </label>
            <button
              type="button"
              disabled={busy || !addId.trim() || !addPassword}
              onClick={() => void addUser()}
              className="h-[36px] bg-black text-white rounded-[8px] text-[12px] hover:bg-neutral-800 disabled:opacity-40"
              style={monoFont}
            >
              Add user
            </button>
          </div>
          {loading && <p className="p-3 text-[12px] text-[var(--app-muted-text)]" style={monoFont}>Loading…</p>}
          {error && <p className="p-3 text-[12px] text-red-600" style={monoFont}>{error}</p>}
          <ul className="max-h-[55vh] overflow-y-auto flex-1">
            {users.map((u) => (
              <li
                key={u.user_id}
                className={`flex items-stretch border-b border-black/5 hover:bg-black/[0.03] ${
                  selected?.user_id === u.user_id ? "bg-black/[0.05]" : ""
                }`}
              >
                <label className="flex items-center px-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={checkedIds.has(u.user_id)}
                    onChange={() => toggleChecked(u.user_id)}
                    onClick={(e) => e.stopPropagation()}
                  />
                </label>
                <button
                  type="button"
                  onClick={() => { setSelected(u); setActionMsg(null); }}
                  className="flex-1 min-w-0 text-left py-2.5 pr-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[12px] truncate" style={monoFont}>{u.user_id}</span>
                    {u.is_admin && (
                      <span className="text-[9px] uppercase tracking-wide text-black/50" style={monoFont}>admin</span>
                    )}
                  </div>
                  <p className="text-[10px] text-[var(--app-muted-text)] mt-0.5" style={monoFont}>
                    {u.profile_complete ? "profile complete" : "profile incomplete"} · {u.profile_field_count ?? 0} fields
                  </p>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="border border-black/10 rounded-[12px] p-4 min-h-[320px]">
          {!selected ? (
            <p className="text-[12px] text-[var(--app-muted-text)]" style={monoFont}>Select a user</p>
          ) : (
            <div className="flex flex-col gap-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-[15px]" style={{ ...monoFont, fontWeight: 600 }}>{selected.user_id}</h2>
                  <p className="text-[11px] text-[var(--app-muted-text)] mt-1" style={monoFont}>
                    created {selected.created_at || "—"} · profile updated {selected.profile_updated_at || "—"}
                    {selected.is_admin ? " · admin" : ""}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2 justify-end">
                  {selected.is_admin ? (
                    <button
                      type="button"
                      disabled={busy || selected.user_id === auth?.user_id}
                      onClick={() => void setAdminRole(false)}
                      className="h-[36px] px-3 border border-black/15 text-black/70 rounded-[8px] text-[12px] hover:bg-black/5 disabled:opacity-40"
                      style={monoFont}
                      title={selected.user_id === auth?.user_id ? "Cannot demote yourself" : "Remove admin"}
                    >
                      Remove admin
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void setAdminRole(true)}
                      className="h-[36px] px-3 bg-black text-white rounded-[8px] text-[12px] hover:bg-neutral-800 disabled:opacity-40"
                      style={monoFont}
                    >
                      Make admin
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={busy || selected.user_id === auth?.user_id}
                    onClick={() => void deleteUser()}
                    className="h-[36px] px-3 border border-red-200 text-red-600 rounded-[8px] text-[12px] hover:bg-red-50 disabled:opacity-40"
                    style={monoFont}
                    title={selected.user_id === auth?.user_id ? "Cannot delete yourself" : "Delete user"}
                  >
                    Delete
                  </button>
                </div>
              </div>
              <div>
                <p className="text-[11px] text-[var(--app-muted-text)] mb-2" style={monoFont}>Profile</p>
                <pre
                  className="text-[11px] leading-relaxed whitespace-pre-wrap break-words border border-black/10 rounded-[8px] p-3 bg-black/[0.02] max-h-[360px] overflow-y-auto"
                  style={monoFont}
                >
                  {JSON.stringify(selected.profile || {}, null, 2)}
                </pre>
              </div>
              <div>
                <div className="flex items-center justify-between gap-2 mb-2">
                  <p className="text-[11px] text-[var(--app-muted-text)]" style={monoFont}>
                    Sessions ({rooms.length}) / Memory ({memory.length})
                  </p>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void exportUsers([selected.user_id])}
                    className="h-[32px] px-3 border border-black/15 text-black/80 rounded-[8px] text-[11px] hover:bg-black/5 disabled:opacity-40"
                    style={monoFont}
                  >
                    Export this user
                  </button>
                </div>
                <ul className="border border-black/10 rounded-[8px] max-h-[220px] overflow-y-auto mb-2">
                  {rooms.length === 0 && (
                    <li className="px-3 py-2 text-[11px] text-[var(--app-muted-text)]" style={monoFont}>No sessions</li>
                  )}
                  {rooms.map((r) => (
                    <li
                      key={r.room_id}
                      className="flex items-stretch border-b border-black/5 hover:bg-black/[0.03]"
                    >
                      <button
                        type="button"
                        onClick={() => void openRoom(r.room_id)}
                        className="flex-1 min-w-0 text-left px-3 py-2"
                      >
                        <span className="text-[11px] truncate block" style={monoFont}>
                          {r.title || r.room_id}
                        </span>
                        <span className="text-[10px] text-[var(--app-muted-text)]" style={monoFont}>
                          {r.room_id} · {r.scenario_type || "—"} · {r.phase || "—"} · {r.updated_at || ""}
                        </span>
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void deleteRoom(r.room_id, r.title)}
                        className="flex-shrink-0 px-3 text-[10px] text-red-600 hover:bg-red-50 disabled:opacity-40"
                        style={monoFont}
                        title="Delete this session"
                      >
                        Delete
                      </button>
                    </li>
                  ))}
                </ul>
                {memory.length > 0 && (
                  <ul className="border border-black/10 rounded-[8px] max-h-[140px] overflow-y-auto mb-2">
                    {memory.map((m) => (
                      <li
                        key={`${m.scenario_type || ""}-${m.session_id}`}
                        className="flex items-stretch border-b border-black/5 last:border-b-0"
                      >
                        <div className="flex-1 min-w-0 px-3 py-2">
                          <span className="text-[10px] text-[var(--app-muted-text)] block" style={monoFont}>
                            [{m.date || "—"}] {m.scenario_type || "—"} · {m.session_id}
                          </span>
                          <span className="text-[10px] leading-relaxed whitespace-pre-wrap break-words" style={monoFont}>
                            {m.summary || "(no summary)"}
                          </span>
                        </div>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void deleteMemory(m)}
                          className="flex-shrink-0 px-3 text-[10px] text-red-600 hover:bg-red-50 disabled:opacity-40"
                          style={monoFont}
                          title="Delete this memory summary"
                        >
                          Delete
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {roomDetail && (
                  <pre
                    className="text-[10px] leading-relaxed whitespace-pre-wrap break-words border border-black/10 rounded-[8px] p-2 bg-black/[0.02] max-h-[220px] overflow-y-auto"
                    style={monoFont}
                  >
                    {roomDetail}
                  </pre>
                )}
              </div>
              <div>
                <p className="text-[11px] text-[var(--app-muted-text)] mb-2" style={monoFont}>Reset password</p>
                <div className="flex flex-wrap gap-2 items-center">
                  <input
                    type="text"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="New password"
                    className="h-[40px] px-3 border border-black/15 rounded-[8px] text-[12px] outline-none min-w-[180px]"
                    style={monoFont}
                  />
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void resetPassword()}
                    className="h-[40px] px-3 bg-black text-white rounded-[8px] text-[12px] hover:bg-neutral-800 disabled:opacity-40"
                    style={monoFont}
                  >
                    Set password
                  </button>
                </div>
              </div>
              {actionMsg && (
                <p className="text-[11px] text-black/70" style={monoFont}>{actionMsg}</p>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
