import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderSync, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import { canWrite, useAuth } from "@/lib/auth";
import { isTerminal, useJob } from "@/lib/jobs";
import { useProject } from "@/lib/project";
import type { Job } from "@/lib/types";
import { fmtDate, humanize, timeAgo } from "@/lib/utils";
import { Button, Card, CardBody, CardHeader, Checkbox, EmptyState, ErrorBox, Loading, Notice, PageHeader, StatusBadge, Table, Td, Th } from "@/components/ui";
import JobStatus from "@/components/JobStatus";
import NoProject from "@/components/NoProject";

const ENTITIES = ["metadata", "releases", "folders", "requirements", "test_cases", "test_sets", "incidents"] as const;
const OPTIONS = [
  ["include_test_steps", "Test steps"],
  ["include_requirement_coverage", "Requirement ↔ test case coverage"],
  ["include_test_set_membership", "Test set membership"],
  ["include_requirement_steps", "Requirement steps"],
  ["include_incident_attachments", "Incident attachment metadata"],
] as const;

function EntityTable({ rows }: { rows: any[] }) {
  return (
    <Table>
      <thead><tr><Th>Entity</Th><Th>Status</Th>{["Discovered", "Created", "Updated", "Skipped", "Failed"].map((h) => <Th key={h} className="text-right">{h}</Th>)}</tr></thead>
      <tbody>
        {rows.map((e) => (
          <tr key={e.entity_type}>
            <Td>{humanize(e.entity_type)}</Td>
            <Td><StatusBadge status={e.status} /></Td>
            {(["discovered", "created", "updated", "skipped", "failed"] as const).map((k) => (
              <Td key={k} className={`text-right tabular-nums ${k === "failed" && e[k] ? "text-destructive" : ""}`}>{e[k] ?? 0}</Td>
            ))}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

export default function Sync() {
  const { project } = useProject();
  const { user } = useAuth();
  const qc = useQueryClient();
  const [entities, setEntities] = useState<string[]>([...ENTITIES]);
  const [opts, setOpts] = useState<Record<string, boolean>>({ include_test_steps: true, include_requirement_coverage: true, include_test_set_membership: true, include_requirement_steps: false, include_incident_attachments: false });
  const [jobId, setJobId] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  const history = useQuery({
    queryKey: ["jobs", "sync", project?.id],
    queryFn: () => api.get<any>(`/sync/jobs?project_id=${project!.id}&page_size=15`),
    enabled: !!project,
    refetchInterval: (q) => (q.state.data?.items?.some((j: Job) => !isTerminal(j.status)) ? 2000 : false),
  });
  const start = useMutation({
    mutationFn: () => api.post<Job>("/sync/jobs", { project_id: project!.id, entities, options: opts }),
    onSuccess: (j) => { setJobId(j.id); qc.invalidateQueries({ queryKey: ["jobs", "sync"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const retry = useMutation({
    mutationFn: (id: number) => api.post<Job>(`/sync/jobs/${id}/retry`),
    onSuccess: (j) => { setJobId(j.id); qc.invalidateQueries({ queryKey: ["jobs", "sync"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const job = useJob(jobId, (j) => {
    qc.invalidateQueries();
    j.status === "COMPLETED" ? toast.success("Sync completed") : toast.warning(`Sync ${humanize(j.status.toLowerCase())}`);
  });
  const live = useQuery({ queryKey: ["sync-detail", jobId], queryFn: () => api.get<any>(`/sync/jobs/${jobId}`), enabled: !!jobId, refetchInterval: job && !isTerminal(job.status) ? 1500 : false });

  if (!project) return <NoProject />;
  const running = !!job && !isTerminal(job.status);

  return (
    <>
      <PageHeader title="Synchronization" description={<>Import records from Spira into TouQA. Read-only — nothing is changed in Spira. Last sync {timeAgo(project.last_synced_at)}.</>} />
      {project.is_demo && <Notice tone="blue" className="mb-4">The demo project uses synthetic data and is not synchronised from Spira.</Notice>}
      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <Card className="h-fit">
          <CardHeader title="New sync" />
          <CardBody className="space-y-4">
            <div>
              <div className="mb-2 flex items-center justify-between text-xs font-medium text-muted-foreground">
                Entities
                <button className="text-primary hover:underline" onClick={() => setEntities(entities.length === ENTITIES.length ? [] : [...ENTITIES])}>{entities.length === ENTITIES.length ? "None" : "All"}</button>
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                {ENTITIES.map((e) => <Checkbox key={e} checked={entities.includes(e)} onChange={(v) => setEntities(v ? [...entities, e] : entities.filter((x) => x !== e))} label={humanize(e)} />)}
              </div>
            </div>
            <div>
              <div className="mb-2 text-xs font-medium text-muted-foreground">Details</div>
              <div className="space-y-1.5">
                {OPTIONS.map(([k, label]) => <Checkbox key={k} checked={!!opts[k]} onChange={(v) => setOpts({ ...opts, [k]: v })} label={<span className="text-sm">{label}</span>} />)}
              </div>
            </div>
            <Button className="w-full" disabled={!canWrite(user) || !entities.length || project.is_demo} loading={start.isPending || running} onClick={() => start.mutate()}>
              <FolderSync className="h-4 w-4" />Start sync
            </Button>
            <p className="text-[11px] text-muted-foreground">Sync is incremental: unchanged records are skipped by content hash. Records deleted in Spira are flagged, not removed.</p>
          </CardBody>
        </Card>

        <div className="space-y-4">
          {jobId && (
            <Card>
              <CardHeader title={`Sync #${jobId}`} />
              <CardBody className="space-y-3">
                <JobStatus job={job} />
                {live.data?.entities?.length > 0 && <EntityTable rows={live.data.entities} />}
              </CardBody>
            </Card>
          )}
          <Card>
            <CardHeader title="History" />
            {history.isLoading ? <Loading /> : history.error ? <ErrorBox error={history.error} className="m-3" /> : history.data?.items.length ? (
              <ul className="divide-y">
                {history.data.items.map((j: any) => (
                  <li key={j.id}>
                    <div className="flex cursor-pointer items-center gap-3 px-4 py-2.5 text-sm hover:bg-muted/50" onClick={() => setExpanded(expanded === j.id ? null : j.id)}>
                      <span className="font-mono text-xs text-muted-foreground">#{j.id}</span>
                      <StatusBadge status={j.status} />
                      <span className="flex-1 truncate text-muted-foreground">{j.entities.map((e: any) => `${humanize(e.entity_type)} ${e.imported ?? 0}`).join(" · ")}</span>
                      <span className="text-xs text-muted-foreground">{fmtDate(j.created_at)}</span>
                      {["FAILED", "PARTIALLY_COMPLETED", "CANCELLED"].includes(j.status) && canWrite(user) && (
                        <Button size="sm" variant="ghost" loading={retry.isPending && retry.variables === j.id} onClick={(e) => { e.stopPropagation(); retry.mutate(j.id); }}><RotateCcw className="h-3.5 w-3.5" />Retry</Button>
                      )}
                    </div>
                    {expanded === j.id && (
                      <div className="space-y-2 bg-muted/30 px-4 py-3">
                        <EntityTable rows={j.entities} />
                        {j.entities.flatMap((e: any) => (e.errors ?? []).map((err: any, i: number) => (
                          <p key={`${e.entity_type}-${i}`} className="text-xs text-destructive">{humanize(e.entity_type)}{err.external_id ? ` #${err.external_id}` : ""}: {err.error}</p>
                        )))}
                        {j.error && <p className="text-xs text-destructive">{j.error}</p>}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            ) : <EmptyState icon={<FolderSync className="h-5 w-5" />} title="No syncs yet" />}
          </Card>
        </div>
      </div>
    </>
  );
}
