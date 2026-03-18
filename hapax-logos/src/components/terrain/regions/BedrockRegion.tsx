import { Region } from "../Region";

export function BedrockRegion() {
  return (
    <Region name="bedrock" className="col-span-3">
      {(depth) => (
        <div className="h-full flex items-center px-6">
          <div className="flex-1">
            <div className="text-[10px] uppercase tracking-[0.4em] text-zinc-600">bedrock</div>
            {depth !== "surface" && (
              <div className="text-xs text-zinc-500 mt-1">
                Governance, health, consent, cost
              </div>
            )}
          </div>
        </div>
      )}
    </Region>
  );
}
