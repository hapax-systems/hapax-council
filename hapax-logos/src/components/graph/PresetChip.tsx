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
  /** When true, grey out chip and block drag/click */
  disabled?: boolean;
  /** Slot count to show next to name in palette mode */
  slotCount?: number;
}

function PresetChipInner({
  name,
  inChain,
  chainIndex,
  onRemove,
  onClick,
  disabled,
  slotCount,
}: PresetChipProps) {
  const handleDragStart = useCallback(
    (e: React.DragEvent) => {
      if (disabled) {
        e.preventDefault();
        return;
      }
      if (inChain && chainIndex !== undefined) {
        e.dataTransfer.setData("chain-reorder", String(chainIndex));
      } else {
        e.dataTransfer.setData("preset-name", name);
      }
      e.dataTransfer.effectAllowed = "move";
    },
    [name, inChain, chainIndex, disabled],
  );

  const handleClick = useCallback(() => {
    if (disabled) return;
    onClick?.(name);
  }, [disabled, onClick, name]);

  const chipColor = disabled ? "#504945" : inChain ? "#ebdbb2" : "#928374";
  const chipBorder = disabled ? "#3c3836" : inChain ? "#fabd2f" : "#504945";
  const chipBg = inChain ? "#3c3836" : "none";
  const chipCursor = disabled ? "not-allowed" : inChain ? "grab" : "pointer";

  return (
    <div
      draggable={!disabled}
      onDragStart={handleDragStart}
      onClick={handleClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "3px 8px",
        fontSize: 10,
        fontFamily: "JetBrains Mono, monospace",
        color: chipColor,
        background: chipBg,
        border: `1px solid ${chipBorder}`,
        borderRadius: 2,
        cursor: chipCursor,
        userSelect: "none",
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {name}
      {!inChain && slotCount !== undefined && (
        <span style={{ color: disabled ? "#504945" : "#665c54", fontSize: 9 }}>
          ({slotCount})
        </span>
      )}
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
