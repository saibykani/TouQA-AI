import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bug, FileUp, Image as ImageIcon, Paperclip, Plus, Save, Send, ShieldCheck, Trash2, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import { canWrite, useAuth } from "@/lib/auth";
import { useJob } from "@/lib/jobs";
import { useProject } from "@/lib/project";
import type { Attachment, IncidentDraft, Job } from "@/lib/types";
import { cn, fmtBytes, humanize, timeAgo } from "@/lib/utils";
import {
  Badge, Button, Card, CardBody, CardHeader, Checkbox, Dialog, EmptyState, ErrorBox, Field, Input, Loading, Notice, PageHeader,
  Select, StatusBadge, Textarea,
} from "@/components/ui";
import NoProject from "@/components/NoProject";
import JobStatus from "@/components/JobStatus";
import ScreenshotViewer from "@/components/ScreenshotViewer";

const hasContent = (c: any) => !!c && Object.keys(c).length > 0;
const LEVELS = ["critical", "high", "medium", "low", "unknown"];
const ENV_FIELDS = [["environment", "Environment"], ["browser", "Browser"], ["operating_system", "OS"], ["device", "Device"], ["application_version", "App version"], ["release", "Release"]] as const;

function Attachments({ draft, editable }: { draft: IncidentDraft; editable: boolean }) {
  const qc = useQueryClient();
  const { config } = useAuth();
  const input = useRef<HTMLInputElement>(null);
  const [view, setView] = useState<Attachment | null>(null);
  const [drag, setDrag] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["incident-draft", draft.id] });
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      for (const f of files) {
        if (config && f.size > config.max_upload_bytes) throw new Error(`${f.name} exceeds the ${fmtBytes(config.max_upload_bytes)} limit`);
        await api.upload(`/incident-drafts/${draft.id}/attachments`, f);
      }
    },
    onSuccess: () => { refresh(); toast.success("Evidence uploaded"); },
    onError: (e) => { refresh(); toast.error(errorMessage(e)); },
  });
  const toggle = useMutation({
    mutationFn: (a: Attachment) => api.patch(`/incident-drafts/${draft.id}/attachments/${a.id}`, { include_in_submission: !a.include_in_submission }),
    onSuccess: refresh,
  });
  const del = useMutation({ mutationFn: (a: Attachment) => api.del(`/incident-drafts/${draft.id}/attachments/${a.id}`), onSuccess: refresh });
  const src = (a: Attachment) => api.url(`/incident-drafts/${draft.id}/attachments/${a.id}/content`);

  // Paste screenshots straight from the clipboard.
  useEffect(() => {
    if (!editable) return;
    const h = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.files ?? []).filter((f) => f.type.startsWith("image/"));
      if (files.length) upload.mutate(files.map((f, i) => new File([f], f.name === "image.png" ? `screenshot-${Date.now()}-${i}.png` : f.name, { type: f.type })));
    };
    window.addEventListener("paste", h);
    return () => window.removeEventListener("paste", h);
  }, [editable, upload]);

  return (
    <div>
      {editable && (
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); upload.mutate(Array.from(e.dataTransfer.files)); }}
          onClick={() => input.current?.click()}
          className={cn("mb-3 flex cursor-pointer flex-col items-center gap-1 rounded-md border-2 border-dashed p-4 text-center text-xs text-muted-foreground hover:bg-muted/50", drag && "border-primary bg-accent")}
        >
          <FileUp className="h-5 w-5" />
          {upload.isPending ? "Uploading…" : "Drop screenshots, logs or files here, click to browse, or paste an image"}
          <input ref={input} type="file" multiple hidden onChange={(e) => { upload.mutate(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
        </div>
      )}
      {draft.attachments.length ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {draft.attachments.map((a) => (
            <div key={a.id} className={cn("overflow-hidden rounded-md border", !a.include_in_submission && "opacity-50")}>
              {a.is_image ? (
                <button onClick={() => setView(a)} className="block h-24 w-full bg-muted"><img src={src(a)} alt={a.filename} className="h-full w-full object-cover" loading="lazy" /></button>
              ) : <div className="flex h-24 items-center justify-center bg-muted"><Paperclip className="h-6 w-6 text-muted-foreground" /></div>}
              <div className="space-y-1 p-2">
                <div className="truncate text-xs font-medium" title={a.filename}>{a.filename}</div>
                <div className="text-[10px] text-muted-foreground">{fmtBytes(a.size_bytes)}{a.width ? ` · ${a.width}×${a.height}` : ""}</div>
                {editable && (
                  <div className="flex items-center justify-between">
                    <Checkbox checked={a.include_in_submission} onChange={() => toggle.mutate(a)} label={<span className="text-[10px]">Attach</span>} />
                    <button onClick={() => del.mutate(a)} className="rounded p-1 text-destructive hover:bg-muted" aria-label="Remove"><Trash2 className="h-3 w-3" /></button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : <p className="text-xs text-muted-foreground">No evidence attached.</p>}
      {view && <ScreenshotViewer src={src(view)} alt={view.filename} onClose={() => setView(null)} />}
    </div>
  );
}

function Editor({ draft, projectId }: { draft: IncidentDraft; projectId: number }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const writer = canWrite(user) && !["submitting", "submitted"].includes(draft.status);
  const [notes, setNotes] = useState(draft.raw_notes);
  const [evidence, setEvidence] = useState<any>(draft.evidence ?? { environment: {} });
  const [content, setContent] = useState<any>(hasContent(draft.content) ? draft.content : null);
  const [cls, setCls] = useState<any>(draft.classification ?? {});
  const [dests, setDests] = useState(draft.destinations);
  const [dirty, setDirty] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  useEffect(() => {
    setNotes(draft.raw_notes); setEvidence(draft.evidence ?? { environment: {} }); setContent(hasContent(draft.content) ? draft.content : null);
    setCls(draft.classification ?? {}); setDests(draft.destinations); setDirty(false);
  }, [draft]);

  const meta = useQuery({ queryKey: ["metadata", projectId], queryFn: () => api.get<Record<string, any[]>>(`/projects/${projectId}/metadata`) });
  const releases = useQuery({ queryKey: ["releases", projectId], queryFn: () => api.get<any[]>(`/releases?project_id=${projectId}`) });
  const integrations = useQuery({ queryKey: ["integrations"], queryFn: () => api.get<any>("/integrations") });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["incident-draft", draft.id] }); qc.invalidateQueries({ queryKey: ["incident-drafts", projectId] }); };

  const save = useMutation({
    mutationFn: () => api.put<IncidentDraft>(`/incident-drafts/${draft.id}`, { raw_notes: notes, evidence, content: content ?? undefined, classification: cls, destinations: dests }),
    onSuccess: () => { refresh(); toast.success("Saved"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const analyze = useMutation({
    mutationFn: async () => {
      if (dirty) await api.put(`/incident-drafts/${draft.id}`, { raw_notes: notes, evidence, classification: cls, destinations: dests });
      return api.post<Job>(`/incident-drafts/${draft.id}/analyze`);
    },
    onSuccess: (j) => setJobId(j.id),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const job = useJob(jobId, (j) => { refresh(); j.error ? toast.error(j.error) : toast.success("Incident drafted — review it below"); });

  const mark = () => setDirty(true);
  const setEnv = (k: string, v: string) => { setEvidence({ ...evidence, environment: { ...(evidence.environment ?? {}), [k]: v } }); mark(); };
  const setC = (k: string, v: any) => { setContent({ ...content, [k]: v }); mark(); };
  const setSp = (k: string, v: string) => { setCls({ ...cls, spira: { ...(cls.spira ?? {}), [k]: v || null } }); mark(); };
  const setJr = (k: string, v: string) => { setCls({ ...cls, jira: { ...(cls.jira ?? {}), [k]: v || null } }); mark(); };
  const m = meta.data ?? {};
  const jiraOk = integrations.data?.jira?.configured;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={draft.status} />
        {draft.is_simulated && <Badge tone="violet">simulated AI</Badge>}
        {draft.ai_model && <span className="text-xs text-muted-foreground">{draft.ai_provider} · {draft.ai_model}</span>}
        <div className="ml-auto flex gap-2">
          {writer && dirty && <Button size="sm" variant="outline" loading={save.isPending} onClick={() => save.mutate()}><Save className="h-3.5 w-3.5" />Save</Button>}
          {writer && <Button size="sm" variant={content ? "outline" : "default"} loading={analyze.isPending || (!!job && !job.finished_at)} onClick={() => analyze.mutate()}><Wand2 className="h-3.5 w-3.5" />{content ? "Re-draft with AI" : "Draft with AI"}</Button>}
          {content && <Button size="sm" disabled={dirty} title={dirty ? "Save first" : undefined} onClick={() => setPreviewOpen(true)}><Send className="h-3.5 w-3.5" />Preview & submit</Button>}
        </div>
      </div>
      {job && !job.finished_at && <JobStatus job={job} />}

      {draft.results && Object.keys(draft.results).length > 0 && (
        <Notice tone="green">
          {Object.entries(draft.results).map(([k, r]: any) => (
            <div key={k}><b className="capitalize">{k}</b>: {humanize(r.status)} {r.external_id && `IN:${r.external_id}`} {r.external_key} {r.url && <a className="underline" href={r.url} target="_blank" rel="noreferrer">open</a>} {r.error}</div>
          ))}
        </Notice>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="1 · What happened" description="Your notes and evidence. The AI only uses what you provide here." />
          <CardBody className="space-y-3">
            <fieldset disabled={!writer} className="space-y-3">
              <Field label="Notes"><Textarea value={notes} onChange={(e) => { setNotes(e.target.value); mark(); }} className="min-h-[110px]" placeholder="Describe the problem in your own words: what you did, what you expected, what happened…" /></Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Expected behaviour"><Textarea value={evidence.expected_behavior ?? ""} onChange={(e) => { setEvidence({ ...evidence, expected_behavior: e.target.value }); mark(); }} className="min-h-[56px]" /></Field>
                <Field label="Actual behaviour"><Textarea value={evidence.actual_behavior ?? ""} onChange={(e) => { setEvidence({ ...evidence, actual_behavior: e.target.value }); mark(); }} className="min-h-[56px]" /></Field>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {ENV_FIELDS.map(([k, label]) => <Field key={k} label={label}><Input value={evidence.environment?.[k] ?? ""} onChange={(e) => setEnv(k, e.target.value)} /></Field>)}
              </div>
              <details>
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Logs & API details</summary>
                <div className="mt-2 space-y-2">
                  <Textarea value={evidence.logs ?? ""} onChange={(e) => { setEvidence({ ...evidence, logs: e.target.value }); mark(); }} placeholder="Console / server logs" className="min-h-[70px] font-mono text-xs" />
                  <Textarea value={evidence.api_details ?? ""} onChange={(e) => { setEvidence({ ...evidence, api_details: e.target.value }); mark(); }} placeholder="Request / response details" className="min-h-[70px] font-mono text-xs" />
                </div>
              </details>
            </fieldset>
            <div>
              <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><ImageIcon className="h-3.5 w-3.5" />Evidence</div>
              <Attachments draft={draft} editable={writer} />
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="2 · Incident draft" description="Review and edit before submitting. Facts are separated from AI hypotheses." />
          <CardBody>
            {!content ? <EmptyState icon={<Wand2 className="h-5 w-5" />} title="No draft yet" description="Add notes or a screenshot, then choose “Draft with AI”." /> : (
              <fieldset disabled={!writer} className="space-y-3">
                {draft.validation?.length > 0 && (
                  <ul className="space-y-0.5 text-xs">{draft.validation.map((i, k) => <li key={k} className={i.severity === "error" ? "text-destructive" : "text-amber-700 dark:text-amber-300"}>{i.field}: {i.message}</li>)}</ul>
                )}
                <Field label="Title"><Input value={content.title ?? ""} onChange={(e) => setC("title", e.target.value)} /></Field>
                <Field label="Summary"><Textarea value={content.summary ?? ""} onChange={(e) => setC("summary", e.target.value)} className="min-h-[56px]" /></Field>
                <Field label="Steps to reproduce"><Textarea value={(content.steps_to_reproduce ?? []).join("\n")} onChange={(e) => setC("steps_to_reproduce", e.target.value.split("\n"))} className="min-h-[90px]" placeholder="One step per line" /></Field>
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Expected result"><Textarea value={content.expected_result ?? ""} onChange={(e) => setC("expected_result", e.target.value)} className="min-h-[56px]" /></Field>
                  <Field label="Actual result"><Textarea value={content.actual_result ?? ""} onChange={(e) => setC("actual_result", e.target.value)} className="min-h-[56px]" /></Field>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <Field label="Severity"><Select value={content.severity} onChange={(e) => setC("severity", e.target.value)}>{LEVELS.map((l) => <option key={l}>{l}</option>)}</Select></Field>
                  <Field label="Priority"><Select value={content.priority} onChange={(e) => setC("priority", e.target.value)}>{LEVELS.map((l) => <option key={l}>{l}</option>)}</Select></Field>
                  <Field label="Reproducibility"><Select value={content.reproducibility} onChange={(e) => setC("reproducibility", e.target.value)}>{["always", "intermittent", "once", "unknown"].map((l) => <option key={l}>{l}</option>)}</Select></Field>
                </div>
                <Field label="Impact"><Textarea value={content.impact ?? ""} onChange={(e) => setC("impact", e.target.value)} className="min-h-[48px]" /></Field>
                {content.observed_facts?.length > 0 && (
                  <div>
                    <div className="mb-1 text-xs font-medium text-muted-foreground">Observed facts</div>
                    <ul className="space-y-1 text-sm">{content.observed_facts.map((f: any, i: number) => <li key={i} className="flex gap-2"><Badge tone="green">{humanize(f.source)}</Badge><span>{f.statement}</span></li>)}</ul>
                  </div>
                )}
                {content.hypotheses?.length > 0 && (
                  <Notice tone="amber">
                    <div className="mb-1 font-medium">AI hypotheses (not verified)</div>
                    <ul className="space-y-1">{content.hypotheses.map((h: any, i: number) => <li key={i}>• {h.statement} <span className="opacity-70">— {h.rationale}</span></li>)}</ul>
                  </Notice>
                )}
              </fieldset>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="3 · Destination & classification" description="Values are resolved against your project's real Spira/Jira options. Nothing is guessed." />
        <CardBody className="space-y-4">
          <div className="flex gap-4">
            <Checkbox disabled={!writer} checked={dests.includes("spira")} onChange={(v) => { setDests(v ? [...dests, "spira"] : dests.filter((d) => d !== "spira")); mark(); }} label="Spira" />
            <Checkbox disabled={!writer || !jiraOk} checked={dests.includes("jira")} onChange={(v) => { setDests(v ? [...dests, "jira"] : dests.filter((d) => d !== "jira")); mark(); }} label={<>Jira {!jiraOk && <span className="text-xs text-muted-foreground">(not connected)</span>}</>} />
          </div>
          {dests.includes("spira") && (
            <fieldset disabled={!writer} className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {([["type_id", "Type", "incident_type"], ["priority_id", "Priority", "incident_priority"], ["severity_id", "Severity", "incident_severity"], ["status_id", "Status", "incident_status"]] as const).map(([k, label, kind]) => (
                <Field key={k} label={`Spira ${label}`}>
                  <Select value={cls.spira?.[k] ?? ""} onChange={(e) => setSp(k, e.target.value)}>
                    <option value="">(default)</option>
                    {(m[kind] ?? []).filter((o: any) => o.active !== false).map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </Select>
                </Field>
              ))}
              <Field label="Detected release">
                <Select value={cls.spira?.detected_release_id ?? ""} onChange={(e) => setSp("detected_release_id", e.target.value)}>
                  <option value="">(none)</option>
                  {(releases.data ?? []).map((r) => <option key={r.external_id} value={r.external_id}>{r.version} {r.name}</option>)}
                </Select>
              </Field>
            </fieldset>
          )}
          {dests.includes("jira") && (
            <fieldset disabled={!writer} className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <Field label="Jira issue type ID" hint="Defaults to the type set in Integrations"><Input value={cls.jira?.issue_type_id ?? ""} onChange={(e) => setJr("issue_type_id", e.target.value)} /></Field>
              <Field label="Jira priority ID"><Input value={cls.jira?.priority_id ?? ""} onChange={(e) => setJr("priority_id", e.target.value)} /></Field>
            </fieldset>
          )}
        </CardBody>
      </Card>

      {previewOpen && <IncidentPreview draft={draft} onClose={() => setPreviewOpen(false)} onDone={refresh} />}
    </div>
  );
}

function IncidentPreview({ draft, onClose, onDone }: { draft: IncidentDraft; onClose: () => void; onDone: () => void }) {
  const [confirmed, setConfirmed] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["incident-preview", draft.id, draft.updated_at], queryFn: () => api.get<any>(`/incident-drafts/${draft.id}/preview`) });
  const submit = useMutation({
    mutationFn: () => api.post<Job>(`/incident-drafts/${draft.id}/submit`, { confirm: true, payload_hash: q.data.payload_hash }),
    onSuccess: (j) => setJobId(j.id),
    onError: (e) => { toast.error(errorMessage(e)); q.refetch(); },
  });
  const job = useJob(jobId, (j) => { onDone(); j.error ? toast.error(j.error) : toast.success("Incident submitted"); });
  const p = q.data;
  return (
    <Dialog open onClose={onClose} wide title="Review incident before submitting" description="This is exactly what will be sent. Nothing is created until you approve."
      footer={jobId ? <Button onClick={onClose}>Close</Button> : (
        <>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!p || p.blocking || !p.writes_allowed || !confirmed} loading={submit.isPending} onClick={() => submit.mutate()}><ShieldCheck className="h-4 w-4" />Approve & submit</Button>
        </>
      )}>
      {jobId ? (
        <div className="space-y-3">
          <JobStatus job={job} />
          {job?.result?.results && Object.entries(job.result.results).map(([k, r]: any) => (
            <div key={k} className="flex items-center gap-2 text-sm"><b className="capitalize">{k}</b><StatusBadge status={r.status} />{r.external_id && <span>IN:{r.external_id}</span>}{r.external_key && <span>{r.external_key}</span>}{r.error && <span className="text-destructive">{r.error}</span>}</div>
          ))}
        </div>
      ) : q.isLoading ? <Loading label="Building preview and checking workflow rules…" /> : q.error ? <ErrorBox error={q.error} /> : p && (
        <div className="space-y-4">
          {!p.writes_allowed && <Notice tone="amber">{p.writes_disabled_reason}</Notice>}
          {p.blocking && <Notice tone="red">Resolve the blocking issues below before submitting.</Notice>}
          {Object.entries(p.destinations).map(([dest, d]: any) => (
            <div key={dest} className="rounded-md border">
              <div className="flex items-center gap-2 border-b px-3 py-2 text-sm font-medium capitalize">{dest} <span className="font-mono text-xs font-normal text-muted-foreground">{d.endpoint}</span>{d.blocking && <Badge tone="red">blocked</Badge>}</div>
              <div className="space-y-2 p-3 text-xs">
                {d.issues?.map((i: any, k: number) => <p key={k} className={i.severity === "error" ? "text-destructive" : "text-amber-700 dark:text-amber-300"}>{i.field}: {i.message}</p>)}
                {d.attachments?.length > 0 && <p>Attachments: {d.attachments.map((a: any) => a.filename).join(", ")}</p>}
                <pre className="max-h-56 overflow-auto rounded bg-muted p-2">{JSON.stringify(d.payload, null, 2)}</pre>
              </div>
            </div>
          ))}
          {p.rendered_html && (
            <details>
              <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Rendered description</summary>
              <iframe title="Description preview" sandbox="" srcDoc={p.rendered_html} className="mt-2 h-64 w-full rounded border bg-white" />
            </details>
          )}
          <Checkbox checked={confirmed} onChange={setConfirmed} disabled={p.blocking || !p.writes_allowed}
            label={<span className="text-xs">I reviewed this incident and approve submitting it. <span className="font-mono text-muted-foreground">#{p.payload_hash.slice(0, 10)}</span></span>} />
        </div>
      )}
    </Dialog>
  );
}

export default function IncidentStudio() {
  const { project } = useProject();
  const { user } = useAuth();
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const draftId = id ? Number(id) : null;

  const list = useQuery({ queryKey: ["incident-drafts", project?.id], queryFn: () => api.get<any[]>(`/incident-drafts?project_id=${project!.id}`), enabled: !!project });
  const draft = useQuery({ queryKey: ["incident-draft", draftId], queryFn: () => api.get<IncidentDraft>(`/incident-drafts/${draftId}`), enabled: !!draftId });
  const create = useMutation({
    mutationFn: () => api.post<IncidentDraft>("/incident-drafts", { project_id: project!.id, raw_notes: "", destinations: ["spira"] }),
    onSuccess: (d) => { qc.invalidateQueries({ queryKey: ["incident-drafts", project?.id] }); navigate(`/incident-studio/${d.id}`); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (rid: number) => api.del(`/incident-drafts/${rid}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["incident-drafts", project?.id] }); navigate("/incident-studio"); },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (!project) return <NoProject />;
  return (
    <>
      <PageHeader title="Incident Studio" description="Turn notes and screenshots into a well-structured incident, then submit to Spira and/or Jira after review."
        actions={canWrite(user) && <Button loading={create.isPending} onClick={() => create.mutate()}><Plus className="h-4 w-4" />New incident</Button>} />
      <div className="grid gap-4 xl:grid-cols-[280px_1fr]">
        <Card className="h-fit">
          <CardHeader title="Drafts" />
          {list.isLoading ? <Loading /> : list.data?.length ? (
            <ul className="max-h-[70vh] divide-y overflow-y-auto">
              {list.data.map((d) => (
                <li key={d.id} className={cn("group flex items-start gap-2 px-3 py-2 hover:bg-muted/50", draftId === d.id && "bg-accent")}>
                  <button className="min-w-0 flex-1 text-left" onClick={() => navigate(`/incident-studio/${d.id}`)}>
                    <div className="truncate text-sm">{d.title || "Untitled"}</div>
                    <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <StatusBadge status={d.status} />{d.attachment_count > 0 && <span className="flex items-center gap-0.5"><Paperclip className="h-3 w-3" />{d.attachment_count}</span>}<span>{timeAgo(d.updated_at)}</span>
                    </div>
                  </button>
                  {canWrite(user) && d.status !== "submitted" && (
                    <button onClick={() => remove.mutate(d.id)} className="invisible rounded p-1 text-muted-foreground hover:text-destructive group-hover:visible" aria-label="Delete draft"><Trash2 className="h-3.5 w-3.5" /></button>
                  )}
                </li>
              ))}
            </ul>
          ) : <EmptyState icon={<Bug className="h-5 w-5" />} title="No incident drafts" />}
        </Card>
        <div className="min-w-0">
          {!draftId ? <Card><EmptyState icon={<Bug className="h-6 w-6" />} title="Select or create an incident" description="Start with your notes and a screenshot. The AI drafts a structured report you can edit." /></Card>
            : draft.isLoading ? <Loading /> : draft.error ? <ErrorBox error={draft.error} /> : draft.data && <Editor draft={draft.data} projectId={project.id} />}
        </div>
      </div>
    </>
  );
}
