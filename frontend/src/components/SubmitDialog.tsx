import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Folder, FolderPlus, RefreshCw, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import { useJob } from "@/lib/jobs";
import type { FolderNode, Job } from "@/lib/types";
import { cn, fmtDate } from "@/lib/utils";
import { Badge, Button, Checkbox, Dialog, ErrorBox, Field, Input, Loading, Notice, StatusBadge } from "./ui";
import JobStatus from "./JobStatus";

function FolderTree({ nodes, value, onChange, depth = 0 }: { nodes: FolderNode[]; value: string | null; onChange: (v: string) => void; depth?: number }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  return (
    <ul>
      {nodes.map((n) => {
        const isOpen = open[n.external_id] ?? false;
        const kids = n.children ?? [];
        return (
          <li key={n.external_id}>
            <div
              onClick={() => onChange(n.external_id)}
              className={cn("flex cursor-pointer items-center gap-1 rounded px-1 py-1 text-sm hover:bg-muted", value === n.external_id && "bg-accent text-accent-foreground")}
              style={{ paddingLeft: depth * 14 + 4 }}
            >
              {kids.length ? (
                <button onClick={(e) => { e.stopPropagation(); setOpen((o) => ({ ...o, [n.external_id]: !isOpen })); }} className="rounded p-0.5" aria-label="Toggle">
                  <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", isOpen && "rotate-90")} />
                </button>
              ) : <span className="w-4" />}
              <Folder className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="truncate">{n.name}</span>
            </div>
            {isOpen && kids.length > 0 && <FolderTree nodes={kids} value={value} onChange={onChange} depth={depth + 1} />}
          </li>
        );
      })}
    </ul>
  );
}

