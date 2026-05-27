import { useEffect, useState } from "react";
import type { CityRef } from "../types";

interface Props {
  cities: CityRef[];
  selectedCity: string;
  onSelectCity: (slug: string) => void;
  view: "map" | "list";
  onView: (v: "map" | "list") => void;
}

export function Header({ cities, selectedCity, onSelectCity, view, onView }: Props) {
  const [dark, setDark] = useState(true);
  useEffect(() => {
    const stored = localStorage.getItem("theme");
    if (stored === "light") {
      document.documentElement.classList.remove("dark");
      setDark(false);
    } else {
      document.documentElement.classList.add("dark");
    }
  }, []);

  function toggleDark() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  }

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-panel/70 px-4 py-3 backdrop-blur">
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent/15 text-accent">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
            <path d="M12 2C8 2 5 5 5 9c0 5 7 13 7 13s7-8 7-13c0-4-3-7-7-7zm0 9.5A2.5 2.5 0 1112 6.5a2.5 2.5 0 010 5z" />
          </svg>
        </div>
        <div className="leading-tight">
          <div className="text-base font-semibold">City Planning Explorer</div>
          <div className="text-xs text-muted">Open data for civic projects</div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          className="input h-9 w-44"
          value={selectedCity}
          onChange={(e) => onSelectCity(e.target.value)}
        >
          {cities.map((c) => (
            <option key={c.slug} value={c.slug}>
              {c.name}, {c.state}
            </option>
          ))}
        </select>

        <div className="flex overflow-hidden rounded-md border border-border bg-panel text-sm">
          <button
            onClick={() => onView("map")}
            className={`px-3 py-1.5 transition-colors ${view === "map" ? "bg-accent/15 text-accent" : "hover:bg-border/40"}`}
          >
            Map
          </button>
          <button
            onClick={() => onView("list")}
            className={`px-3 py-1.5 transition-colors ${view === "list" ? "bg-accent/15 text-accent" : "hover:bg-border/40"}`}
          >
            List
          </button>
        </div>

        <button onClick={toggleDark} className="btn h-9" aria-label="Toggle dark mode" title="Toggle dark mode">
          {dark ? (
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor"><path d="M12 4V2m0 20v-2m8-8h2M2 12h2m13.66-5.66l1.41-1.41M4.93 19.07l1.41-1.41m0-11.31L4.93 4.93m14.14 14.14l-1.41-1.41M12 7a5 5 0 100 10 5 5 0 000-10z" /></svg>
          ) : (
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor"><path d="M21 12.79A9 9 0 1111.21 3a7 7 0 109.79 9.79z" /></svg>
          )}
        </button>
      </div>
    </header>
  );
}
