import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Project } from "./types";

interface Ctx { projects: Project[]; project: Project | null; setProjectId: (id: number) => void; loading: boolean }
const ProjectContext = createContext<Ctx>({ projects: [], project: null, setProjectId: () => {}, loading: true });
const KEY = "touqa.projectId";

export function ProjectProvider({ children }: { children: ReactNode }) {
  const { data = [], isLoading } = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
  const [id, setId] = useState<number | null>(() => {
    try {
      const v = localStorage.getItem(KEY);
      return v ? Number(v) : null;
    } catch {
      return null;
    }
  });
  useEffect(() => {
    if (data.length && !data.some((p) => p.id === id)) setId(data[0].id);
  }, [data, id]);
  const value = useMemo<Ctx>(
    () => ({
      projects: data,
      project: data.find((p) => p.id === id) ?? null,
      loading: isLoading,
      setProjectId: (n) => {
        setId(n);
        try {
          localStorage.setItem(KEY, String(n));
        } catch {
          /* storage unavailable */
        }
      },
    }),
    [data, id, isLoading],
  );
  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

export const useProject = () => useContext(ProjectContext);
