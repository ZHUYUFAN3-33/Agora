// Logo assets in public/: logo.png = mark only (no text), logo-with-text.png = with wordmark
const LOGO_MARK_URL = "/logo.png";
const LOGO_FULL_URL = "/logo-with-text.png";

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