function CreateFolder({ projectId, parent, onCreated }: { projectId: number; parent: string | null; onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const doPreview = useMutation({
    mutationFn: () => api.post<any>("/folders/preview", { project_id: projectId, name, parent_external_id: parent }),
    onSuccess: setPreview,
    onError: (e) => toast.error(errorMessage(e)),
  });
  const create = useMutation({
    mutationFn: () => api.post<any>("/folders", { project_id: projectId, name, parent_external_id: parent, confirm: true }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["folders", projectId] });
      toast.success(r.already_existed ? "Folder already existed — selected it" : "Folder created in Spira");
      onCreated(r.folder.external_id);
      setPreview(null);
      setName("");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="space-y-2 rounded-md border border-dashed p-3">
      <div className="flex gap-2">
        <Input placeholder="New folder name" value={name} onChange={(e) => { setName(e.target.value); setPreview(null); }} />
        <Button variant="outline" disabled={!name.trim()} loading={doPreview.isPending} onClick={() => doPreview.mutate()}>Preview</Button>
      </div>
      {preview && (
        <div className="space-y-2 text-xs">
          <p>Will create <b>{preview.path.join(" / ")}</b> via <code>{preview.operation}</code></p>
          <pre className="overflow-x-auto rounded bg-muted p-2">{JSON.stringify(preview.payload, null, 2)}</pre>
          {preview.duplicate && <Notice tone="amber">A folder with this name already exists here. Select it instead.</Notice>}
          {!preview.writes_allowed && <Notice tone="amber">{preview.writes_disabled_reason}</Notice>}
          <Button size="sm" disabled={!preview.writes_allowed || !!preview.duplicate} loading={create.isPending} onClick={() => create.mutate()}>
            <FolderPlus className="h-3.5 w-3.5" />Create folder in Spira
          </Button>
        </div>
      )}
    </div>
  );
}

/** Folder selection → exact payload preview → explicit approval → background submission. */
export default function SubmitDialog({ open, onClose, projectId, draftIds, onDone }: {
  open: boolean; onClose: () => void; projectId: number; draftIds: number[]; onDone: () => void;
}) {
  const qc = useQueryClient();
  const [folder, setFolder] = useState<string | null>(null);
  const [includeTags, setIncludeTags] = useState(true);
  const [confirmed, setConfirmed] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const folders = useQuery({
    queryKey: ["folders", projectId],
    queryFn: () => api.get<{ tree: FolderNode[]; synced_at: string | null }>(`/folders?project_id=${projectId}&folder_type=test_case`),
    enabled: open,
  });
  const refresh = useMutation({
    mutationFn: () => api.post<any>(`/folders/refresh?project_id=${projectId}`),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["folders", projectId] }); toast.success(r.note ?? "Folders refreshed from Spira"); },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const body = useMemo(() => ({ project_id: projectId, draft_ids: draftIds, folder_external_id: folder, options: { include_tags: includeTags } }),
    [projectId, draftIds, folder, includeTags]);
  const preview = useQuery({
    queryKey: ["submission-preview", body],
    queryFn: () => api.post<any>("/submissions/test-cases/preview", body),
    enabled: open && draftIds.length > 0 && !jobId,
  });
  useEffect(() => setConfirmed(false), [preview.data?.payload_hash]);
  useEffect(() => { if (!open) { setJobId(null); setConfirmed(false); } }, [open]);

  const submit = useMutation({
    mutationFn: () => api.post<Job>("/submissions/test-cases", { ...body, confirm: true, payload_hash: preview.data.payload_hash }),
    onSuccess: (j) => setJobId(j.id),
    onError: (e) => { toast.error(errorMessage(e)); preview.refetch(); },
  });
  const job = useJob(jobId, (j) => {
    onDone();
    const r = j.result ?? {};
    if (r.created === r.total) toast.success(`Created ${r.created} test case(s) in Spira`);
    else toast.warning(`Created ${r.created ?? 0} of ${r.total ?? draftIds.length}. Review the results.`);
  });

  const p = preview.data;
  return (
    <Dialog open={open} onClose={onClose} wide title={`Create ${draftIds.length} test case(s) in Spira`}
      description="Nothing is sent until you review the exact payload and approve it."
      footer={jobId ? <Button onClick={onClose}>Close</Button> : (
        <>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!p || p.blocking || !p.writes_allowed || !confirmed} loading={submit.isPending} onClick={() => submit.mutate()}>
            <ShieldCheck className="h-4 w-4" />Approve & create in Spira
          </Button>
        </>
      )}>
      {jobId ? (
        <div className="space-y-3">
          <JobStatus job={job} />
          {job?.result?.results && (
            <ul className="divide-y rounded-md border text-sm">
              {job.result.results.map((r: any) => (
                <li key={r.draft_id} className="flex items-center gap-2 px-3 py-2">
                  <span className="text-muted-foreground">Draft #{r.draft_id}</span>
                  <StatusBadge status={r.status} />
                  {r.external_id && (r.url ? <a className="text-primary hover:underline" href={r.url} target="_blank" rel="noreferrer">TC:{r.external_id}</a> : <span>TC:{r.external_id}</span>)}
                  {r.error && <span className="truncate text-xs text-destructive">{r.error}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-[260px_1fr]">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">Destination folder</span>
              <button onClick={() => refresh.mutate()} className="rounded p-1 text-muted-foreground hover:bg-muted" title="Refresh from Spira" aria-label="Refresh folders">
                <RefreshCw className={cn("h-3.5 w-3.5", refresh.isPending && "animate-spin")} />
              </button>
            </div>
            <div className="max-h-64 overflow-y-auto rounded-md border p-1">
              <div onClick={() => setFolder(null)} className={cn("cursor-pointer rounded px-2 py-1 text-sm hover:bg-muted", folder === null && "bg-accent text-accent-foreground")}>(Project root)</div>
              {folders.isLoading ? <Loading /> : <FolderTree nodes={folders.data?.tree ?? []} value={folder} onChange={setFolder} />}
            </div>
            <p className="text-[11px] text-muted-foreground">Folders synced {fmtDate(folders.data?.synced_at)}</p>
            {showCreate ? <CreateFolder projectId={projectId} parent={folder} onCreated={(id) => { setFolder(id); setShowCreate(false); }} />
              : <Button size="sm" variant="outline" onClick={() => setShowCreate(true)}><FolderPlus className="h-3.5 w-3.5" />New folder here</Button>}
            <Checkbox checked={includeTags} onChange={setIncludeTags} label={<span className="text-xs">Include tags</span>} />
          </div>
          <div className="min-w-0 space-y-3">
            {preview.isLoading && <Loading label="Building preview…" />}
            <ErrorBox error={preview.error} />
            {p && (
              <>
                <div className="text-sm">Destination: <b>{p.folder_path.join(" / ")}</b> <span className="text-muted-foreground">(PR:{p.project_external_id})</span></div>
                {!p.writes_allowed && <Notice tone="amber">{p.writes_disabled_reason}</Notice>}
                {p.already_created?.length > 0 && <Notice tone="blue">{p.already_created.length} draft(s) were already created and will be skipped.</Notice>}
                {p.blocking && <Notice tone="red">Some drafts have blocking errors. Fix or deselect them.</Notice>}
                <ul className="space-y-2">
                  {p.payloads.map((x: any) => (
                    <li key={x.draft_id} className="rounded-md border">
                      <details>
                        <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm">
                          <span className="flex-1 truncate font-medium">{x.name}</span>
                          <Badge>{x.test_steps.length} steps</Badge>
                          {x.coverage_link ? <Badge tone="green">→ RQ:{x.coverage_link.RequirementId}</Badge> : <Badge tone="amber">no coverage</Badge>}
                          {x.blocking && <Badge tone="red">blocked</Badge>}
                        </summary>
                        <div className="space-y-2 border-t p-3 text-xs">
                          {x.issues.map((i: any, k: number) => <p key={k} className={i.severity === "error" ? "text-destructive" : "text-amber-700 dark:text-amber-300"}>{i.field}: {i.message}</p>)}
                          <pre className="max-h-64 overflow-auto rounded bg-muted p-2">{JSON.stringify({ test_case: x.test_case, test_steps: x.test_steps, coverage_link: x.coverage_link }, null, 2)}</pre>
                        </div>
                      </details>
                    </li>
                  ))}
                </ul>
                <Field label="Approval">
                  <Checkbox checked={confirmed} onChange={setConfirmed} disabled={p.blocking || !p.writes_allowed}
                    label={<span className="text-xs">I reviewed these payloads and approve creating them in Spira. <span className="font-mono text-muted-foreground">#{p.payload_hash.slice(0, 10)}</span></span>} />
                </Field>
              </>
            )}
          </div>
        </div>
      )}
    </Dialog>
  );
}
