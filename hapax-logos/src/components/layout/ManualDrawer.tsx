import { X, Search, ChevronRight, ChevronDown, List, Printer, ChevronsUpDown } from "lucide-react";
import { useEffect, useCallback, useState, useRef, useMemo } from "react";
import { useManual } from "../../api/hooks";
import { MarkdownContent } from "../shared/MarkdownContent";

interface ManualDrawerProps {
  open: boolean;
  onClose: () => void;
}

interface TocEntry {
  id: string;
  title: string;
  level: number;
}

interface Section {
  id: string;
  title: string;
  level: number;
  content: string;
}

function toId(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function extractToc(content: string): TocEntry[] {
  const entries: TocEntry[] = [];
  for (const line of content.split("\n")) {
    const match = line.match(/^(#{2,3})\s+(.+)$/);
    if (match) {
      const level = match[1].length;
      const title = match[2];
      entries.push({ id: toId(title), title, level });
    }
  }
  return entries;
}

function splitSections(content: string): Section[] {
  const parts = content.split(/(?=^## )/m);
  const sections: Section[] = [];

  for (const part of parts) {
    const headingMatch = part.match(/^(#{2})\s+(.+)$/m);
    if (headingMatch) {
      sections.push({
        id: toId(headingMatch[2]),
        title: headingMatch[2],
        level: headingMatch[1].length,
        content: part,
      });
    } else if (part.trim()) {
      // Preamble before first H2
      sections.push({ id: "_preamble", title: "", level: 0, content: part });
    }
  }
  return sections;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function ManualDrawer({ open, onClose }: ManualDrawerProps) {
  const { data: manual, isError } = useManual();
  const [search, setSearch] = useState("");
  const [showToc, setShowToc] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [activeSection, setActiveSection] = useState<string>("");
  const [activeSubsection, setActiveSubsection] = useState<string>("");
  const contentRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  /* eslint-disable react-hooks/preserve-manual-memoization */
  const toc = useMemo(() => (manual?.content ? extractToc(manual.content) : []), [manual?.content]);

  const sections = useMemo(
    () => (manual?.content ? splitSections(manual.content) : []),
    [manual?.content],
  );
  /* eslint-enable react-hooks/preserve-manual-memoization */

  const filteredSections = useMemo(() => {
    if (!search.trim()) return sections;
    const query = search.toLowerCase();
    return sections.filter(
      (s) => s.level === 0 || s.title.toLowerCase().includes(query) || s.content.toLowerCase().includes(query),
    );
  }, [sections, search]);

  const allCollapsed = useMemo(
    () => sections.filter((s) => s.level > 0).every((s) => collapsed.has(s.id)),
    [sections, collapsed],
  );

  const toggleSection = (id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (allCollapsed) {
      setCollapsed(new Set());
    } else {
      setCollapsed(new Set(sections.filter((s) => s.level > 0).map((s) => s.id)));
    }
  };

  // Breadcrumb: track visible section via IntersectionObserver
  useEffect(() => {
    if (!open || !contentRef.current) return;

    const headings = contentRef.current.querySelectorAll("h2, h3");
    if (headings.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const el = entry.target as HTMLElement;
            const id = el.id || toId(el.textContent ?? "");
            if (el.tagName === "H2") {
              setActiveSection(id);
              setActiveSubsection("");
            } else if (el.tagName === "H3") {
              setActiveSubsection(id);
            }
          }
        }
      },
      { root: contentRef.current, rootMargin: "-10% 0px -80% 0px", threshold: 0 },
    );

    headings.forEach((h) => observer.observe(h));
    return () => observer.disconnect();
  }, [open, filteredSections, collapsed]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (search) {
          setSearch("");
        } else {
          onClose();
        }
      }
      if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
        const active = document.activeElement;
        if (active?.tagName !== "INPUT" && active?.tagName !== "TEXTAREA") {
          e.preventDefault();
          searchRef.current?.focus();
        }
      }
    },
    [onClose, search],
  );

  useEffect(() => {
    if (open) {
      document.addEventListener("keydown", handleKeyDown);
      return () => document.removeEventListener("keydown", handleKeyDown);
    }
  }, [open, handleKeyDown]);

  // Reset state when drawer closes
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!open) {
      setSearch("");
      setShowToc(false);
      setCollapsed(new Set());
      setActiveSection("");
      setActiveSubsection("");
    } else if (toc.length > 0 && !activeSection) {
      // Initialize active section to first H2 on open
      const first = toc.find((e) => e.level === 2);
      if (first) setActiveSection(first.id);
    }
  }, [open, toc, activeSection]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const scrollToSection = (id: string) => {
    setShowToc(false);
    setSearch("");
    // Ensure section is not collapsed
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.delete(id);
      // Also expand the parent H2 if scrolling to an H3
      const parentH2 = toc.find((e) => e.level === 2 && toc.indexOf(e) < toc.findIndex((t) => t.id === id));
      if (parentH2) next.delete(parentH2.id);
      return next;
    });
    // Delay to allow React to re-render expanded sections before scrolling
    setTimeout(() => {
      const el =
        contentRef.current?.querySelector(`[id="${id}"]`) ??
        Array.from(contentRef.current?.querySelectorAll("h2, h3") ?? []).find(
          (h) => toId(h.textContent ?? "") === id,
        );
      el?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 100);
  };

  const handlePrint = () => {
    window.print();
  };

  const searchCount = search.trim()
    ? filteredSections.filter((s) => s.level > 0).length
    : 0;

  const activeSectionTitle = toc.find((e) => e.id === activeSection)?.title;
  const activeSubsectionTitle = toc.find((e) => e.id === activeSubsection)?.title;

  return (
    <>
      {/* Backdrop */}
      {open && <div className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm print:hidden" onClick={onClose} />}

      {/* Drawer */}
      <div
        className={`fixed right-0 top-0 z-50 h-full w-full max-w-4xl transform border-l border-zinc-700 bg-zinc-900 shadow-xl transition-transform duration-200 print:static print:max-w-none print:transform-none print:border-0 print:shadow-none ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-zinc-700 px-4 py-2 print:hidden">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-zinc-200">Operations Manual</h2>
            {manual?.updated_at && (
              <span className="text-[10px] text-zinc-600" title={new Date(manual.updated_at).toLocaleString()}>
                updated {relativeTime(manual.updated_at)}
              </span>
            )}
            <button
              onClick={() => setShowToc((v) => !v)}
              className={`rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 ${showToc ? "bg-zinc-800 text-zinc-300" : ""}`}
              title="Table of contents"
            >
              <List className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={toggleAll}
              className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
              title={allCollapsed ? "Expand all sections" : "Collapse all sections"}
            >
              <ChevronsUpDown className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-zinc-500" />
              <input
                ref={searchRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search… (/)"
                className="w-64 rounded border border-zinc-700 bg-zinc-800 py-1 pl-7 pr-2 text-xs text-zinc-300 placeholder-zinc-600 focus:border-zinc-500 focus:outline-none"
              />
              {search && (
                <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-zinc-600">
                  {searchCount} sections
                </span>
              )}
            </div>
            <button
              onClick={handlePrint}
              className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
              title="Print manual"
            >
              <Printer className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={onClose}
              className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* TOC dropdown */}
        {showToc && (
          <div className="border-b border-zinc-700 max-h-64 overflow-y-auto px-4 py-2 bg-zinc-900/95 print:hidden">
            <nav className="space-y-0.5">
              {toc.map((entry) => (
                <button
                  key={entry.id}
                  onClick={() => scrollToSection(entry.id)}
                  className={`flex w-full items-center gap-1 rounded px-2 py-1 text-left text-xs hover:bg-zinc-800 ${
                    entry.id === activeSection || entry.id === activeSubsection
                      ? "bg-zinc-800 text-zinc-200"
                      : entry.level === 2
                        ? "text-zinc-300 font-medium"
                        : "text-zinc-500 pl-5"
                  }`}
                >
                  <ChevronRight className="h-2.5 w-2.5 flex-shrink-0 text-zinc-600" />
                  {entry.title}
                </button>
              ))}
            </nav>
          </div>
        )}

        {/* Breadcrumb */}
        {activeSectionTitle && !showToc && (
          <div className="flex items-center gap-1 border-b border-zinc-800 px-4 py-1 text-[11px] text-zinc-500 print:hidden">
            <button onClick={() => contentRef.current?.scrollTo({ top: 0, behavior: "smooth" })} className="hover:text-zinc-300">
              Manual
            </button>
            <ChevronRight className="h-2.5 w-2.5" />
            <button onClick={() => scrollToSection(activeSection)} className="hover:text-zinc-300 truncate max-w-[200px]">
              {activeSectionTitle}
            </button>
            {activeSubsectionTitle && (
              <>
                <ChevronRight className="h-2.5 w-2.5" />
                <button onClick={() => scrollToSection(activeSubsection)} className="hover:text-zinc-300 truncate max-w-[200px]">
                  {activeSubsectionTitle}
                </button>
              </>
            )}
          </div>
        )}

        {/* Content */}
        <div
          ref={contentRef}
          className={`overflow-y-auto p-4 print:overflow-visible ${
            activeSectionTitle && !showToc ? "h-[calc(100%-75px)]" : "h-[calc(100%-45px)]"
          }`}
        >
          {manual?.content ? (
            search.trim() && filteredSections.filter((s) => s.level > 0).length === 0 ? (
              <p className="text-xs text-zinc-500 py-8 text-center">No sections match "{search}"</p>
            ) : filteredSections.map((section) =>
              section.level === 0 ? (
                <div key={section.id} className="mb-4">
                  <MarkdownContent content={section.content} searchQuery={search || undefined} />
                </div>
              ) : (
                <div key={section.id} className="mb-2 print:break-inside-avoid">
                  <button
                    onClick={() => toggleSection(section.id)}
                    className="group flex w-full items-center gap-1.5 rounded px-1 py-1 text-left hover:bg-zinc-800/50 print:pointer-events-none"
                  >
                    <span className="print:hidden flex-shrink-0">
                      {collapsed.has(section.id) ? (
                        <ChevronRight className="h-3.5 w-3.5 text-zinc-600 group-hover:text-zinc-400" />
                      ) : (
                        <ChevronDown className="h-3.5 w-3.5 text-zinc-600 group-hover:text-zinc-400" />
                      )}
                    </span>
                    <h2 id={section.id} className="text-base font-semibold text-zinc-200 scroll-mt-4">
                      {section.title}
                    </h2>
                  </button>
                  {(!collapsed.has(section.id) || search.trim()) && (
                    <div className="pl-0">
                      <MarkdownContent
                        content={section.content.replace(/^## .+\n/, "")}
                        searchQuery={search || undefined}
                      />
                    </div>
                  )}
                </div>
              ),
            )
          ) : isError ? (
            <p className="text-xs text-red-400">Failed to load manual. Is the API running?</p>
          ) : (
            <p className="text-xs text-zinc-500">Loading manual...</p>
          )}
        </div>
      </div>

      {/* Print styles */}
      <style>{`
        @media print {
          body > *:not(.fixed) { display: none !important; }
          .fixed { position: static !important; transform: none !important; }
          .bg-zinc-900 { background: white !important; }
          .text-zinc-200, .text-zinc-300, .text-zinc-400 { color: black !important; }
          .text-zinc-500, .text-zinc-600 { color: #666 !important; }
          .border-zinc-700, .border-zinc-800 { border-color: #ccc !important; }
          .bg-zinc-800 { background: #f5f5f5 !important; }
          mark[data-search-highlight] { background: yellow !important; }
        }
      `}</style>
    </>
  );
}
