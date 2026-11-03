import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckCircle2, Download, KeyRound, Plug, Unplug, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import { isAdmin, useAuth } from "@/lib/auth";
import { useProject } from "@/lib/project";
import type { Project } from "@/lib/types";
import { fmtDate } from "@/lib/utils";
import { Badge, Button, Card, CardBody, CardHeader, Checkbox, ErrorBox, Field, Input, Loading, Notice, PageHeader, Select, StatusBadge } from "@/components/ui";

function SecretHint({ cfg }: { cfg: any }) {
  return cfg?.has_secret
    ? <span className="flex items-center gap-1"><KeyRound className="h-3 w-3" />Stored encrypted ({cfg.secret_fingerprint}). Leave blank to keep it.</span>
    : <>Stored encrypted on the server; never shown again.</>;
}

function ConnStatus({ cfg }: { cfg: any }) {
  if (!cfg?.configured) return <Badge>Not configured</Badge>;
  return (
    <span className="flex items-center gap-2 text-xs text-muted-foreground">
      <StatusBadge status={cfg.status} />
      {cfg.last_success_at && <>last OK {fmtDate(cfg.last_success_at)}</>}
    </span>
  );
}

function TestResult({ r }: { r: any }) {
  if (!r) return null;
  return r.ok ? (
    <Notice tone="green"><CheckCircle2 className="mr-1 inline h-3.5 w-3.5" />Connected{r.user ? ` as ${r.user.full_name || r.user.username || r.user.displayName || r.user.email || ""}` : ""}{r.project_count != null ? ` · ${r.project_count} projects visible` : ""}</Notice>
  ) : <Notice tone="red"><XCircle className="mr-1 inline h-3.5 w-3.5" />{r.error ?? r.message ?? "Connection failed"}</Notice>;
}

const spiraSchema = z.object({
  base_url: z.string().min(4, "Enter your Spira URL"),
  username: z.string().min(1, "Enter your Spira username"),
  api_key: z.string().optional(),
});

