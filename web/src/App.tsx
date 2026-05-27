import { useEffect, useMemo, useState } from "react";
import { Header } from "./components/Header";
import { Filters, type FilterState } from "./components/Filters";
import { MapView } from "./components/MapView";
import { ListView } from "./components/ListView";
import { loadMeta, loadProjects } from "./data";
import type { CityRef, Meta, Project } from "./types";

const DEFAULT_CENTER: [number, number] = [-117.9414, 33.7739];

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"map" | "list">("map");
  const [city, setCity] = useState<string>("garden-grove-ca");
  const [filters, setFilters] = useState<FilterState>({
    q: "",
    status: "all",
    year: "",
    hearingBody: "",
  });

  useEffect(() => {
    Promise.all([loadProjects(), loadMeta()])
      .then(([p, m]) => {
        setProjects(p);
        setMeta(m);
        if (m.cities.length > 0 && !m.cities.find((c) => c.slug === city)) {
          setCity(m.cities[0].slug);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cities: CityRef[] = meta?.cities || [];

  const cityProjects = useMemo(
    () => projects.filter((p) => p.city_slug === city),
    [projects, city]
  );

  const years = useMemo(() => {
    const ys = new Set<string>();
    for (const p of cityProjects) {
      const d = p.last_seen_date || "";
      if (d.length >= 4 && /^\d{4}/.test(d)) ys.add(d.slice(0, 4));
    }
    return Array.from(ys).sort().reverse();
  }, [cityProjects]);

  const hearingBodies = useMemo(() => {
    const set = new Set<string>();
    for (const p of cityProjects) if (p.hearing_body) set.add(p.hearing_body);
    return Array.from(set).sort();
  }, [cityProjects]);

  const filtered = useMemo(() => {
    const q = filters.q.trim().toLowerCase();
    return cityProjects.filter((p) => {
      if (filters.status !== "all" && p.status !== filters.status) return false;
      if (filters.year && !(p.last_seen_date || "").startsWith(filters.year)) return false;
      if (filters.hearingBody && p.hearing_body !== filters.hearingBody) return false;
      if (q) {
        const hay = `${p.case_number} ${p.address} ${p.description} ${p.applicant_name}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [cityProjects, filters]);

  return (
    <div className="flex h-screen flex-col bg-bg text-fg">
      <Header
        cities={cities}
        selectedCity={city}
        onSelectCity={setCity}
        view={view}
        onView={setView}
      />
      <Filters
        state={filters}
        onChange={setFilters}
        years={years}
        hearingBodies={hearingBodies}
        total={cityProjects.length}
        filtered={filtered.length}
      />

      {error && <div className="p-4 text-sm text-rose-400">Error: {error}</div>}
      {loading && (
        <div className="flex flex-1 items-center justify-center text-muted">Loading projects…</div>
      )}
      {!loading && !error && (
        <>
          {view === "map" ? (
            <MapView projects={filtered} defaultCenter={DEFAULT_CENTER} />
          ) : (
            <ListView projects={filtered} />
          )}
        </>
      )}

      <footer className="border-t border-border bg-panel/50 px-4 py-2 text-xs text-muted">
        Map data © OpenStreetMap contributors · Project data: City of Garden Grove DPU public records ·
        {meta && (
          <span> {meta.counts.total.toLocaleString()} projects, {meta.counts.geocoded.toLocaleString()} geocoded · updated {new Date(meta.generated_at).toLocaleDateString()}</span>
        )}
      </footer>
    </div>
  );
}
