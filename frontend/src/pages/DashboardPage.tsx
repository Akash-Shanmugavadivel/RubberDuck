import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BookOpen, CheckCircle2, Code2, Database, FileText, Server } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { PageHeader } from "../components/AppShell";

export function DashboardPage() {
  const documents = useQuery({ queryKey: ["documents"], queryFn: api.documents });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  const ready = useQuery({ queryKey: ["readiness"], queryFn: api.readiness, retry: false, refetchInterval: 30_000 });
  const resourceCount = documents.data?.length ?? 0;
  return <div className="page"><PageHeader eyebrow="YOUR AI PYTHON CLASSROOM" title="Learn by asking, testing, and debugging." description="Use trusted course materials, progressive hints, and a secure Python workspace."/>
    <section className="hero-card"><div><span className="status-dot"/>Tutor ready</div><strong>{resourceCount} indexed {resourceCount === 1 ? "resource" : "resources"}</strong><span>Evidence-backed answers</span><Code2 className="hero-watermark"/></section>
    <div className="section-heading"><div><h2>Continue learning</h2><p>Choose the tool that matches what you need to do.</p></div></div>
    <section className="quick-grid"><Link className="quick-card" to="/documents"><div className="quick-icon purple"><FileText/></div><h3>Course library</h3><p>Upload notes, slides, PDFs, or a YouTube lesson.</p><span>Manage resources <ArrowRight size={16}/></span></Link><Link className="quick-card" to="/tutor"><div className="quick-icon orange"><BookOpen/></div><h3>Ask the tutor</h3><p>Get explanations grounded in selected course content.</p><span>Start a conversation <ArrowRight size={16}/></span></Link><Link className="quick-card" to="/workspace"><div className="quick-icon blue"><Code2/></div><h3>Python lab</h3><p>Edit multiple files, run tests, and inspect diagnostics.</p><span>Open workspace <ArrowRight size={16}/></span></Link></section>
    <section className="system-strip"><div><Server/><span><strong>API</strong>{health.data?.status ?? (health.isLoading ? "Checking…" : "Unavailable")}</span>{health.data && <CheckCircle2 className="ok"/>}</div><div><Database/><span><strong>Database</strong>{ready.data?.status ?? (ready.isLoading ? "Checking…" : "Not ready")}</span>{ready.data?.status === "ready" && <CheckCircle2 className="ok"/>}</div></section>
  </div>;
}
