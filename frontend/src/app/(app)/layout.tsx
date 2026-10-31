"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";
import { Spinner } from "@/components/ui";

const NAV: { href: string; text: string; roles?: string[] }[] = [
  { href: "/dashboard", text: "Dashboard" },
  { href: "/incidents", text: "Incidents" },
  { href: "/map", text: "Map" },
  { href: "/dispatches", text: "Dispatches" },
  { href: "/units", text: "Units & responders" },
  { href: "/resources", text: "Resources" },
  { href: "/logs", text: "Operational log", roles: ["admin"] },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, ready, logout } = useAuth();
  const router = useRouter();
  const path = usePathname();

  // Client-side guard (UX only): the API enforces the real permissions on every request.
  useEffect(() => { if (ready && !user) router.replace("/login"); }, [ready, user, router]);
  if (!ready || !user) return <Spinner text="Checking session…" />;

  return (
    <div className="shell">
      <a className="skip" href="#content">Skip to content</a>
      <nav className="side" aria-label="Main">
        <div className="brand">ERMS Console</div>
        {NAV.filter((n) => !n.roles || n.roles.includes(user.role)).map((n) => (
          <Link key={n.href} href={n.href} aria-current={path === n.href || path.startsWith(n.href + "/") ? "page" : undefined}>{n.text}</Link>
        ))}
        <div className="who">
          <div><strong>{user.username}</strong></div>
          <div style={{ textTransform: "capitalize" }}>{user.role}</div>
          <button className="btn small" style={{ marginTop: 6 }} onClick={logout}>Sign out</button>
        </div>
      </nav>
      <main id="content" className="main">{children}</main>
    </div>
  );
}
