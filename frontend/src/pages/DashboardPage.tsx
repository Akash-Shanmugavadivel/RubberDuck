import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BookOpen, CheckCircle2, Code2, Database, FileText, MessageSquareText, NotebookPen, Server, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/AppShell";

export function DashboardPage() {
  const { user } = useAuth();
  const documents = useQuery({ queryKey: ["documents"], queryFn: api.documents });
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.conversations });
  const notes = useQuery({ queryKey: ["notes"], queryFn: api.notes });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  const ready = useQuery({ queryKey: ["readiness"], queryFn: api.readiness, retry: false, refetchInterval: 30_000 });
  const resourceCount = documents.data?.length ?? 0;
  const studentName = user?.email.split("@")[0].split(/[._-]/)[0] ?? "student";

  return <div className="page dashboard-page"><PageHeader eyebrow="YOUR AI PYTHON CLASSROOM" title={`Welcome back, ${studentName}.`} description="Pick up where you left off or start a focused learning session."/>
    <section className="dashboard-hero"><div className="dashboard-hero-copy"><span><Sparkles/>AI tutor ready</span><h2>Turn course material into understanding.</h2><p>Ask grounded questions, practice Python safely, and keep your best explanations organised.</p><div><Link className="primary" to="/tutor"><MessageSquareText/>Continue learning</Link><Link className="secondary" to="/documents"><FileText/>Add material</Link></div></div><div className="hero-orbit"><div><BookOpen/></div><span>Ask</span><span>Build</span><span>Understand</span></div></section>
    <section className="overview-stats"><article><FileText/><div><strong>{resourceCount}</strong><span>Learning resources</span></div></article><article><MessageSquareText/><div><strong>{conversations.data?.length ?? 0}</strong><span>Conversations</span></div></article><article><NotebookPen/><div><strong>{notes.data?.length ?? 0}</strong><span>Saved notes</span></div></article><article><CheckCircle2/><div><strong>{ready.data?.status === "ready" ? "Ready" : "Checking"}</strong><span>Classroom status</span></div></article></section>
    <div className="section-heading"><div><h2>Your learning tools</h2><p>Everything you need to move from question to working code.</p></div></div>
    <section className="quick-grid"><Link className="quick-card" to="/documents"><div className="quick-card-top"><div className="quick-icon purple"><FileText/></div><span>01</span></div><h3>Course library</h3><p>Upload notes, slides, PDFs, or a YouTube lesson.</p><span>Manage resources <ArrowRight size={16}/></span></Link><Link className="quick-card featured" to="/tutor"><div className="quick-card-top"><div className="quick-icon orange"><BookOpen/></div><span>02</span></div><h3>Ask the tutor</h3><p>Get explanations grounded in selected course content.</p><span>Start a conversation <ArrowRight size={16}/></span></Link><Link className="quick-card" to="/workspace"><div className="quick-card-top"><div className="quick-icon blue"><Code2/></div><span>03</span></div><h3>Python lab</h3><p>Edit multiple files, run tests, and inspect diagnostics.</p><span>Open workspace <ArrowRight size={16}/></span></Link></section>
    <section className="dashboard-lower"><div className="recent-panel"><div className="section-heading"><div><h2>Recent conversations</h2><p>Continue a topic without losing context.</p></div><Link to="/tutor">View all</Link></div>{conversations.data?.length ? conversations.data.slice(0, 4).map(item => <Link to="/tutor" className="recent-row" key={item.id}><div><MessageSquareText/><span><strong>{item.title}</strong><small>{item.behavior.replace("_", " ")} · {item.difficulty}</small></span></div><time>{new Date(item.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</time></Link>) : <div className="recent-empty"><MessageSquareText/><span>Your tutor conversations will appear here.</span></div>}</div><div className="status-panel"><div className="section-heading"><div><h2>System status</h2><p>Live service availability.</p></div></div><div><Server/><span><strong>API service</strong><small>{health.data?.status ?? (health.isLoading ? "Checking…" : "Unavailable")}</small></span><i className={health.data ? "online" : "offline"}/></div><div><Database/><span><strong>PostgreSQL</strong><small>{ready.data?.status ?? (ready.isLoading ? "Checking…" : "Not ready")}</small></span><i className={ready.data?.status === "ready" ? "online" : "offline"}/></div></div></section>
  </div>;
}
