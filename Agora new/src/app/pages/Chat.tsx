import React, { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router";
import { motion, AnimatePresence } from "motion/react";
import { AgoraLogo, AgoraLogoFull } from "../components/AgoraLogo";
import {
  AGENTS,
  SAMPLE_CONVERSATIONS,
  SUGGESTED_PROMPTS,
  getAgentResponse,
} from "../data/agents";

const monoFont = { fontFamily: "'Share Tech Mono', monospace" };
const condensedFont = { fontFamily: "'Barlow Condensed', sans-serif" };

interface Message {
  id: string;
  role: "user" | "agent";
  agentId?: string;
  content: string;
  timestamp: number;
}

interface Conversation {
  id: string;
  title: string;
  preview: string;
  timestamp: string;
  messages: Message[];
}

function formatTime(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

// Typing indicator
function TypingDots({ agentId }: { agentId: string }) {
  const agent = AGENTS.find((a) => a.id === agentId);
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
      className="flex flex-col gap-1 mb-2"
    >
      <div className="flex items-center gap-2 mb-1">
        <div
          className="w-[7px] h-[7px] rounded-[1.5px] flex-shrink-0"
          style={{ backgroundColor: agent?.dotColor || "#000" }}
        />
        <span
          className="text-[11px] tracking-widest"
          style={{ ...monoFont, color: agent?.color || "#000" }}
        >
          {agent?.name}
        </span>
      </div>
      <div className="ml-4 flex items-center gap-1 h-8 px-4 bg-transparent border border-black/10 rounded-[10px] w-fit">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="w-[5px] h-[5px] bg-black rounded-full"
            animate={{ opacity: [0.3, 1, 0.3] }}
            transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.25 }}
          />
        ))}
      </div>
    </motion.div>
  );
}

// Single agent message bubble
function AgentMessage({ message }: { message: Message }) {
  const agent = AGENTS.find((a) => a.id === message.agentId);
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="flex flex-col gap-1 mb-4"
    >
      <div className="flex items-center gap-2 mb-1">
        <div
          className="w-[7px] h-[7px] rounded-[1.5px] flex-shrink-0"
          style={{ backgroundColor: agent?.dotColor || "#000" }}
        />
        <span
          className="text-[11px] tracking-widest"
          style={{ ...monoFont, color: agent?.color || "#000" }}
        >
          {agent?.name}
        </span>
        <span className="text-[10px] text-black/30 ml-1" style={monoFont}>
          · {agent?.role}
        </span>
      </div>
      <div className="ml-4 px-4 py-3 border border-black/10 rounded-[10px] rounded-tl-[2px] max-w-[90%]">
        <p className="text-[13px] text-black/80 leading-relaxed" style={monoFont}>
          {message.content}
        </p>
      </div>
    </motion.div>
  );
}

// User message bubble
function UserMessage({ message, nickname }: { message: Message; nickname: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="flex flex-col items-end gap-1 mb-6"
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[11px] text-black/40 tracking-wider" style={monoFont}>
          {formatTime(message.timestamp)}
        </span>
        <span className="text-[11px] tracking-widest" style={monoFont}>
          {nickname.toUpperCase() || "YOU"}
        </span>
      </div>
      <div className="px-4 py-3 bg-black rounded-[10px] rounded-tr-[2px] max-w-[85%]">
        <p className="text-[13px] text-white leading-relaxed" style={monoFont}>
          {message.content}
        </p>
      </div>
    </motion.div>
  );
}

