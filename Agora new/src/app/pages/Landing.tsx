import React, { useState } from "react";
import { useNavigate } from "react-router";
import { AgoraLogo } from "../components/AgoraLogo";
import svgPaths from "../../imports/svg-czrgecjots";

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
  const [email, setEmail] = useState("");
  const [mode, setMode] = useState<"landing" | "signin" | "signup">("landing");

  const monoFont = { fontFamily: "'Share Tech Mono', monospace" };
  const condensedFont = { fontFamily: "'Barlow Condensed', sans-serif" };

  const handleContinueWithEmail = () => {
    if (email.trim()) {
      setMode("signin");
    }
  };

  const handleAuth = () => {
    localStorage.setItem("agora_auth", JSON.stringify({ email: email || "user@agora.app", nickname: "" }));
    navigate("/onboarding");
  };

  if (mode === "signin") {
    return (
      <div className="min-h-screen bg-white flex flex-col items-center justify-center px-6">
        <div className="w-full max-w-[320px] flex flex-col gap-6">
          {/* Logo centered big */}
          <div className="flex justify-center mb-8">
            <AgoraLogo size={180} />
          </div>

          {/* Sign in fields */}
          <div className="flex flex-col gap-3">
            <div className="h-[48px] bg-black rounded-[10px] flex items-center px-4">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter your email..."
                className="bg-transparent w-full outline-none text-[#828282] placeholder-[#828282]"
                style={{ ...monoFont, fontSize: "13px" }}
              />
            </div>
            <div className="h-[48px] bg-black rounded-[10px] flex items-center px-4">
              <input
                type="password"
                placeholder="Enter your password..."
                className="bg-transparent w-full outline-none text-[#828282] placeholder-[#828282]"
                style={{ ...monoFont, fontSize: "13px" }}
              />
            </div>
            <button
              onClick={handleAuth}
              className="h-[48px] bg-black rounded-[10px] flex items-center justify-center cursor-pointer hover:bg-neutral-800 transition-colors"
            >
              <span className="text-white" style={{ ...monoFont, fontSize: "13px" }}>
                Continue
              </span>
            </button>
          </div>

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
    <div className="min-h-screen bg-white flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-[320px] flex flex-col gap-0">
        {/* Logo + wordmark */}
        <div className="mb-10">
          <AgoraLogo size={42} />
        </div>

        {/* Tagline */}
        <p
          className="mb-16 text-black"
          style={{
            ...monoFont,
            fontSize: "28px",
            lineHeight: "1.7",
            letterSpacing: "0.07em",
            whiteSpace: "pre-wrap",
          }}
        >
          {"Refine your\njudgment\nthrough\ncontrolled\ndivergence_"}
        </p>

        {/* Auth buttons */}
        <div className="flex flex-col gap-3">
          {/* Google */}
          <button
            onClick={handleAuth}
            className="h-[48px] bg-white border border-black/10 rounded-[10px] shadow-[0px_0px_3px_0px_rgba(0,0,0,0.08),0px_2px_3px_0px_rgba(0,0,0,0.17)] flex items-center justify-center gap-3 cursor-pointer hover:bg-gray-50 transition-colors"
          >
            <GoogleIcon />
            <span className="text-black/54" style={{ fontFamily: "'Roboto', sans-serif", fontSize: "14px" }}>
              Continue with Google
            </span>
          </button>

          {/* Apple */}
          <button
            onClick={handleAuth}
            className="h-[48px] bg-black rounded-[10px] shadow-[0px_0px_3px_0px_rgba(0,0,0,0.08),0px_2px_3px_0px_rgba(0,0,0,0.17)] flex items-center justify-center gap-3 cursor-pointer hover:bg-neutral-800 transition-colors"
          >
            <AppleIcon />
            <span className="text-white" style={{ fontFamily: "'SF Pro Display', sans-serif", fontSize: "14px" }}>
              Continue with Apple
            </span>
          </button>

          {/* OR divider */}
          <div className="flex items-center gap-3 my-1">
            <div className="flex-1 h-px bg-black" />
            <span className="text-black" style={{ ...condensedFont, fontSize: "14px" }}>OR</span>
            <div className="flex-1 h-px bg-black" />
          </div>

          {/* Email */}
          <div className="h-[48px] bg-black rounded-[10px] flex items-center px-4">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleContinueWithEmail()}
              placeholder="Enter your email..."
              className="bg-transparent w-full outline-none text-[#828282] placeholder-[#828282]"
              style={{ ...monoFont, fontSize: "13px" }}
            />
          </div>

          {/* Continue */}
          <button
            onClick={handleContinueWithEmail}
            className="h-[48px] bg-black rounded-[10px] flex items-center justify-center cursor-pointer hover:bg-neutral-800 transition-colors"
          >
            <span className="text-white" style={{ ...monoFont, fontSize: "13px" }}>
              Continue
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}