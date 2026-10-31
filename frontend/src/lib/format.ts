export const SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"] as const;
export const INCIDENT_STATUSES = ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"] as const;
export const DISPATCH_NEXT: Record<string, string[]> = {
  DISPATCHED: ["EN_ROUTE", "ON_SCENE", "CANCELLED"],
  EN_ROUTE: ["ON_SCENE", "CANCELLED"],
  ON_SCENE: ["COMPLETED"],
  COMPLETED: [],
  CANCELLED: [],
};

// Severity colours are also used for map markers; status is shown by shape/outline there.
export const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: "#b91c1c", HIGH: "#ea580c", MEDIUM: "#ca8a04", LOW: "#2563eb",
};

export function dt(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return isNaN(d.getTime()) ? value : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function minutes(m?: number | null): string {
  if (m === null || m === undefined) return "—";
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

export const label = (s?: string | null) => (s ? s.replace(/_/g, " ") : "—");
