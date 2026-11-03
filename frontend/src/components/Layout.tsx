import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity, Bug, ClipboardList, FlaskConical, FolderSync, Gauge, Layers, LogOut, Menu, Moon, Plug, Rocket, Search,
  Settings as SettingsIcon, Sparkles, Sun, X, FileText,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useProject } from "@/lib/project";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { Badge, Select } from "./ui";
import CommandPalette from "./CommandPalette";

export const NAV = [
  { group: "Workspace", items: [
    { to: "/", label: "Overview", icon: Gauge },
    { to: "/requirements", label: "Requirements", icon: FileText },
    { to: "/designer", label: "AI Test Designer", icon: Sparkles },
    { to: "/test-cases", label: "Test Cases", icon: FlaskConical },
    { to: "/test-sets", label: "Test Sets", icon: Layers },
    { to: "/incidents", label: "Incidents", icon: Bug },
    { to: "/incident-studio", label: "Incident Studio", icon: ClipboardList },
    { to: "/releases", label: "Releases", icon: Rocket },
  ] },
  { group: "Operations", items: [
    { to: "/sync", label: "Synchronization", icon: FolderSync },
    { to: "/audit", label: "Audit Log", icon: Activity },
  ] },
  { group: "Configuration", items: [
    { to: "/integrations", label: "Integrations", icon: Plug },
    { to: "/settings", label: "Settings & Mapping", icon: SettingsIcon },
  ] },
];

function ConnectionDots() {
  const { data } = useQuery({ queryKey: ["integrations"], queryFn: () => api.get<any>("/integrations"), staleTime: 60_000 });
  if (!data) return null;
  const items = [
    { k: "Spira", ok: data.spira?.status === "connected" || data.spira?.configured },
    { k: "Jira", ok: data.jira?.status === "connected" || data.jira?.configured },
    { k: "AI", ok: data.ai?.provider && data.ai.provider !== "simulated", label: data.ai?.provider },
  ];
  return (
    <div className="hidden items-center gap-3 text-xs text-muted-foreground md:flex">
      {items.map((i) => (
        <NavLink key={i.k} to="/integrations" className="flex items-center gap-1.5 hover:text-foreground" title={i.label ?? undefined}>
          <span className={cn("h-2 w-2 rounded-full", i.ok ? "bg-emerald-500" : "bg-muted-foreground/40")} />
          {i.k}
        </NavLink>
      ))}
    </div>
  );
}

export default function Layout() {
  const { user, config, logout } = useAuth();
  const { projects, project, setProjectId } = useProject();
  const { theme, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const [palette, setPalette] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const sidebar = (
    <nav className="flex h-full flex-col">
      <div className="flex h-14 items-center gap-2 border-b px-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">TQ</div>
        <span className="font-semibold">{config?.app_name ?? "TouQA AI"}</span>
        {config?.demo_mode && <Badge tone="violet" className="ml-auto">Demo</Badge>}
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-3">
        {NAV.map((g) => (
          <div key={g.group} className="mb-4">
            <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{g.group}</div>
            {g.items.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  cn("flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
                    isActive ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")
                }
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            ))}
          </div>
        ))}
      </div>
      <div className="border-t p-3 text-xs">
        <div className="truncate font-medium">{user?.display_name || user?.email}</div>
        <div className="flex items-center justify-between text-muted-foreground">
          <span className="capitalize">{user?.role}</span>
          {config?.auth_enabled && (
            <button onClick={logout} className="flex items-center gap-1 hover:text-foreground"><LogOut className="h-3.5 w-3.5" /> Sign out</button>
          )}
        </div>
      </div>
    </nav>
  );

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 border-r bg-card lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <aside className="absolute left-0 top-0 h-full w-64 border-r bg-card" onClick={(e) => e.stopPropagation()}>
            <button className="absolute right-2 top-3 rounded p-1 hover:bg-muted" onClick={() => setOpen(false)} aria-label="Close menu"><X className="h-4 w-4" /></button>
            {sidebar}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-card/90 px-4 backdrop-blur">
          <button className="rounded p-1.5 hover:bg-muted lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
          <div className="flex min-w-0 items-center gap-2">
            <Select
              aria-label="Project"
              className="h-8 w-56 max-w-[45vw] text-xs"
              value={project?.id ?? ""}
              onChange={(e) => (e.target.value === "__add" ? navigate("/integrations") : setProjectId(Number(e.target.value)))}
            >
              {!projects.length && <option value="">No projects yet</option>}
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.is_demo ? "◆ " : ""}{p.name} {p.platform === "spira" && !p.is_demo ? `(PR:${p.external_id})` : ""}</option>
              ))}
              <option value="__add">+ Add project…</option>
            </Select>
            {project?.is_demo && <Badge tone="violet" title="Synthetic data — nothing is sent externally">Demo data</Badge>}
          </div>
          <button
            onClick={() => setPalette(true)}
            className="ml-auto flex h-8 items-center gap-2 rounded-md border bg-background px-3 text-xs text-muted-foreground hover:bg-muted sm:w-64"
          >
            <Search className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Search or jump to…</span>
            <kbd className="ml-auto hidden rounded border px-1 text-[10px] sm:inline">Ctrl K</kbd>
          </button>
          <ConnectionDots />
          <button onClick={toggle} className="rounded p-1.5 hover:bg-muted" aria-label="Toggle theme">
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
        </header>
        <main className="mx-auto w-full max-w-[1500px] flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </div>
  );
}
