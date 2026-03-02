import React, { useState } from "react";
import { useNavigate } from "react-router";
import { LandingLogoSection, DEFAULT_LOGO_GAP, DEFAULT_TEXT_LOGO_OFFSET_X } from "../components/AgoraLogo";

const LOGO_GAP_KEY = "agora_logo_gap";
const TEXT_LOGO_OFFSET_KEY = "agora_text_logo_offset_x";

export default function Onboarding() {
  const navigate = useNavigate();
  const [nickname, setNickname] = useState("");
  const logoGap = (() => {
    const v = localStorage.getItem(LOGO_GAP_KEY);
    return v ? Math.min(48, Math.max(0, parseInt(v, 10))) : DEFAULT_LOGO_GAP;
  })();
  const textLogoOffsetX = (() => {
    const v = localStorage.getItem(TEXT_LOGO_OFFSET_KEY);
    return v ? Math.min(40, Math.max(-40, parseInt(v, 10))) : DEFAULT_TEXT_LOGO_OFFSET_X;
  })();

  const monoFont = { fontFamily: "'Share Tech Mono', monospace" };

  const handleContinue = () => {
    if (!nickname.trim()) return;
    const existing = JSON.parse(localStorage.getItem("agora_auth") || "{}");
    localStorage.setItem("agora_auth", JSON.stringify({ ...existing, nickname: nickname.trim() }));
    navigate("/chat");
  };

  return (
    <div className="min-h-screen bg-white flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-[320px] flex flex-col gap-6">
        <div className="flex justify-center mb-4">
          <LandingLogoSection width={200} logoToTextGap={logoGap} textLogoOffsetX={textLogoOffsetX} />
        </div>

        <div className="flex flex-col gap-3">
          <div className="h-[48px] bg-black rounded-[10px] flex items-center px-4">
            <input
              type="text"
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleContinue()}
              placeholder="Enter your nickname..."
              maxLength={24}
              className="bg-transparent w-full outline-none text-[#828282] placeholder-[#828282]"
              style={{ ...monoFont, fontSize: "13px" }}
              autoFocus
            />
          </div>

          <button
            onClick={handleContinue}
            disabled={!nickname.trim()}
            className="h-[48px] bg-black rounded-[10px] flex items-center justify-center cursor-pointer hover:bg-neutral-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
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
