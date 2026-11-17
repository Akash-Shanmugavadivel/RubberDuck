import { Activity, BookOpen, Code2, FileText, LayoutDashboard, LogOut, Menu, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const links = [
  ["/", "Overview", LayoutDashboard], ["/documents", "Course library", FileText],
  ["/tutor", "AI tutor", BookOpen], ["/workspace", "Python lab", Code2],
  ["/monitoring", "System health", Activity],
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const { user, logout } = useAuth();
  return <div className="app-shell">
    <button className="mobile-menu icon-button" onClick={() => setOpen(true)} aria-label="Open menu"><Menu /></button>
    {open && <button className="scrim" aria-label="Close menu" onClick={() => setOpen(false)} />}
    <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
      <div className="brand"><div className="brand-mark">⌁</div><div><strong>RubberDuck</strong><span>AI learning workspace</span></div></div>
      <button className="sidebar-close icon-button" onClick={() => setOpen(false)} aria-label="Close menu"><X /></button>
      <nav>{links.map(([to, label, Icon]) => <NavLink key={to} to={to} end={to === "/"} onClick={() => setOpen(false)}><Icon size={19}/><span>{label}</span></NavLink>)}</nav>
      <div className="account"><span>{user?.email}</span><button onClick={() => void logout()}><LogOut size={17}/>Sign out</button></div>
    </aside>
    <main className="main-content">{children}</main>
  </div>;
}

export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description: string; action?: ReactNode }) {
  return <header className="page-header"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1><p>{description}</p></div>{action}</header>;
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon">{icon}</div><h2>{title}</h2><p>{children}</p></div>;
}
