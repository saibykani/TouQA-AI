import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { useProject } from "@/lib/project";
import { fmtBytes, fmtDate, timeAgo } from "@/lib/utils";
import { Badge, Button, Checkbox, Dialog, ErrorBox, KV, Loading, PageHeader, StatusBadge } from "@/components/ui";
import RecordTable, { useOpenParam } from "@/components/RecordTable";
import NoProject from "@/components/NoProject";

const sevTone = (s?: string | null) => (/(1|critical|high)/i.test(s ?? "") ? "red" : /(2|medium)/i.test(s ?? "") ? "amber" : "neutral") as "red" | "amber" | "neutral";

function IncidentDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const q = useQuery({ queryKey: ["incident", id], queryFn: () => api.get<any>(`/incidents/${id}`) });
  const i = q.data;
  return (
    <Dialog open onClose={onClose} wide title={i ? <><span className="mr-2 font-mono text-xs text-muted-foreground">{i.external_key ?? `IN:${i.external_id}`}</span>{i.name}</> : "Incident"}
      footer={i?.url && <a href={i.url} target="_blank" rel="noreferrer"><Button variant="outline"><ExternalLink className="h-4 w-4" />Open</Button></a>}>
      {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} /> : i && (
        <div className="grid gap-4 md:grid-cols-[1fr_220px]">
          <div className="min-w-0">
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{i.description_text || <span className="italic text-muted-foreground">No description</span>}</p>
            {i.attachments?.length > 0 && (
              <>
                <div className="mb-1 mt-4 text-xs font-medium text-muted-foreground">Attachments</div>
                <ul className="text-sm">{i.attachments.map((a: any) => <li key={a.external_id}>{a.filename} <span className="text-xs text-muted-foreground">{a.size_bytes ? fmtBytes(a.size_bytes) : ""}</span></li>)}</ul>
              </>
            )}
          </div>
          <div>
            <KV label="Status"><StatusBadge status={i.status} /></KV>
            <KV label="Type">{i.type}</KV>
            <KV label="Priority">{i.priority}</KV>
            <KV label="Severity">{i.severity}</KV>
            <KV label="Owner">{i.owner}</KV>
            <KV label="Opener">{i.opener}</KV>
            <KV label="Detected in">{i.detected_release}</KV>
            <KV label="Resolved in">{i.resolved_release}</KV>
            <KV label="Created">{fmtDate(i.created_at)}</KV>
          </div>
        </div>
      )}
    </Dialog>
  );
}

export default function Incidents() {
  const { project } = useProject();
  const navigate = useNavigate();
  const [open, close] = useOpenParam();
  const [openOnly, setOpenOnly] = useState(false);
  if (!project) return <NoProject />;
  return (
    <>
      <PageHeader title="Incidents" description="Defects imported from Spira and those submitted through Incident Studio."
        actions={<Button onClick={() => navigate("/incident-studio")}><Plus className="h-4 w-4" />Report incident</Button>} />
      <RecordTable<any>
        endpoint="/incidents" projectId={project.id} placeholder="Search name, text or IN:id" filters={{ open_only: openOnly || undefined }}
        extra={<Checkbox checked={openOnly} onChange={setOpenOnly} label="Open only" />}
        columns={[
          { header: "ID", cell: (r) => <span className="font-mono text-xs text-muted-foreground">{r.external_key ?? `IN:${r.external_id}`}</span>, className: "w-24" },
          { header: "Name", cell: (r) => <span className="font-medium">{r.name}</span> },
          { header: "Status", cell: (r) => <StatusBadge status={r.status} /> },
          { header: "Priority", cell: (r) => r.priority ? <Badge tone={sevTone(r.priority)}>{r.priority}</Badge> : "—" },
          { header: "Severity", cell: (r) => r.severity ? <Badge tone={sevTone(r.severity)}>{r.severity}</Badge> : "—" },
          { header: "Type", cell: (r) => r.type ?? "—" },
          { header: "Owner", cell: (r) => r.owner ?? "—" },
          { header: "Updated", cell: (r) => <span className="text-xs text-muted-foreground">{timeAgo(r.updated_at)}</span> },
        ]}
      />
      {open && <IncidentDetail id={open} onClose={close} />}
    </>
  );
}
