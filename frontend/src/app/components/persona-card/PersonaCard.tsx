import { useState } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { PersonaDto } from "../../../core/types/persona";
import type { PersonaOverlayTab } from "../persona-overlay/PersonaOverlay";
import { CHAKRA_PALETTE } from "../../../core/types/chakra";
import { CroppedAvatar } from "../avatar-crop/CroppedAvatar";

interface PersonaCardProps {
  persona: PersonaDto;
  index: number;
  onContinue: (personaId: string) => void;
  onNewChat: (personaId: string) => void;
  onOpenOverlay: (personaId: string, tab: PersonaOverlayTab) => void;
  onTogglePin?: (personaId: string, pinned: boolean) => void;
}

export default function PersonaCard({
  persona,
  index,
  onContinue,
  onNewChat,
  onOpenOverlay,
  onTogglePin,
}: PersonaCardProps) {
  const [isHovered, setIsHovered] = useState(false);
  const [hoveredZone, setHoveredZone] = useState<"continue" | "new" | null>(null);

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: persona.id });

  const chakra = CHAKRA_PALETTE[persona.colour_scheme];

  const glowStrength = isHovered
    ? chakra.glow.replace("0.3", "0.55")
    : chakra.glow;

  const cardStyle: React.CSSProperties = {
    width: "clamp(160px, 42vw, 210px)",
    height: "clamp(240px, 63vw, 320px)",
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
    background: `linear-gradient(160deg, #1a1528 0%, #0f0d16 100%)`,
    border: `1px solid ${isHovered ? chakra.hex + "55" : chakra.hex + "28"}`,
    boxShadow: isHovered
      ? `0 0 24px ${glowStrength}, 0 0 8px ${glowStrength}, inset 0 1px 0 rgba(255,255,255,0.06)`
      : `0 0 12px ${glowStrength}, inset 0 1px 0 rgba(255,255,255,0.04)`,
    animation: `card-entrance 0.6s cubic-bezier(0.16, 1, 0.3, 1) ${index * 0.1}s both`,
  };

  const menuButtons: { label: string; tab: PersonaOverlayTab }[] = [
    { label: "Overview", tab: "overview" },
    { label: "Edit", tab: "edit" },
    { label: "History", tab: "history" },
  ];

  return (
    <div
      ref={setNodeRef}
      style={cardStyle}
      className="relative flex flex-col rounded-xl overflow-hidden select-none"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => {
        setIsHovered(false);
        setHoveredZone(null);
      }}
      {...attributes}
    >
      {/* Chakra gradient overlay */}
      <div
        className="absolute inset-x-0 top-0 h-1/2 pointer-events-none"
        style={{ background: chakra.gradient }}
      />

      {/* Drag handle — only this element triggers drag */}
      <div
        className="absolute top-2.5 left-2.5 z-10 flex flex-col gap-[3px] cursor-grab active:cursor-grabbing p-1"
        {...listeners}
      >
        {[0, 1, 2].map((row) => (
          <div key={row} className="flex gap-[3px]">
            <div
              className="w-[3px] h-[3px] rounded-full"
              style={{ background: "rgba(255,255,255,0.3)" }}
            />
            <div
              className="w-[3px] h-[3px] rounded-full"
              style={{ background: "rgba(255,255,255,0.3)" }}
            />
          </div>
        ))}
      </div>

      {/* Pin button + NSFW indicator */}
      <div className="absolute top-2 right-2 z-10 flex items-center gap-1.5">
        {onTogglePin && (
          <button
            className="flex h-5 w-5 items-center justify-center rounded-full transition-all duration-200"
            style={{
              color: persona.pinned ? chakra.hex : "rgba(255,255,255,0.2)",
              background: persona.pinned ? chakra.hex + "1a" : "transparent",
            }}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => onTogglePin(persona.id, !persona.pinned)}
            onMouseEnter={(e) => {
              if (!persona.pinned) e.currentTarget.style.color = chakra.hex + "80";
            }}
            onMouseLeave={(e) => {
              if (!persona.pinned) e.currentTarget.style.color = "rgba(255,255,255,0.2)";
            }}
            title={persona.pinned ? "Unpin" : "Pin"}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 17v5" />
              <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z" />
            </svg>
          </button>
        )}
        {persona.nsfw && (
          <span className="text-xs leading-none">💋</span>
        )}
      </div>

      {/* Card content — CSS Grid: name / avatar / tagline */}
      <div
        className="flex-1 grid items-center justify-items-center px-3"
        style={{
          gridTemplateRows: "auto 1fr auto",
          paddingBottom: "28px",
        }}
      >
        {/* Name */}
        <p
          className="font-serif text-[15px] font-semibold leading-tight pt-4 self-start"
          style={{ color: "#e8e0d4" }}
        >
          {persona.name}
        </p>

        {/* Avatar / Monogram */}
        <div
          className="w-[90px] h-[90px] rounded-full flex items-center justify-center self-center overflow-hidden"
          style={{
            background: `radial-gradient(circle at center, ${chakra.hex}33 0%, ${chakra.hex}11 50%, transparent 70%)`,
            boxShadow: `0 0 20px ${glowStrength}, 0 0 40px ${chakra.hex}22`,
            border: `2px solid ${chakra.hex}4d`,
          }}
        >
          {persona.profile_image ? (
            <CroppedAvatar
              personaId={persona.id}
              updatedAt={persona.updated_at}
              crop={persona.profile_crop}
              size={86}
              alt={persona.name}
            />
          ) : (
            <span
              className="font-serif text-3xl font-semibold"
              style={{ color: chakra.hex }}
            >
              {persona.monogram}
            </span>
          )}
        </div>

        {/* Tagline — anchored at bottom, max 2 lines with ellipsis */}
        <p
          className="font-mono text-[11px] italic leading-snug text-center self-end w-full"
          style={{
            color: "rgba(255,255,255,0.4)",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {persona.tagline}
        </p>
      </div>

      {/* Chat zones — absolute overlay above menu bar */}
      <div className="absolute top-0 left-0 right-0 bottom-[48px] flex">
        {/* Continue zone — left 2/3 */}
        <button
          className="flex-[2] flex items-end justify-center pb-2 bg-transparent border-none cursor-pointer"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => onContinue(persona.id)}
          onMouseEnter={() => setHoveredZone("continue")}
          onMouseLeave={() => setHoveredZone(null)}
        >
          <span
            className="text-[10px] font-semibold uppercase tracking-[1.5px] transition-all duration-250"
            style={{
              color: hoveredZone === "continue"
                ? chakra.hex + "b3"
                : chakra.hex + "26",
              textShadow: hoveredZone === "continue"
                ? `0 0 12px ${chakra.glow}`
                : "none",
            }}
          >
            Continue
          </span>
        </button>

        {/* Divider line */}
        <div
          className="w-px transition-colors duration-300 self-stretch my-[15%]"
          style={{
            background: isHovered ? chakra.hex + "26" : "transparent",
          }}
        />

        {/* New zone — right 1/3 */}
        <button
          className="flex-[1] flex items-end justify-center pb-2 bg-transparent border-none cursor-pointer"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => onNewChat(persona.id)}
          onMouseEnter={() => setHoveredZone("new")}
          onMouseLeave={() => setHoveredZone(null)}
        >
          <span
            className="text-[10px] font-semibold uppercase tracking-[1.5px] transition-all duration-250"
            style={{
              color: hoveredZone === "new"
                ? chakra.hex + "b3"
                : chakra.hex + "26",
              textShadow: hoveredZone === "new"
                ? `0 0 12px ${chakra.glow}`
                : "none",
            }}
          >
            New
          </span>
        </button>
      </div>

      {/* Menu bar — bottom */}
      <div
        className="flex h-12 relative z-[3]"
        style={{ borderTop: `1px solid rgba(255,255,255,0.06)` }}
      >
        {menuButtons.map((btn, i) => (
          <button
            key={btn.tab}
            className="flex-1 flex items-center justify-center text-[10px] font-medium uppercase tracking-[1px] transition-colors duration-200 bg-transparent border-none cursor-pointer"
            style={{
              color: "rgba(255,255,255,0.35)",
              borderRight: i < menuButtons.length - 1
                ? "1px solid rgba(255,255,255,0.04)"
                : "none",
            }}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => onOpenOverlay(persona.id, btn.tab)}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = chakra.hex;
              e.currentTarget.style.background = chakra.hex + "0f";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = "rgba(255,255,255,0.35)";
              e.currentTarget.style.background = "transparent";
            }}
          >
            {btn.label}
          </button>
        ))}
      </div>
    </div>
  );
}
