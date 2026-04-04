interface AddPersonaCardProps {
  onClick: () => void;
  index: number;
}

export default function AddPersonaCard({ onClick, index }: AddPersonaCardProps) {
  const cardStyle: React.CSSProperties = {
    width: "clamp(160px, 42vw, 210px)",
    height: "clamp(240px, 63vw, 320px)",
    border: "1px dashed rgba(201,168,76,0.15)",
    animation: `card-entrance 0.6s cubic-bezier(0.16, 1, 0.3, 1) ${index * 0.1}s both`,
  };

  return (
    <button
      style={cardStyle}
      className="relative flex flex-col items-center justify-center gap-3 rounded-xl bg-transparent cursor-pointer transition-all duration-200 hover:border-[rgba(201,168,76,0.35)] hover:bg-[rgba(201,168,76,0.04)] group"
      onClick={onClick}
    >
      {/* Plus icon */}
      <div
        className="w-10 h-10 rounded-full flex items-center justify-center transition-colors duration-200"
        style={{
          border: "1px dashed rgba(201,168,76,0.3)",
          color: "rgba(201,168,76,0.5)",
        }}
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 18 18"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        >
          <line x1="9" y1="3" x2="9" y2="15" />
          <line x1="3" y1="9" x2="15" y2="9" />
        </svg>
      </div>

      <span
        className="font-mono text-[10px] uppercase tracking-widest transition-colors duration-200"
        style={{ color: "rgba(201,168,76,0.45)" }}
      >
        add persona
      </span>
    </button>
  );
}
