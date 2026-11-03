import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { useProject } from "@/lib/project";
import { fmtDate } from "@/lib/utils";
import { Button, Dialog, ErrorBox, KV, Loading, PageHeader, StatusBadge } from "@/components/ui";
import RecordTable, { useOpenParam } from "@/components/RecordTable";
import NoProject from "@/components/NoProject";

const COLORS: Record<string, string> = { Passed: "bg-emerald-500", Failed: "bg-red-500", Caution: "bg-amber-500", Blocked: "bg-slate-500", NotRun: "bg-muted-foreground/30", NotApplicable: "bg-muted-foreground/15" };

function Counts({ counts }: { counts: Record<string, number | null> | null }) {
  const entries = Object.entries(counts ?? {}).filter(([, v]) => v);
  const total = entries.reduce((a, [, v]) => a + (v ?? 0), 0);
  if (!total) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="flex h-2 w-28 overflow-hidden rounded-full bg-muted" title={entries.map(([k, v]) => `${k}: ${v}`).join(", ")}>
      {entries.map(([k, v]) => <div key={k} className={COLORS[k] ?? "bg-muted"} style={{ width: `${(100 * (v ?? 0)) / total}%` }} />)}
    </div>
  );
}

function TestSetDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const q = useQuery({ queryKey: ["test-set", id], queryFn: () => api.get<any>(`/test-sets/${id}`) });
  const s = q.data;
  return (
    <Dialog open onClose={onClose} wide title={s ? <><span className="mr-2 font-mono text-xs text-muted-foreground">TX:{s.external_id}</span>{s.name}</> : "Test set"}
      footer={s?.url && <a href={s.url} target="_blank" rel="noreferrer"><Button variant="outline"><ExternalLink className="h-4 w-4" />Open in Spira</Button></a>}>
      {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} /> : s && (
        <div className="grid gap-4 md:grid-cols-[1fr_220px]">
          <div>
            {s.description_text && <p className="mb-3 whitespace-pre-wrap text-sm">{s.description_text}</p>}
            <div className="mb-1 text-xs font-medium text-muted-foreground">Test cases ({s.test_cases.length})</div>
            <ol className="divide-y rounded-md border text-sm">
              {s.test_cases.map((t: any) => (
                <li key={`${t.position}-${t.test_case_external_id}`} className="flex gap-2 px-3 py-1.5">
                  <span className="w-6 text-muted-foreground">{t.position}</span>
                  <span className="font-mono text-xs text-muted-foreground">TC:{t.test_case_external_id}</span>
                  {t.id ? <Link to={`/test-cases?open=${t.id}`} className="truncate hover:underline">{t.name}</Link> : <i className="text-muted-foreground">not imported</i>}
                </li>
              ))}
            </ol>
          </div>
          <div>
            <KV label="Status"><StatusBadge status={s.status} /></KV>
            <KV label="Release">{s.release}</KV>
            <KV label="Owner">{s.owner}</KV>
            <KV label="Planned">{fmtDate(s.planned_date, false)}</KV>
            <KV label="Results"><Counts counts={s.counts} /></KV>
            {s.folder_path?.length > 0 && <KV label="Folder">{s.folder_path.join(" / ")}</KV>}
          </div>
        </div>
      )}
    </Dialog>
  );
}

export default function TestSets() {
  const { project } = useProject();
  const [open, close] = useOpenParam();
  if (!project) return <NoProject />;
  return (
    <>
      <PageHeader title="Test Sets" description="Test sets and their latest execution results." />
      <RecordTable<any>
        endpoint="/test-sets" projectId={project.id} placeholder="Search name or TX:id"
        columns={[
          { header: "ID", cell: (r) => <span className="font-mono text-xs text-muted-foreground">TX:{r.external_id}</span>, className: "w-24" },
          { header: "Name", cell: (r) => <span className="font-medium">{r.name}</span> },
          { header: "Status", cell: (r) => <StatusBadge status={r.status} /> },
          { header: "Release", cell: (r) => r.release ?? "—" },
          { header: "Cases", cell: (r) => r.test_case_count, className: "tabular-nums" },
          { header: "Results", cell: (r) => <Counts counts={r.counts} /> },
          { header: "Planned", cell: (r) => fmtDate(r.planned_date, false) },
        ]}
      />
      {open && <TestSetDetail id={open} onClose={close} />}
    </>
  );
}
