import { memo, useCallback } from "react";

interface PresetChipProps {
  name: string;
  /** In chain strip — shows X button, draggable for reorder */
  inChain?: boolean;
  /** Index in chain (for reorder drag data) */
  chainIndex?: number;
  /** Called when X is clicked in chain mode */
  onRemove?: (index: number) => void;
  /** Called when chip is clicked in palette mode */
  onClick?: (name: string) => void;
}

function PresetChipInner({ name, inChain, chainIndex, onRemove, onClick }: PresetChipProps) {
  const handleDragStart = useCallback(
    (e: React.DragEvent) => {
      if (inChain && chainIndex !== undefined) {
        e.dataTransfer.setData("chain-reorder", String(chainIndex));
      } else {
        e.dataTransfer.setData("preset-name", name);
      }
      e.dataTransfer.effectAllowed = "move";
    },
    [name, inChain, chainIndex],
  );

  return (
    <div
      draggable
      onDragStart={handleDragStart}
      onClick={() => onClick?.(name)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "3px 8px",
        fontSize: 10,
        fontFamily: "JetBrains Mono, monospace",
        color: inChain ? "#ebdbb2" : "#928374",
        background: inChain ? "#3c3836" : "none",
        border: inChain ? "1px solid #fabd2f" : "1px solid #504945",
        borderRadius: 2,
        cursor: inChain ? "grab" : "pointer",
        userSelect: "none",
      }}
    >
      {name}
      {inChain && onRemove && chainIndex !== undefined && (
        <span
          onClick={(e) => {
            e.stopPropagation();
            onRemove(chainIndex);
          }}
          style={{ color: "#665c54", cursor: "pointer", marginLeft: 2 }}
        >
          ×
        </span>
      )}
    </div>
  );
}

export const PresetChip = memo(PresetChipInner);
