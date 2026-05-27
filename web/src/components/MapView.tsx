import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { Map as MlMap, Marker } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import Supercluster from "supercluster";
import type { Project } from "../types";
import { ProjectPanel } from "./ProjectPanel";

interface Props {
  projects: Project[];
  defaultCenter: [number, number];
}

const RASTER_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: [
        "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [
    { id: "osm", type: "raster", source: "osm" },
  ],
};

export function MapView({ projects, defaultCenter }: Props) {
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markersRef = useRef<Marker[]>([]);
  const [selected, setSelected] = useState<Project | null>(null);

  const geocoded = useMemo(
    () => projects.filter((p) => p.latitude !== null && p.longitude !== null),
    [projects]
  );

  const cluster = useMemo(() => {
    const sc = new Supercluster<{ project: Project }, {}>({
      radius: 50,
      maxZoom: 16,
    });
    sc.load(
      geocoded.map((p) => ({
        type: "Feature" as const,
        properties: { project: p },
        geometry: {
          type: "Point" as const,
          coordinates: [p.longitude!, p.latitude!],
        },
      }))
    );
    return sc;
  }, [geocoded]);

  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;
    const m = new maplibregl.Map({
      container: mapContainer.current,
      style: RASTER_STYLE,
      center: defaultCenter,
      zoom: 11.5,
      attributionControl: { compact: true },
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = m;
    m.on("moveend", refreshMarkers);
    m.on("zoomend", refreshMarkers);
    m.once("load", refreshMarkers);
    return () => {
      m.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    refreshMarkers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cluster]);

  function refreshMarkers() {
    const m = mapRef.current;
    if (!m) return;
    markersRef.current.forEach((mk) => mk.remove());
    markersRef.current = [];
    const b = m.getBounds();
    const bbox: [number, number, number, number] = [
      b.getWest(),
      b.getSouth(),
      b.getEast(),
      b.getNorth(),
    ];
    const z = Math.floor(m.getZoom());
    const clusters = cluster.getClusters(bbox, z);
    for (const f of clusters) {
      const [lng, lat] = (f.geometry as any).coordinates as [number, number];
      const props = f.properties as any;
      const el = document.createElement("div");
      if (props.cluster) {
        const count = props.point_count as number;
        const size = Math.min(56, 24 + Math.log2(count + 1) * 8);
        el.className = "cluster-marker";
        el.style.width = `${size}px`;
        el.style.height = `${size}px`;
        el.textContent = String(count);
        el.onclick = () => {
          const expansionZoom = cluster.getClusterExpansionZoom(f.id as number);
          m.flyTo({ center: [lng, lat], zoom: Math.min(expansionZoom, 17), speed: 1.4 });
        };
      } else {
        const project = props.project as Project;
        el.className = `point-marker point-${project.status}`;
        el.title = project.case_number;
        el.onclick = (ev) => {
          ev.stopPropagation();
          setSelected(project);
          m.flyTo({ center: [lng, lat], zoom: Math.max(m.getZoom(), 15), speed: 1.2 });
        };
      }
      const marker = new maplibregl.Marker({ element: el }).setLngLat([lng, lat]).addTo(m);
      markersRef.current.push(marker);
    }
  }

  return (
    <div className="relative flex-1 overflow-hidden">
      <div ref={mapContainer} className="absolute inset-0" />
      <ProjectPanel project={selected} onClose={() => setSelected(null)} />
      <div className="pointer-events-none absolute bottom-2 left-2 rounded-md bg-panel/80 px-2 py-1 text-xs text-muted">
        Showing {geocoded.length.toLocaleString()} of {projects.length.toLocaleString()} projects with coordinates
      </div>
    </div>
  );
}