function SpiraCard({ cfg, admin }: { cfg: any; admin: boolean }) {
  const qc = useQueryClient();
  const [result, setResult] = useState<any>(null);
  const form = useForm<z.infer<typeof spiraSchema>>({ resolver: zodResolver(spiraSchema), defaultValues: { base_url: cfg?.base_url ?? "https://toucan.spiraservice.net/", username: cfg?.username ?? "", api_key: "" } });
  useEffect(() => { form.reset({ base_url: cfg?.base_url ?? "https://toucan.spiraservice.net/", username: cfg?.username ?? "", api_key: "" }); }, [cfg?.base_url, cfg?.username]); // eslint-disable-line react-hooks/exhaustive-deps
  const done = () => qc.invalidateQueries({ queryKey: ["integrations"] });
  const save = useMutation({
    mutationFn: (v: z.infer<typeof spiraSchema>) => api.put("/integrations/spira", { ...v, api_key: v.api_key || null }),
    onSuccess: () => { done(); form.setValue("api_key", ""); toast.success("Spira settings saved"); test.mutate(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const test = useMutation({
    mutationFn: () => api.post<any>("/integrations/spira/test"),
    onSuccess: (r) => { setResult(r); done(); qc.invalidateQueries({ queryKey: ["spira-projects"] }); },
    onError: (e) => setResult({ ok: false, error: errorMessage(e) }),
  });
  const disconnect = useMutation({ mutationFn: () => api.del("/integrations/spira"), onSuccess: () => { done(); setResult(null); toast.success("Spira disconnected"); } });

  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Plug className="h-4 w-4" />Spira</span>} description="Inflectra SpiraTest/SpiraTeam/SpiraPlan via REST v7.0" actions={<ConnStatus cfg={cfg} />} />
      <CardBody>
        <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="space-y-3">
          <fieldset disabled={!admin} className="space-y-3">
            <Field label="Spira URL" error={form.formState.errors.base_url?.message}><Input {...form.register("base_url")} placeholder="https://yourcompany.spiraservice.net/" /></Field>
            <Field label="Username" error={form.formState.errors.username?.message}><Input autoComplete="off" {...form.register("username")} /></Field>
            <Field label="RSS token / API key" hint={<SecretHint cfg={cfg} />}>
              <Input type="password" autoComplete="new-password" placeholder={cfg?.has_secret ? "••••••••  (unchanged)" : "{XXXXXXXX-XXXX-…}"} {...form.register("api_key")} />
            </Field>
          </fieldset>
          <p className="text-[11px] text-muted-foreground">In Spira: your profile → enable RSS Feeds → copy the RSS token including the braces.</p>
          <TestResult r={result} />
          {admin && (
            <div className="flex flex-wrap gap-2">
              <Button type="submit" loading={save.isPending}>Save & test</Button>
              {cfg?.configured && <Button type="button" variant="outline" loading={test.isPending} onClick={() => test.mutate()}>Test connection</Button>}
              {cfg?.configured && <Button type="button" variant="ghost" className="ml-auto text-destructive" onClick={() => disconnect.mutate()}><Unplug className="h-4 w-4" />Disconnect</Button>}
            </div>
          )}
        </form>
      </CardBody>
    </Card>
  );
}

const jiraSchema = z.object({
  base_url: z.string().min(4, "Enter your Jira URL"),
  flavor: z.enum(["cloud", "datacenter"]),
  email: z.string(),
  api_token: z.string().optional(),
  project_key: z.string().optional(),
  issue_type_id: z.string().optional(),
}).refine((v) => v.flavor !== "cloud" || v.email.length > 0, { message: "Jira Cloud needs the account email", path: ["email"] });

function JiraCard({ cfg, admin }: { cfg: any; admin: boolean }) {
  const qc = useQueryClient();
  const [result, setResult] = useState<any>(null);
  const defaults = () => ({ base_url: cfg?.base_url ?? "", flavor: (cfg?.flavor ?? "cloud") as "cloud" | "datacenter", email: cfg?.username ?? "", api_token: "",
    project_key: cfg?.settings?.project_key ?? "", issue_type_id: cfg?.settings?.issue_type_id ?? "" });
  const form = useForm<z.infer<typeof jiraSchema>>({ resolver: zodResolver(jiraSchema), defaultValues: defaults() });
  useEffect(() => { form.reset(defaults()); }, [cfg?.base_url, cfg?.username, cfg?.settings?.project_key]); // eslint-disable-line react-hooks/exhaustive-deps
  const flavor = form.watch("flavor");
  const projectKey = form.watch("project_key");
  const done = () => qc.invalidateQueries({ queryKey: ["integrations"] });
  const types = useQuery({
    queryKey: ["jira-issue-types", projectKey],
    queryFn: () => api.get<any[]>(`/integrations/jira/issue-types?project_key=${encodeURIComponent(projectKey!)}`),
    enabled: !!cfg?.configured && !!projectKey,
    retry: false,
  });
  const save = useMutation({
    mutationFn: (v: z.infer<typeof jiraSchema>) => api.put("/integrations/jira", { ...v, api_token: v.api_token || null, project_key: v.project_key || null, issue_type_id: v.issue_type_id || null }),
    onSuccess: () => { done(); form.setValue("api_token", ""); toast.success("Jira settings saved"); test.mutate(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const test = useMutation({
    mutationFn: () => api.post<any>("/integrations/jira/test"),
    onSuccess: (r) => { setResult(r); done(); },
    onError: (e) => setResult({ ok: false, error: errorMessage(e) }),
  });
  const disconnect = useMutation({ mutationFn: () => api.del("/integrations/jira"), onSuccess: () => { done(); setResult(null); toast.success("Jira disconnected"); } });

  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Plug className="h-4 w-4" />Jira</span>} description="Optional — submit incidents to Jira Cloud or Data Center" actions={<ConnStatus cfg={cfg} />} />
      <CardBody>
        <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="space-y-3">
          <fieldset disabled={!admin} className="space-y-3">
            <div className="grid grid-cols-[1fr_140px] gap-2">
              <Field label="Jira URL" error={form.formState.errors.base_url?.message}><Input {...form.register("base_url")} placeholder="https://yourcompany.atlassian.net" /></Field>
              <Field label="Deployment"><Select {...form.register("flavor")}><option value="cloud">Cloud</option><option value="datacenter">Data Center</option></Select></Field>
            </div>
            {flavor === "cloud" && <Field label="Account email" error={form.formState.errors.email?.message}><Input autoComplete="off" {...form.register("email")} /></Field>}
            <Field label={flavor === "cloud" ? "API token" : "Personal access token"} hint={<SecretHint cfg={cfg} />}>
              <Input type="password" autoComplete="new-password" placeholder={cfg?.has_secret ? "••••••••  (unchanged)" : ""} {...form.register("api_token")} />
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Project key"><Input {...form.register("project_key")} placeholder="QA" /></Field>
              <Field label="Issue type for bugs">
                {types.data?.length ? (
                  <Select {...form.register("issue_type_id")}><option value="">Select…</option>{types.data.filter((t) => !t.subtask).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select>
                ) : <Input {...form.register("issue_type_id")} placeholder="Issue type ID" />}
              </Field>
            </div>
          </fieldset>
          <TestResult r={result} />
          {admin && (
            <div className="flex flex-wrap gap-2">
              <Button type="submit" loading={save.isPending}>Save & test</Button>
              {cfg?.configured && <Button type="button" variant="outline" loading={test.isPending} onClick={() => test.mutate()}>Test connection</Button>}
              {cfg?.configured && <Button type="button" variant="ghost" className="ml-auto text-destructive" onClick={() => disconnect.mutate()}><Unplug className="h-4 w-4" />Disconnect</Button>}
            </div>
          )}
        </form>
      </CardBody>
    </Card>
  );
}

function AICard({ ai, admin }: { ai: any; admin: boolean }) {
  const qc = useQueryClient();
  const [v, setV] = useState({ provider: ai.provider, model: ai.model ?? "", vision_model: ai.vision_model ?? "", base_url: ai.base_url ?? "", vision_enabled: ai.vision_enabled });
  const [result, setResult] = useState<any>(null);
  useEffect(() => setV({ provider: ai.provider, model: ai.model ?? "", vision_model: ai.vision_model ?? "", base_url: ai.base_url ?? "", vision_enabled: ai.vision_enabled }), [ai]);
  const save = useMutation({
    mutationFn: () => api.put("/integrations/ai", { ...v, base_url: v.base_url || null, vision_model: v.vision_model || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["integrations"] }); toast.success("AI settings saved"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const test = useMutation({
    mutationFn: () => api.post<any>("/integrations/ai/test"),
    onSuccess: setResult,
    onError: (e) => setResult({ ok: false, error: errorMessage(e) }),
  });
  const keyOk = v.provider === "anthropic" ? ai.anthropic_key_configured : v.provider === "openai_compatible" ? ai.api_key_configured : true;
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Bot className="h-4 w-4" />AI provider</span>} description="Used for analysis, test generation and incident drafting"
        actions={ai.simulated ? <Badge tone="violet">Simulated</Badge> : <Badge tone="green">{ai.provider}</Badge>} />
      <CardBody className="space-y-3">
        {ai.demo_mode && <Notice tone="blue">Demo mode is on — the simulated provider is always used.</Notice>}
        <fieldset disabled={!admin || ai.demo_mode} className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <Field label="Provider">
              <Select value={v.provider} onChange={(e) => setV({ ...v, provider: e.target.value })}>
                <option value="anthropic">Anthropic (Claude)</option>
                <option value="openai_compatible">OpenAI-compatible</option>
                <option value="local">Local (Ollama / LM Studio)</option>
                <option value="simulated">Simulated (no AI)</option>
              </Select>
            </Field>
            <Field label="Model"><Input value={v.model} onChange={(e) => setV({ ...v, model: e.target.value })} placeholder={v.provider === "anthropic" ? "claude-opus-5-5" : ""} /></Field>
          </div>
          {v.provider !== "anthropic" && v.provider !== "simulated" && (
            <Field label="Base URL"><Input value={v.base_url} onChange={(e) => setV({ ...v, base_url: e.target.value })} placeholder={v.provider === "local" ? "http://localhost:11434/v1" : "https://…/v1"} /></Field>
          )}
          <div className="grid grid-cols-2 items-end gap-2">
            <Field label="Vision model (screenshots)"><Input value={v.vision_model} onChange={(e) => setV({ ...v, vision_model: e.target.value })} placeholder="Same as model" /></Field>
            <div className="pb-2"><Checkbox checked={v.vision_enabled} onChange={(c) => setV({ ...v, vision_enabled: c })} label="Analyse screenshots" /></div>
          </div>
        </fieldset>
        {!keyOk && (
          <Notice tone="amber">
            No API key configured for this provider. Add {v.provider === "anthropic" ? <code>ANTHROPIC_API_KEY</code> : <code>AI_API_KEY</code>} to the backend <code>.env</code> file and restart — keys are never entered in the browser.
          </Notice>
        )}
        <TestResult r={result && { ...result, user: null }} />
        {admin && (
          <div className="flex gap-2">
            <Button loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
            <Button variant="outline" loading={test.isPending} onClick={() => test.mutate()}>Test AI</Button>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function ProjectImport({ spiraOk }: { spiraOk: boolean }) {
  const qc = useQueryClient();
  const { projects, setProjectId } = useProject();
  const remote = useQuery({ queryKey: ["spira-projects"], queryFn: () => api.get<any[]>("/integrations/spira/projects"), enabled: spiraOk, retry: false });
  const imported = new Set(projects.filter((p) => p.platform === "spira" && !p.is_demo).map((p) => p.external_id));
  const imp = useMutation({
    mutationFn: (external_id: string) => api.post<Project>("/projects/import", { external_id }),
    onSuccess: (p) => { qc.invalidateQueries({ queryKey: ["projects"] }); setProjectId(p.id); toast.success(`${p.name} added. Run a sync to import its records.`); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const seed = useMutation({
    mutationFn: () => api.post<Project>("/projects/demo/seed"),
    onSuccess: (p) => { qc.invalidateQueries({ queryKey: ["projects"] }); setProjectId(p.id); toast.success("Demo project loaded"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card>
      <CardHeader title="Projects" description="Choose which Spira projects TouQA works with"
        actions={<Button size="sm" variant="outline" loading={seed.isPending} onClick={() => seed.mutate()}>Load demo project</Button>} />
      <CardBody>
        {!spiraOk ? <p className="text-sm text-muted-foreground">Connect Spira to list your projects.</p>
          : remote.isLoading ? <Loading /> : remote.error ? <ErrorBox error={remote.error} /> : (
            <ul className="max-h-80 divide-y overflow-y-auto rounded-md border">
              {remote.data?.map((p) => (
                <li key={p.external_id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <span className="w-14 font-mono text-xs text-muted-foreground">PR:{p.external_id}</span>
                  <span className="flex-1 truncate">{p.name}</span>
                  {!p.active && <Badge>inactive</Badge>}
                  {imported.has(p.external_id) ? <Badge tone="green">Added</Badge>
                    : <Button size="sm" variant="outline" loading={imp.isPending && imp.variables === p.external_id} onClick={() => imp.mutate(p.external_id)}><Download className="h-3.5 w-3.5" />Add</Button>}
                </li>
              ))}
            </ul>
          )}
      </CardBody>
    </Card>
  );
}

export default function Integrations() {
  const { user } = useAuth();
  const admin = isAdmin(user);
  const q = useQuery({ queryKey: ["integrations"], queryFn: () => api.get<any>("/integrations") });
  return (
    <>
      <PageHeader title="Integrations" description="Connect Spira, Jira and your AI provider. Credentials are encrypted at rest and never returned to the browser." />
      {!admin && <Notice tone="amber" className="mb-4">Only administrators can change integrations.</Notice>}
      {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} /> : (
        <div className="grid gap-4 lg:grid-cols-2">
          <SpiraCard cfg={q.data.spira} admin={admin} />
          <ProjectImport spiraOk={!!q.data.spira?.configured} />
          <JiraCard cfg={q.data.jira} admin={admin} />
          <AICard ai={q.data.ai} admin={admin} />
        </div>
      )}
    </>
  );
}
