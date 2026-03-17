import { invoke } from "@tauri-apps/api/core";

const LAYERS = [
  { id: "gradient", label: "L0 Gradient", color: "bg-indigo-500" },
  { id: "reaction_diff", label: "L1 Reaction-Diffusion", color: "bg-purple-500" },
  { id: "voronoi", label: "L2 Voronoi", color: "bg-cyan-500" },
  { id: "wave", label: "L3 Wave", color: "bg-emerald-500" },
  { id: "physarum", label: "L4 Physarum", color: "bg-amber-500" },
  { id: "feedback", label: "L5 Feedback", color: "bg-rose-500" },
];

interface LayerControlsProps {
  opacities: Record<string, number>;
  onUpdate: () => void;
}

export function LayerControls({ opacities, onUpdate }: LayerControlsProps) {
  const handleChange = async (layer: string, value: number) => {
    try {
      await invoke("set_visual_layer_param", { layer, opacity: value });
      onUpdate();
    } catch {
      // Visual surface may not be running
    }
  };

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
        Layer Opacities
      </h3>
      {LAYERS.map((layer) => {
        const value = opacities[layer.id] ?? 1.0;
        return (
          <div key={layer.id} className="flex items-center gap-3">
            <div className={`h-2 w-2 rounded-full ${layer.color}`} />
            <span className="w-40 text-xs text-zinc-300">{layer.label}</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={value}
              onChange={(e) => handleChange(layer.id, parseFloat(e.target.value))}
              className="flex-1 accent-zinc-400"
            />
            <span className="w-10 text-right text-xs text-zinc-500">
              {(value * 100).toFixed(0)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}
