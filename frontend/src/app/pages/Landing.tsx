import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { motion, AnimatePresence } from "motion/react";
import { LandingLogoSection, DEFAULT_LOGO_GAP, DEFAULT_TEXT_LOGO_OFFSET_X } from "../components/AgoraLogo";
import { getAuth, loginRequest, registerRequest, setAuth } from "../auth";
import svgPaths from "../../imports/svg-czrgecjots";

const LOGO_MARK_URL = "/Assets/logo.png";
const LOGO_GAP_KEY = "agora_logo_gap";
const TEXT_LOGO_OFFSET_KEY = "agora_text_logo_offset_x";
const monoFont = { fontFamily: "'Share Tech Mono', monospace" };
const condensedFont = { fontFamily: "'Barlow Condensed', sans-serif" };

function GoogleIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 16.7538 16.7538" fill="none">
      <g>
        <path clipRule="evenodd" d={svgPaths.p13008700} fill="#4285F4" fillRule="evenodd" />
        <path clipRule="evenodd" d={svgPaths.p2e899a00} fill="#34A853" fillRule="evenodd" />
        <path clipRule="evenodd" d={svgPaths.p1bd76f80} fill="#FBBC05" fillRule="evenodd" />
        <path clipRule="evenodd" d={svgPaths.p2ea14b00} fill="#EA4335" fillRule="evenodd" />
      </g>
    </svg>
  );
}

function AppleIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 17.4822 17.4822" fill="none">
      <rect fill="black" width="17.4822" height="17.4822" />
      <path d={svgPaths.p1bcb9100} fill="white" />
    </svg>
  );
}

