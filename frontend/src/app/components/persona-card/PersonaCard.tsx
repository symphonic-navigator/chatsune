import { useState } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { PersonaDto } from "../../../core/types/persona";
import { CHAKRA_PALETTE } from "../../../core/types/chakra";

interface PersonaCardProps {
  persona: PersonaDto;
  index: number;
  onContinue: (personaId: string) => void;
  onNewChat: (personaId: string) => void;
  onOpenOverlay: (personaId: string) => void;
}

export default function PersonaCard({
  persona,
  index,
  onContinue,
  onNewChat,
  onOpenOverlay,
}: PersonaCardProps) {
  const [isHovered, setIsHovered] = useState(false);

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

  const avatarGlowStyle: React.CSSProperties = {
    background: `radial-gradient(circle at center, ${chakra.hex}33 0%, ${chakra.hex}11 50%, transparent 70%)`,
    boxShadow: `0 0 20px ${glowStrength}, 0 0 40px ${chakra.hex}22`,
  };

  const monogramBadgeStyle: React.CSSProperties = {
    background: `${chakra.hex}22`,
    border: `1px solid ${chakra.hex}44`,
    color: chakra.hex,
  };

  return (
    <div
      ref={setNodeRef}
      style={cardStyle}
      className="relative flex flex-col items-center rounded-xl overflow-hidden cursor-grab active:cursor-grabbing select-none"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      {...attributes}
      {...listeners}
    >
      {/* NSFW indicator */}
      {persona.nsfw && (
        <div className="absolute top-2 left-2 z-10 text-xs leading-none">
          💋
        </div>
      )}

      {/* Monogram badge */}
      <div
        className="absolute top-2 right-2 z-10 w-6 h-6 rounded-full flex items-center justify-center text-xs font-serif font-semibold"
        style={monogramBadgeStyle}
      >
        {persona.monogram}
      </div>

      {/* Chakra gradient overlay at top */}
      <div
        className="absolute inset-x-0 top-0 h-1/2 pointer-events-none"
        style={{ background: chakra.gradient }}
      />

      {/* Avatar area */}
      <div className="flex-1 flex items-center justify-center pt-8">
        <div
          className="w-[100px] h-[100px] rounded-full flex items-center justify-center overflow-hidden"
          style={avatarGlowStyle}
        >
          {persona.profile_image ? (
            <img
              src={persona.profile_image}
              alt={persona.name}
              className="w-full h-full object-cover rounded-full"
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
      </div>

      {/* Name and tagline */}
      <div className="px-3 pb-2 text-center">
        <p
          className="font-serif text-sm font-semibold leading-tight mb-0.5"
          style={{ color: "#e8e0d4" }}
        >
          {persona.name}
        </p>
        <p
          className="font-mono text-[9px] uppercase tracking-widest leading-tight"
          style={{ color: chakra.hex + "cc" }}
        >
          {persona.tagline}
        </p>
      </div>

      {/* Overlay trigger button */}
      <button
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-8 h-8 rounded-full flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity duration-200 z-20"
        style={{
          background: "rgba(10,8,16,0.7)",
          border: `1px solid ${chakra.hex}55`,
          color: chakra.hex,
        }}
        onPointerDown={(e) => e.stopPropagation()}
        onClick={() => onOpenOverlay(persona.id)}
        aria-label="Open persona overlay"
      >
        <span className="text-base leading-none">⟡</span>
      </button>

      {/* Action zones */}
      <div className="absolute bottom-0 inset-x-0 flex h-10">
        {/* Continue — left 2/3 */}
        <button
          className="flex-[2] flex items-center justify-center text-[10px] font-mono uppercase tracking-wider transition-colors duration-150"
          style={{
            background: isHovered ? `${chakra.hex}18` : "transparent",
            borderTop: `1px solid ${chakra.hex}22`,
            borderRight: `1px solid ${chakra.hex}22`,
            color: "#e8e0d4aa",
          }}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => onContinue(persona.id)}
        >
          continue
        </button>

        {/* New chat — right 1/3 */}
        <button
          className="flex-[1] flex items-center justify-center text-[10px] font-mono uppercase tracking-wider transition-colors duration-150"
          style={{
            background: isHovered ? `${chakra.hex}28` : "transparent",
            borderTop: `1px solid ${chakra.hex}22`,
            color: chakra.hex + "bb",
          }}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => onNewChat(persona.id)}
        >
          new
        </button>
      </div>
    </div>
  );
}
