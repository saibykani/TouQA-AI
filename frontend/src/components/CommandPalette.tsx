import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CornerDownLeft, Search } from "lucide-react";
import { api } from "@/lib/api";
import { useProject } from "@/lib/project";
import { cn, qs } from "@/lib/utils";
import { NAV } from "./Layout";
import { Spinner } from "./ui";

interface Hit { label: string; sub?: string; to: string }

const ROUTE_FOR: Record<string, (id: number) => string> = {
  requirement: (id) => `/requirements/${id}`,
  test_case: (id) => `/test-cases?open=${id}`,
  test_set: (id) => `/test-sets?open=${id}`,
  incident: (id) => `/incidents?open=${id}`,
};

export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [idx, setIdx] = useState(0);
  const navigate = useNavigate();
  const { project } = useProject();

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 200);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    if (open) {
      setQ("");
      setIdx(0);
    }
  }, [open]);

  const search = useQuery({
    queryKey: ["search", project?.id, debounced],
    queryFn: () => api.get<any>(`/search${qs({ project_id: project!.id, q: debounced })}`),
    enabled: open && !!project && debounced.length > 0,
  });

  const hits = useMemo<Hit[]>(() => {
    const pages: Hit[] = NAV.flatMap((g) => g.items)
      .filter((i) => !q || i.label.toLowerCase().includes(q.toLowerCase()))
      .map((i) => ({ label: i.label, sub: "Go to page", to: i.to }));
    const records: Hit[] = (search.data ?? [])
      .filter((r: any) => ROUTE_FOR[r.kind])
      .map((r: any) => ({ label: r.name, sub: r.label, to: ROUTE_FOR[r.kind](r.id) }));
    return [...records, ...pages].slice(0, 30);
  }, [q, search.data]);

  if (!open) return null;
  const go = (h?: Hit) => {
    if (!h) return;
    navigate(h.to);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-[12vh]" onMouseDown={onClose}>
      <div className="w-full max-w-xl overflow-hidden rounded-lg border bg-card shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b px-3">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input
            autoFocus
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setIdx(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, hits.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
              if (e.key === "Enter") go(hits[idx]);
              if (e.key === "Escape") onClose();
            }}
            placeholder="Search requirements, test cases, incidents (e.g. RQ:12)…"
            className="h-12 flex-1 bg-transparent text-sm outline-none"
          />
          {search.isFetching && <Spinner />}
        </div>
        <ul className="max-h-[50vh] overflow-y-auto p-1">
          {hits.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted-foreground">No matches</li>}
          {hits.map((h, i) => (
            <li key={`${h.to}-${i}`}>
              <button
                onMouseEnter={() => setIdx(i)}
                onClick={() => go(h)}
                className={cn("flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm", i === idx && "bg-muted")}
              >
                <span className="min-w-0 flex-1 truncate">{h.label}</span>
                <span className="shrink-0 text-xs capitalize text-muted-foreground">{h.sub}</span>
                {i === idx && <CornerDownLeft className="h-3.5 w-3.5 text-muted-foreground" />}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
