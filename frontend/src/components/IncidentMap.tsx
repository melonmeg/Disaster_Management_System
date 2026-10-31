"use client";
import "leaflet/dist/leaflet.css";
import { useEffect, useMemo, useRef } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import { SEVERITY_COLOR, dt, label } from "@/lib/format";

export type MapIncident = {
  incident_id: number; incident_type: string; severity: string; status: string; location: string;
  created_at: string; latitude: number | null; longitude: number | null;
};

function FitOnce({ points }: { points: [number, number][] }) {
  const map = useMap();
  const done = useRef("");
  const key = points.map((p) => p.join(",")).sort().join("|");
  useEffect(() => {
    if (!points.length || done.current === key) return;
    done.current = key;                                   // refit only when the set of markers changes
    map.fitBounds(points as LatLngBoundsExpression, { padding: [40, 40], maxZoom: 15 });
  }, [key, points, map]);
  return null;
}

/**
 * Markers: colour = severity; unresolved incidents are solid, resolved/closed are hollow rings.
 * With nothing geocoded the view is a neutral world view; no position is ever guessed.
 */
export default function IncidentMap({ incidents, selectedId, onSelect }: { incidents: MapIncident[]; selectedId: number | null; onSelect: (id: number) => void }) {
  const placed = useMemo(() => incidents.filter((i) => i.latitude !== null && i.longitude !== null), [incidents]);
  const points = useMemo(() => placed.map((i) => [i.latitude!, i.longitude!] as [number, number]), [placed]);

  return (
    <MapContainer center={[20, 0]} zoom={2} className="map" scrollWheelZoom>
      <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxZoom={19}
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' />
      <FitOnce points={points} />
      {placed.map((i) => {
        const done = i.status === "RESOLVED" || i.status === "CLOSED";
        const color = SEVERITY_COLOR[i.severity] ?? "#475569";
        return (
          <CircleMarker key={i.incident_id} center={[i.latitude!, i.longitude!]} radius={i.incident_id === selectedId ? 13 : 9}
            pathOptions={{ color: i.incident_id === selectedId ? "#111827" : color, weight: i.incident_id === selectedId ? 4 : 3, fillColor: color, fillOpacity: done ? 0.05 : 0.85 }}
            eventHandlers={{ click: () => onSelect(i.incident_id) }}>
            <Popup>
              <strong>#{i.incident_id} {i.incident_type}</strong><br />
              {i.severity} · {label(i.status)}<br />{i.location}<br /><span style={{ color: "#555" }}>{dt(i.created_at)}</span>
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