export default function Landing() {
  const navigate = useNavigate();
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"landing" | "auth">("landing");
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [splashVisible, setSplashVisible] = useState(true);
  const [logoGap, setLogoGap] = useState(DEFAULT_LOGO_GAP);
  const [textLogoOffsetX, setTextLogoOffsetX] = useState(DEFAULT_TEXT_LOGO_OFFSET_X);
  const [controlVisible, setControlVisible] = useState(false);

  useEffect(() => {
    if (getAuth()?.token) navigate("/chat");
  }, [navigate]);

  useEffect(() => {
    const v1 = localStorage.getItem(LOGO_GAP_KEY);
    const v2 = localStorage.getItem(TEXT_LOGO_OFFSET_KEY);
    if (v1) setLogoGap(Math.min(48, Math.max(0, parseInt(v1, 10))));
    if (v2) setTextLogoOffsetX(Math.min(40, Math.max(-40, parseInt(v2, 10))));
  }, []);

  useEffect(() => {
    const t1 = setTimeout(() => setSplashVisible(false), 1800);
    return () => clearTimeout(t1);
  }, []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === " " && !["INPUT", "TEXTAREA"].includes((e.target as HTMLElement)?.tagName)) {
        e.preventDefault();
        setControlVisible((v) => !v);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const handleLogoGapChange = (px: number) => {
    setLogoGap(px);
    localStorage.setItem(LOGO_GAP_KEY, String(px));
  };
  const handleTextLogoOffsetChange = (px: number) => {
    setTextLogoOffsetX(px);
    localStorage.setItem(TEXT_LOGO_OFFSET_KEY, String(px));
  };
  const handleResetToDefault = () => {
    setLogoGap(DEFAULT_LOGO_GAP);
    setTextLogoOffsetX(DEFAULT_TEXT_LOGO_OFFSET_X);
    localStorage.removeItem(LOGO_GAP_KEY);
    localStorage.removeItem(TEXT_LOGO_OFFSET_KEY);
  };

  const submitAuth = async () => {
    setError(null);
    if (!userId.trim() || !password) {
      setError("Enter user ID and password");
      return;
    }
    setBusy(true);
    try {
      const data = authMode === "login"
        ? await loginRequest(userId.trim(), password)
        : await registerRequest(userId.trim(), password);
      setAuth(data);
      navigate("/chat");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Auth failed");
    } finally {
      setBusy(false);
    }
  };

  const logoSection = (
    <div className="flex justify-center mb-8">
      <LandingLogoSection width={200} logoToTextGap={logoGap} textLogoOffsetX={textLogoOffsetX} />
    </div>
  );

  const spacingControl = controlVisible && (
    <div className="fixed bottom-4 right-4 bg-white/95 border border-black/10 rounded-[10px] shadow-lg px-3 py-2.5 flex flex-col gap-2 z-10">
      <div className="flex items-center gap-3">
        <span className="text-[10px] text-[var(--app-muted-text)] whitespace-nowrap w-20" style={monoFont}>logo–text gap</span>
        <input type="range" min={0} max={48} value={logoGap} onChange={(e) => handleLogoGapChange(parseInt(e.target.value, 10))} className="w-20 h-1.5 accent-black" />
        <span className="text-[10px] text-[var(--app-muted-text)] w-6" style={monoFont}>{logoGap}px</span>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-[10px] text-[var(--app-muted-text)] whitespace-nowrap w-20" style={monoFont}>text logo X</span>
        <input type="range" min={-40} max={40} value={textLogoOffsetX} onChange={(e) => handleTextLogoOffsetChange(parseInt(e.target.value, 10))} className="w-20 h-1.5 accent-black" />
        <span className="text-[10px] text-[var(--app-muted-text)] w-8" style={monoFont}>{textLogoOffsetX}px</span>
      </div>
      <button onClick={handleResetToDefault} className="text-[9px] text-[var(--app-muted-text)] hover:text-black self-start mt-0.5" style={monoFont}>reset to default</button>
    </div>
  );

  if (mode === "auth") {
    return (
      <div className="min-h-screen bg-white flex flex-col items-center justify-center px-6 relative">
        {spacingControl}
        <div className="w-full max-w-[320px] flex flex-col gap-6">
          {logoSection}
          <div className="flex gap-2">
            {(["login", "register"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => { setAuthMode(m); setError(null); }}
                className={`flex-1 h-[36px] rounded-[8px] text-[12px] border transition-colors ${
                  authMode === m ? "bg-black text-white border-black" : "border-black/15 text-black/60 hover:bg-black/5"
                }`}
                style={monoFont}
              >
                {m === "login" ? "Login" : "Register"}
              </button>
            ))}
          </div>
          <div className="flex flex-col gap-3">
            <div className="h-[48px] bg-black rounded-[10px] flex items-center px-4">
              <input
                type="text"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                placeholder="User ID (3–32: a-z, 0-9, _ -)"
                autoComplete="username"
                className="bg-transparent w-full outline-none text-[#828282] placeholder-[#828282]"
                style={{ ...monoFont, fontSize: "13px" }}
              />
            </div>
            <div className="h-[48px] bg-black rounded-[10px] flex items-center px-4">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void submitAuth()}
                placeholder="Password"
                autoComplete={authMode === "login" ? "current-password" : "new-password"}
                className="bg-transparent w-full outline-none text-[#828282] placeholder-[#828282]"
                style={{ ...monoFont, fontSize: "13px" }}
              />
            </div>
            {error && (
              <p className="text-[11px] text-red-600" style={monoFont}>{error}</p>
            )}
            <button
              onClick={() => void submitAuth()}
              disabled={busy}
              className="h-[48px] bg-black rounded-[10px] flex items-center justify-center cursor-pointer hover:bg-neutral-800 transition-colors disabled:opacity-40"
            >
              <span className="text-white" style={{ ...monoFont, fontSize: "13px" }}>
                {busy ? "Please wait…" : authMode === "login" ? "Login" : "Create account"}
              </span>
            </button>
          </div>
          <p className="text-center text-[#828282]" style={{ ...monoFont, fontSize: "11px" }}>
            Forgot password? Contact admin.
          </p>
          <button
            onClick={() => setMode("landing")}
            className="text-center text-[#828282] hover:text-black transition-colors"
            style={{ ...monoFont, fontSize: "11px" }}
          >
            ← back
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white flex flex-col items-center justify-center px-6 relative">
      <AnimatePresence mode="wait">
        {splashVisible ? (
          <motion.div
            key="splash"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.6 }}
            className="absolute inset-0 flex items-center justify-center bg-white"
          >
            <img
              src={LOGO_MARK_URL}
              alt=""
              style={{ width: 120, height: 120, objectFit: "contain" }}
              draggable={false}
            />
          </motion.div>
        ) : (
          <motion.div
            key="main"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4 }}
            className="w-full max-w-[320px] flex flex-col gap-0"
          >
            {logoSection}
            {spacingControl}

            <div className="flex flex-col gap-3">
              <button
                type="button"
                disabled
                className="h-[48px] bg-white border border-black/10 rounded-[10px] shadow-[0px_0px_3px_0px_rgba(0,0,0,0.08),0px_2px_3px_0px_rgba(0,0,0,0.17)] flex items-center justify-center gap-3 opacity-40 cursor-not-allowed"
              >
                <GoogleIcon />
                <span style={{ fontFamily: "'Roboto', sans-serif", fontSize: "14px", color: "rgba(0,0,0,0.54)" }}>
                  Continue with Google
                </span>
              </button>

              <button
                type="button"
                disabled
                className="h-[48px] bg-black rounded-[10px] shadow-[0px_0px_3px_0px_rgba(0,0,0,0.08),0px_2px_3px_0px_rgba(0,0,0,0.17)] flex items-center justify-center gap-3 opacity-40 cursor-not-allowed"
              >
                <AppleIcon />
                <span className="text-white" style={{ fontFamily: "'SF Pro Display', sans-serif", fontSize: "14px" }}>
                  Continue with Apple
                </span>
              </button>

              <div className="flex items-center gap-3 my-1">
                <div className="flex-1 h-px bg-black" />
                <span className="text-black" style={{ ...condensedFont, fontSize: "14px" }}>OR</span>
                <div className="flex-1 h-px bg-black" />
              </div>

              <button
                onClick={() => { setMode("auth"); setAuthMode("login"); setError(null); }}
                className="h-[48px] bg-black rounded-[10px] flex items-center justify-center cursor-pointer hover:bg-neutral-800 transition-colors"
              >
                <span className="text-white" style={{ ...monoFont, fontSize: "13px" }}>
                  Continue with User ID
                </span>
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
