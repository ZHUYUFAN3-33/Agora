import React, { useEffect, useState } from "react";
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

export default function Admin() {
  const navigate = useNavigate();
  const auth = getAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [newPassword, setNewPassword] = useState("");
  const [resetMsg, setResetMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!auth?.token) {
      navigate("/", { replace: true });
      return;
    }
    if (!auth.is_admin) {
      navigate("/chat", { replace: true });
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await authFetch("/admin/users");
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || "Failed to load users");
        if (!cancelled) setUsers(data.users || []);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [auth?.token, auth?.is_admin, navigate]);

  const resetPassword = async () => {
    if (!selected) return;
    setResetMsg(null);
    if (newPassword.length < 4) {
      setResetMsg("Password must be at least 4 characters");
      return;
    }
    const res = await authFetch(`/admin/users/${encodeURIComponent(selected.user_id)}/password`, {
      method: "POST",
      body: JSON.stringify({ password: newPassword }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setResetMsg(data.error || "Reset failed");
      return;
    }
    setResetMsg(`Password reset for ${selected.user_id}`);
    setNewPassword("");
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
          <span className="text-[13px]" style={monoFont}>Admin</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[11px] text-[var(--app-muted-text)]" style={monoFont}>{auth?.user_id}</span>
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
        <section className="border border-black/10 rounded-[12px] overflow-hidden">
          <div className="px-3 py-2 border-b border-black/8 text-[11px] text-[var(--app-muted-text)]" style={monoFont}>
            Users ({users.length})
          </div>
          {loading && <p className="p-3 text-[12px] text-[var(--app-muted-text)]" style={monoFont}>Loading…</p>}
          {error && <p className="p-3 text-[12px] text-red-600" style={monoFont}>{error}</p>}
          <ul className="max-h-[70vh] overflow-y-auto">
            {users.map((u) => (
              <li key={u.user_id}>
                <button
                  type="button"
                  onClick={() => { setSelected(u); setResetMsg(null); }}
                  className={`w-full text-left px-3 py-2.5 border-b border-black/5 hover:bg-black/[0.03] ${
                    selected?.user_id === u.user_id ? "bg-black/[0.05]" : ""
                  }`}
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
              <div>
                <h2 className="text-[15px]" style={{ ...monoFont, fontWeight: 600 }}>{selected.user_id}</h2>
                <p className="text-[11px] text-[var(--app-muted-text)] mt-1" style={monoFont}>
                  created {selected.created_at || "—"} · profile updated {selected.profile_updated_at || "—"}
                </p>
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
                    onClick={() => void resetPassword()}
                    className="h-[40px] px-3 bg-black text-white rounded-[8px] text-[12px] hover:bg-neutral-800"
                    style={monoFont}
                  >
                    Set password
                  </button>
                </div>
                {resetMsg && (
                  <p className="text-[11px] mt-2 text-black/70" style={monoFont}>{resetMsg}</p>
                )}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
