import { LoadingSkeleton } from "../shared/LoadingSkeleton";

interface SidebarSectionProps {
  title: string;
  children: React.ReactNode;
  clickable?: boolean;
  onClick?: () => void;
  loading?: boolean;
  age?: string;
}

export function SidebarSection({ title, children, clickable, onClick, loading, age }: SidebarSectionProps) {
  return (
    <div
      className={clickable ? "cursor-pointer rounded p-1 -m-1 hover:bg-zinc-800/50 focus-visible:ring-1 focus-visible:ring-zinc-500 focus-visible:outline-none" : ""}
      onClick={clickable ? onClick : undefined}
      onKeyDown={clickable ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick?.(); } } : undefined}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
    >
      <h3 className="mb-1 flex items-center gap-2 font-medium tracking-wide uppercase text-zinc-300">
        {title}
        {age && <span className="text-[10px] font-normal normal-case tracking-normal text-zinc-600">{age}</span>}
      </h3>
      <div className="space-y-1.5 text-zinc-400">
        {loading ? <LoadingSkeleton lines={2} /> : children}
      </div>
    </div>
  );
}
