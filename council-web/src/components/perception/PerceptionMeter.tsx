import { Activity, Eye, Hand, Scan, Smile, User } from "lucide-react";
import type { PerceptionState } from "../../api/types";

/** Color-coded classification badge */
function Tag({ value, color }: { value: string; color: string }) {
  return (
    <span className={`rounded-md px-1.5 py-0.5 text-[9px] font-semibold ${color}`}>
      {value}
    </span>
  );
}

function IconTag({ icon: Icon, value, color }: { icon: React.ComponentType<{ className?: string }>; value: string; color: string }) {
  return (
    <div className={`flex items-center gap-1 rounded-md bg-zinc-800/80 px-1.5 py-0.5 ${color}`}>
      <Icon className="h-3 w-3" />
      <span className="text-[9px] font-semibold">{value}</span>
    </div>
  );
}

export function PerceptionMeter({ perception }: { perception: PerceptionState | undefined }) {
  if (!perception?.available) {
    return (
      <div className="flex items-center justify-center py-3 text-[10px] text-zinc-600">
        Perception offline
      </div>
    );
  }

  return (
    <div className="px-3 py-2.5">
      {/* Visual classification badges only */}
      <div className="flex flex-wrap items-center gap-1.5">
        {/* Faces */}
        <IconTag icon={User} value={`${perception.person_count ?? perception.face_count} detected`} color="text-emerald-400" />

        {/* Emotion */}
        <IconTag icon={Smile} value={perception.top_emotion || "neutral"} color={
          perception.top_emotion && perception.top_emotion !== "neutral"
            ? "text-rose-300" : "text-zinc-400"
        } />

        {/* Gaze */}
        <IconTag icon={Eye} value={perception.gaze_direction || "unknown"} color={
          perception.gaze_direction === "screen" ? "text-emerald-300"
            : perception.gaze_direction === "away" ? "text-amber-300"
              : "text-zinc-400"
        } />

        {/* Posture */}
        <Tag
          value={perception.posture || "unknown"}
          color={
            perception.posture === "upright"
              ? "bg-emerald-900/50 text-emerald-300"
              : perception.posture === "slouching"
                ? "bg-amber-900/50 text-amber-300"
                : "bg-zinc-800 text-zinc-400"
          }
        />

        {/* Hand gesture */}
        <IconTag icon={Hand} value={perception.hand_gesture || "none"} color={
          perception.hand_gesture && perception.hand_gesture !== "none"
            ? "text-violet-300" : "text-zinc-400"
        } />

        {/* Detected action */}
        <IconTag icon={Activity} value={perception.detected_action || "unknown"} color={
          perception.detected_action && perception.detected_action !== "unknown"
            ? "text-teal-300" : "text-zinc-400"
        } />

        {/* Scene type */}
        <IconTag icon={Scan} value={(perception.scene_type || "unknown").replace(/_/g, " ")} color={
          perception.scene_type && perception.scene_type !== "unknown"
            ? "text-teal-300" : "text-zinc-400"
        } />

        {/* Pose summary */}
        {perception.pose_summary && perception.pose_summary !== "unknown" && (
          <Tag value={`pose: ${perception.pose_summary}`} color="bg-zinc-800 text-zinc-300" />
        )}

        {/* Scene objects */}
        {perception.scene_objects && (
          <span className="truncate rounded-md bg-zinc-800/80 px-1.5 py-0.5 text-[9px] text-teal-400" style={{ maxWidth: "200px" }}>
            {perception.scene_objects}
          </span>
        )}
      </div>
    </div>
  );
}
