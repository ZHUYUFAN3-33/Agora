// Logo assets in public/Assets/
const LOGO_MARK_URL = "/Assets/logo.png";
const LOGO_FULL_URL = "/Assets/logo%20with%20text%20.png";
const TEXT_LOGO_URL = "/Assets/Text%20logo.png";

interface AgoraLogoProps {
  size?: number;
  showWordmark?: boolean;
}

// Full logo with wordmark — 聊天界面 sidebar 左上角用
export function AgoraLogoFull({ height = 40 }: { height?: number }) {
  return (
    <img
      src={LOGO_FULL_URL}
      alt="agora"
      style={{ height, width: "auto", display: "block", objectFit: "contain" }}
      draggable={false}
    />
  );
}

// Just the dot-circle mark (no text) — 登入界面、聊天界面中间用
export function AgoraLogo({ size = 64 }: { size?: number }) {
  return (
    <img
      src={LOGO_MARK_URL}
      alt="agora logo"
      style={{ width: size, height: size, display: "block", objectFit: "contain" }}
      draggable={false}
    />
  );
}

// Small inline logo
export function AgoraLogoSmall({ size = 32 }: { size?: number }) {
  return <AgoraLogo size={size} />;
}

// Landing/Onboarding: logo + Text logo (same width) + tagline
const TAGLINE = "Refine your judgment through controlled divergence_";
const DEFAULT_LOGO_GAP = 24;
const DEFAULT_TEXT_LOGO_OFFSET_X = 0;

export function LandingLogoSection({ width = 200, logoToTextGap = DEFAULT_LOGO_GAP, textLogoOffsetX = DEFAULT_TEXT_LOGO_OFFSET_X }: { width?: number; logoToTextGap?: number; textLogoOffsetX?: number }) {
  return (
    <div className="flex flex-col items-center" style={{ width }}>
      <img
        src={LOGO_MARK_URL}
        alt=""
        style={{ width, height: width, objectFit: "contain", display: "block" }}
        draggable={false}
      />
      <div style={{ height: logoToTextGap }} />
      <img
        src={TEXT_LOGO_URL}
        alt="AGORA"
        style={{ width, height: "auto", objectFit: "contain", display: "block", marginLeft: textLogoOffsetX }}
        draggable={false}
      />
      <div style={{ height: 12 }} />
      <p
        className="text-black text-center w-full"
        style={{ fontFamily: "'Share Tech Mono', monospace", fontSize: "12px", lineHeight: 1.5, letterSpacing: "0.04em" }}
      >
        {TAGLINE}
      </p>
    </div>
  );
}

export { DEFAULT_LOGO_GAP, DEFAULT_TEXT_LOGO_OFFSET_X };

// Agent dot indicator (small square)
export function AgentDot({ color = "black", size = 8 }: { color?: string; size?: number }) {
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: 2,
        backgroundColor: color,
        flexShrink: 0,
      }}
    />
  );
}