// Sidebar conversation item
function ConvItem({
  conv,
  isActive,
  onClick,
}: {
  conv: Conversation;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-3 rounded-[8px] transition-colors flex flex-col gap-1 ${
        isActive ? "bg-black text-white" : "hover:bg-black/5"
      }`}
    >
      <span
        className="text-[12px] truncate"
        style={{ ...monoFont, color: isActive ? "#fff" : "#000" }}
      >
        {conv.title}
      </span>
      <span
        className="text-[10px] truncate"
        style={{ ...monoFont, color: isActive ? "rgba(255,255,255,0.5)" : "rgba(0,0,0,0.4)" }}
      >
        {conv.timestamp}
      </span>
    </button>
  );
}

export default function Chat() {
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<Conversation[]>(SAMPLE_CONVERSATIONS as Conversation[]);
  const [currentConvId, setCurrentConvId] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [typingAgents, setTypingAgents] = useState<string[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [messageCount, setMessageCount] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const authData = JSON.parse(localStorage.getItem("agora_auth") || "{}");
  const nickname: string = authData.nickname || "You";

  useEffect(() => {
    const auth = localStorage.getItem("agora_auth");
    if (!auth) navigate("/");
  }, [navigate]);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [conversations, typingAgents, scrollToBottom]);

  const currentConv = conversations.find((c) => c.id === currentConvId) || null;

  const handleNewChat = () => {
    setCurrentConvId(null);
    setTypingAgents([]);
    setSidebarOpen(false);
    inputRef.current?.focus();
  };

  const handleSelectConv = (id: string) => {
    setCurrentConvId(id);
    setTypingAgents([]);
    setSidebarOpen(false);
  };

  const handleSend = () => {
    const text = inputValue.trim();
    if (!text || typingAgents.length > 0) return;
    setInputValue("");

    const userMsg: Message = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: text,
      timestamp: Date.now(),
    };

    let convId = currentConvId;
    let updatedConvs = [...conversations];

    if (!convId) {
      // Create new conversation
      const newConv: Conversation = {
        id: `conv-${Date.now()}`,
        title: text.length > 48 ? text.slice(0, 48) + "…" : text,
        preview: text,
        timestamp: "just now",
        messages: [userMsg],
      };
      updatedConvs = [newConv, ...updatedConvs];
      convId = newConv.id;
      setCurrentConvId(convId);
      setConversations(updatedConvs);
    } else {
      updatedConvs = updatedConvs.map((c) =>
        c.id === convId ? { ...c, messages: [...c.messages, userMsg] } : c
      );
      setConversations(updatedConvs);
    }

    // Simulate agents responding one by one
    const currentMsgIndex = messageCount;
    setMessageCount((prev) => prev + 1);

    AGENTS.forEach((agent, idx) => {
      const startDelay = idx * 1800 + 600;
      const endDelay = startDelay + 1200;

      setTimeout(() => {
        setTypingAgents((prev) => [...prev, agent.id]);
      }, startDelay);

      setTimeout(() => {
        const responseContent = getAgentResponse(agent.id, currentMsgIndex);
        const agentMsg: Message = {
          id: `msg-${Date.now()}-${agent.id}`,
          role: "agent",
          agentId: agent.id,
          content: responseContent,
          timestamp: Date.now(),
        };

        setTypingAgents((prev) => prev.filter((id) => id !== agent.id));
        setConversations((prev) =>
          prev.map((c) =>
            c.id === convId
              ? {
                  ...c,
                  messages: [...c.messages, agentMsg],
                  preview: `${agent.name}: ${responseContent.slice(0, 60)}...`,
                  timestamp: "just now",
                }
              : c
          )
        );
      }, endDelay);
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("agora_auth");
    navigate("/");
  };

  return (
    <div className="h-screen bg-white flex overflow-hidden">
      {/* Sidebar overlay on mobile */}
      <AnimatePresence>
        {sidebarOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/20 z-20 lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <motion.aside
        className={`
          fixed lg:relative z-30 lg:z-auto h-full bg-white border-r border-black/8 flex flex-col
          w-[260px] lg:w-[240px] xl:w-[260px]
          transition-transform duration-300 lg:transition-none lg:translate-x-0
          ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}
        `}
      >
        {/* Sidebar header */}
        <div className="px-4 pt-6 pb-4 flex items-center justify-between border-b border-black/8">
          <AgoraLogoFull height={28} />
          <button
            className="lg:hidden p-1 hover:bg-black/5 rounded"
            onClick={() => setSidebarOpen(false)}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M3 3L13 13M3 13L13 3" stroke="black" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* New chat button */}
        <div className="px-3 pt-4 pb-2">
          <button
            onClick={handleNewChat}
            className="w-full h-[40px] border border-black/20 rounded-[8px] flex items-center justify-center gap-2 hover:bg-black hover:text-white hover:border-black transition-all duration-200 group"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path
                d="M6 1V11M1 6H11"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
            <span className="text-[12px]" style={monoFont}>
              new chat
            </span>
          </button>
        </div>

        {/* Conversations */}
        <div className="flex-1 overflow-y-auto px-2 py-2">
          {conversations.length === 0 ? (
            <p className="text-center text-black/30 text-[11px] mt-8" style={monoFont}>
              no conversations yet
            </p>
          ) : (
            <div className="flex flex-col gap-1">
              {conversations.map((conv) => (
                <ConvItem
                  key={conv.id}
                  conv={conv}
                  isActive={conv.id === currentConvId}
                  onClick={() => handleSelectConv(conv.id)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Sidebar footer */}
        <div className="px-3 py-4 border-t border-black/8 flex items-center justify-between">
          <span className="text-[11px] text-black/50" style={monoFont}>
            {nickname.toUpperCase()}
          </span>
          <button
            onClick={handleLogout}
            className="text-[10px] text-black/30 hover:text-black transition-colors"
            style={monoFont}
          >
            sign out
          </button>
        </div>
      </motion.aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="h-[56px] border-b border-black/8 flex items-center px-4 gap-4 flex-shrink-0">
          {/* Hamburger */}
          <button
            className="lg:hidden p-1.5 hover:bg-black/5 rounded-md transition-colors"
            onClick={() => setSidebarOpen(true)}
          >
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
              <path d="M2 4.5H16M2 9H16M2 13.5H16" stroke="black" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>

          {/* Title */}
          <div className="flex-1 flex items-center">
            {currentConv ? (
              <span className="text-[13px] text-black/70 truncate" style={monoFont}>
                {currentConv.title}
              </span>
            ) : (
              <span className="text-[13px] text-black/30" style={monoFont}>
                new conversation_
              </span>
            )}
          </div>

          {/* Agent indicators */}
          <div className="flex items-center gap-2">
            {AGENTS.map((agent) => (
              <div key={agent.id} className="flex items-center gap-1.5" title={`${agent.name} · ${agent.role}`}>
                <div
                  className="w-[7px] h-[7px] rounded-[1.5px]"
                  style={{ backgroundColor: agent.dotColor }}
                />
                <span
                  className="hidden sm:block text-[10px] tracking-widest"
                  style={{ ...monoFont, color: agent.color }}
                >
                  {agent.name}
                </span>
              </div>
            ))}
          </div>
        </header>

        {/* Messages area */}
        <div className="flex-1 overflow-y-auto px-4 sm:px-8 py-6">
          {!currentConv ? (
            /* Welcome / empty state */
            <div className="max-w-[560px] mx-auto flex flex-col items-center justify-center min-h-[60vh] gap-8">
              <div className="flex flex-col items-center gap-4">
                <AgoraLogo size={64} />
                <p
                  className="text-center text-[22px] text-black"
                  style={{ ...condensedFont, fontWeight: 500, letterSpacing: "0.12em" }}
                >
                  agora
                </p>
                <p
                  className="text-center text-[13px] text-black/40 max-w-[300px] leading-relaxed"
                  style={monoFont}
                >
                  four agents. one question. controlled divergence.
                </p>
              </div>

              {/* Agent descriptions */}
              <div className="grid grid-cols-2 gap-3 w-full max-w-[400px]">
                {AGENTS.map((agent) => (
                  <div
                    key={agent.id}
                    className="border border-black/8 rounded-[10px] px-4 py-3"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <div
                        className="w-[6px] h-[6px] rounded-[1.2px]"
                        style={{ backgroundColor: agent.dotColor }}
                      />
                      <span
                        className="text-[11px] tracking-widest"
                        style={{ ...monoFont, color: agent.color }}
                      >
                        {agent.name}
                      </span>
                    </div>
                    <p className="text-[10px] text-black/40" style={monoFont}>
                      {agent.role}
                    </p>
                  </div>
                ))}
              </div>

              {/* Suggested prompts */}
              <div className="w-full max-w-[480px]">
                <p className="text-[10px] text-black/30 mb-3 text-center tracking-widest" style={monoFont}>
                  SUGGESTED PROMPTS
                </p>
                <div className="flex flex-col gap-2">
                  {SUGGESTED_PROMPTS.map((prompt, i) => (
                    <button
                      key={i}
                      onClick={() => {
                        setInputValue(prompt);
                        inputRef.current?.focus();
                      }}
                      className="text-left px-4 py-3 border border-black/8 rounded-[10px] hover:bg-black hover:text-white hover:border-black transition-all duration-200 group"
                    >
                      <span
                        className="text-[12px] text-black/60 group-hover:text-white transition-colors"
                        style={monoFont}
                      >
                        {prompt}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            /* Messages */
            <div className="max-w-[680px] mx-auto">
              {currentConv.messages.map((msg) =>
                msg.role === "user" ? (
                  <UserMessage key={msg.id} message={msg} nickname={nickname} />
                ) : (
                  <AgentMessage key={msg.id} message={msg} />
                )
              )}

              {/* Typing indicators */}
              <AnimatePresence>
                {typingAgents.map((agentId) => (
                  <TypingDots key={agentId} agentId={agentId} />
                ))}
              </AnimatePresence>

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input area */}
        <div className="flex-shrink-0 border-t border-black/8 px-4 sm:px-8 py-4">
          <div className="max-w-[680px] mx-auto">
            <div className="flex gap-3 items-end">
              <div className="flex-1 bg-black rounded-[12px] flex items-end px-4 py-3 gap-2">
                <textarea
                  ref={inputRef}
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Enter a question or topic to explore..."
                  rows={1}
                  disabled={typingAgents.length > 0}
                  className="flex-1 bg-transparent resize-none outline-none text-white placeholder-[#828282] leading-relaxed disabled:opacity-50"
                  style={{ ...monoFont, fontSize: "13px", maxHeight: "120px" }}
                  onInput={(e) => {
                    const el = e.currentTarget;
                    el.style.height = "auto";
                    el.style.height = `${el.scrollHeight}px`;
                  }}
                />
              </div>

              <button
                onClick={handleSend}
                disabled={!inputValue.trim() || typingAgents.length > 0}
                className="h-[48px] w-[48px] bg-black rounded-[12px] flex items-center justify-center flex-shrink-0 hover:bg-neutral-800 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path
                    d="M8 13V3M3 8L8 3L13 8"
                    stroke="white"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>

            <p className="text-center text-[10px] text-black/20 mt-2" style={monoFont}>
              shift+enter for new line · enter to send
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}