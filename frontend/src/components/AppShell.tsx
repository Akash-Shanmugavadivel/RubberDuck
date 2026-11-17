import { Activity, BookOpen, ChevronLeft, ChevronRight, Code2, FileText, LayoutDashboard, LogOut, Menu, Moon, ShieldCheck, Sun, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const links = [
  ["/", "Overview", LayoutDashboard], ["/documents", "Course library", FileText],
  ["/tutor", "AI tutor", BookOpen], ["/workspace", "Python lab", Code2],
  ["/monitoring", "System health", Activity],
] as const;

const pageNames: Record<string, string> = { "/": "Overview", "/documents": "Course library", "/tutor": "AI tutor", "/workspace": "Python lab", "/monitoring": "System health", "/tutor-policy": "Tutor policy" };

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("rubberduck_sidebar") === "collapsed");
  const [dark, setDark] = useState(() => localStorage.getItem("rubberduck_theme") === "dark");
  const { user, logout } = useAuth();
  const location = useLocation();
  const initials = user?.email.slice(0, 2).toUpperCase() ?? "RD";

  useEffect(() => { document.documentElement.dataset.theme = dark ? "dark" : "light"; localStorage.setItem("rubberduck_theme", dark ? "dark" : "light"); }, [dark]);
  useEffect(() => { localStorage.setItem("rubberduck_sidebar", collapsed ? "collapsed" : "open"); }, [collapsed]);

  return <div className={`app-shell ${collapsed ? "shell-collapsed" : ""}`}>
    <button className="mobile-menu icon-button" onClick={() => setOpen(true)} aria-label="Open menu"><Menu/></button>
    {open && <button className="scrim" aria-label="Close menu" onClick={() => setOpen(false)}/>} 
    <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
      <div className="sidebar-head"><div className="brand"><div className="brand-mark">⌁</div><div className="brand-copy"><strong>RubberDuck</strong><span>AI learning workspace</span></div></div><button className="collapse-button" onClick={() => setCollapsed(value => !value)} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>{collapsed ? <ChevronRight/> : <ChevronLeft/>}</button></div>
      <button className="sidebar-close icon-button" onClick={() => setOpen(false)} aria-label="Close menu"><X/></button>
      <p className="nav-label">Workspace</p>
      <nav>{links.map(([to, label, Icon]) => <NavLink key={to} to={to} end={to === "/"} onClick={() => setOpen(false)} title={collapsed ? label : undefined}><Icon size={19}/><span>{label}</span></NavLink>)}{user?.role === "instructor" && <NavLink to="/tutor-policy" onClick={() => setOpen(false)} title={collapsed ? "Tutor policy" : undefined}><ShieldCheck size={19}/><span>Tutor policy</span></NavLink>}</nav>
      <div className="sidebar-footer"><button className="theme-toggle" onClick={() => setDark(value => !value)}>{dark ? <Sun/> : <Moon/>}<span>{dark ? "Light mode" : "Dark mode"}</span></button><div className="account"><div className="account-avatar">{initials}</div><div className="account-copy"><strong>{user?.email.split("@")[0]}</strong><span>{user?.role}</span></div><button onClick={() => void logout()} aria-label="Sign out" title="Sign out"><LogOut size={17}/></button></div></div>
    </aside>
    <main className="main-content"><div className="context-bar"><span>RubberDuck</span><strong>/</strong><span>{pageNames[location.pathname] ?? "Classroom"}</span><button onClick={() => setDark(value => !value)} aria-label="Toggle color theme">{dark ? <Sun/> : <Moon/>}</button></div>{children}</main>
  </div>;
}

export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description: string; action?: ReactNode }) {
  return <header className="page-header"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1><p>{description}</p></div>{action}</header>;
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon">{icon}</div><h2>{title}</h2><p>{children}</p></div>;
}
