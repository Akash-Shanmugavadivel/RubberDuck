import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, File, FileUp, Link2, LoaderCircle, Search, Trash2, Youtube } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api, errorMessage } from "../api/client";
import type { IngestionJob } from "../api/types";
import { EmptyState, PageHeader } from "../components/AppShell";

const terminal = new Set(["completed", "failed", "cancelled", "timed_out"]);

export function DocumentsPage() {
  const client = useQueryClient();
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [youtube, setYoutube] = useState("");
  const [languages, setLanguages] = useState("en");
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const documents = useQuery({ queryKey: ["documents"], queryFn: api.documents });
  const filteredDocuments = documents.data?.filter(document => document.name.toLowerCase().includes(search.toLowerCase()));
  const hasActiveJobs = jobs.some(job => !terminal.has(job.state));
  useEffect(() => {
    if (!hasActiveJobs) return;
    const timer = window.setInterval(() => {
      const active = jobs.filter(job => !terminal.has(job.state));
      void Promise.allSettled(active.map(job => api.ingestionJob(job.id))).then(results => {
        const updates = results.flatMap(result => result.status === "fulfilled" ? [result.value] : []);
        const failures = results.flatMap(result => result.status === "rejected" ? [errorMessage(result.reason)] : []);
        setJobs(current => current.map(job => updates.find(update => update.id === job.id) ?? job));
        if (updates.some(job => job.state === "completed")) void client.invalidateQueries({ queryKey: ["documents"] });
        if (failures.length) setError(`Could not refresh one or more ingestion jobs: ${failures.join(" · ")}`);
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [client, hasActiveJobs, jobs]);
  const upload = useMutation({ mutationFn: async (files: File[]) => {
    const results = await Promise.allSettled(files.map(api.upload));
    return {
      jobs: results.flatMap(result => result.status === "fulfilled" ? [result.value] : []),
      failures: results.flatMap((result, index) => result.status === "rejected" ? [`${files[index].name}: ${errorMessage(result.reason)}`] : []),
    };
  }, onSuccess: result => { setJobs(current => [...result.jobs, ...current]); if (result.failures.length) setError(result.failures.join(" · ")); }, onError: e => setError(errorMessage(e)) });
  const addVideo = useMutation({ mutationFn: (reference: string) => api.addYouTube(reference, languages.split(",").map(value => value.trim()).filter(Boolean)), onSuccess: value => { setJobs(current => [value, ...current]); setYoutube(""); }, onError: e => setError(errorMessage(e)) });
  const remove = useMutation({ mutationFn: api.deleteDocument, onSuccess: () => client.invalidateQueries({ queryKey: ["documents"] }), onError: e => setError(errorMessage(e)) });

  function chooseFile(event: React.ChangeEvent<HTMLInputElement>) { const files = Array.from(event.target.files ?? []); if (files.length) { setError(""); upload.mutate(files); } event.target.value = ""; }
  function submitVideo(event: FormEvent) { event.preventDefault(); if (youtube.trim()) { setError(""); addVideo.mutate(youtube.trim()); } }

  return <div className="page"><PageHeader eyebrow="COURSE LIBRARY" title="Ground answers in trusted material." description="Add course documents or video transcripts. Every answer can trace back to its source." action={<label className="primary upload-button"><FileUp size={18}/>Upload files<input multiple type="file" accept=".pdf,.txt,.csv,.pptx,.md,.rst" onChange={chooseFile}/></label>}/>
    {error && <div className="notice error">{error}</div>}
    {jobs.length > 0 && <section className="job-list"><div className="job-list-heading"><strong>Ingestion activity · {jobs.length}</strong>{jobs.some(job => terminal.has(job.state)) && <button className="text-button" onClick={() => setJobs(current => current.filter(job => !terminal.has(job.state)))}>Clear finished</button>}</div>{jobs.map(job => <div className={`job-banner ${job.state}`} key={job.id}><div>{terminal.has(job.state) ? <CheckCircle2/> : <LoaderCircle className="spin"/>}<span><strong>{job.message}</strong><small>{Math.round(job.progress * 100)}% · attempt {job.attempt}/{job.max_attempts}{job.error ? ` · ${job.error}` : ""}</small></span></div><div className="progress"><span style={{ width: `${job.progress * 100}%` }}/></div>{!terminal.has(job.state) && <button className="text-button" onClick={() => api.cancelIngestion(job.id).then(update => setJobs(current => current.map(item => item.id === update.id ? update : item)))}>Cancel</button>}</div>)}</section>}
    <section className="youtube-card"><div><div className="quick-icon red"><Youtube/></div><span><h3>Add a video lesson</h3><p>Index a YouTube transcript alongside your documents.</p></span></div><form onSubmit={submitVideo}><Link2 size={18}/><input value={youtube} onChange={e => setYoutube(e.target.value)} placeholder="YouTube URL or video ID" aria-label="YouTube URL"/><input className="language-input" value={languages} onChange={e => setLanguages(e.target.value)} placeholder="en,ta,hi" aria-label="Preferred transcript languages"/><button disabled={addVideo.isPending || !languages.trim()}>Add lesson</button></form></section>
    <div className="section-heading resource-heading"><div><h2>Indexed resources</h2><p>{documents.data?.length ?? 0} available to your tutor</p></div><label className="resource-search"><Search/><input aria-label="Search resources" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search materials…"/></label></div>
    {documents.isLoading ? <div className="loading-row"><LoaderCircle className="spin"/>Loading resources…</div> : filteredDocuments?.length ? <div className="resource-list">{filteredDocuments.map(document => <article key={document.id} className="resource-row"><div className="file-icon"><File/></div><div><h3>{document.name}</h3><p>{document.source_type} · {document.media_type} · index {document.index_version}</p></div><span className="indexed"><CheckCircle2/>Indexed</span><button className="icon-button danger" title="Delete resource" aria-label={`Delete ${document.name}`} disabled={remove.isPending} onClick={() => { if (confirm(`Delete ${document.name}?`)) remove.mutate(document.id); }}><Trash2/></button></article>)}</div> : documents.data?.length ? <EmptyState icon={<Search/>} title="No matching resources">Try a different search term.</EmptyState> : <EmptyState icon={<FileTextIcon/>} title="No resources yet">Upload a course file or add a video transcript to begin.</EmptyState>}
  </div>;
}

function FileTextIcon() { return <File size={30}/>; }
