import type { Meta, Project } from "./types";

const PROJECTS_URL = `${import.meta.env.BASE_URL}data/projects.json`;
const META_URL = `${import.meta.env.BASE_URL}data/meta.json`;

let projectsCache: Project[] | null = null;
let metaCache: Meta | null = null;

export async function loadProjects(): Promise<Project[]> {
  if (projectsCache) return projectsCache;
  const res = await fetch(PROJECTS_URL);
  if (!res.ok) throw new Error(`failed to load projects.json: ${res.status}`);
  projectsCache = await res.json();
  return projectsCache!;
}

export async function loadMeta(): Promise<Meta> {
  if (metaCache) return metaCache;
  const res = await fetch(META_URL);
  if (!res.ok) throw new Error(`failed to load meta.json: ${res.status}`);
  metaCache = await res.json();
  return metaCache!;
}
