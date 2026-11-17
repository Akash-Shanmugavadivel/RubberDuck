import { useMutation, useQuery } from "@tanstack/react-query";
import { BookOpen, Bot, ChevronDown, Lightbulb, LoaderCircle, Send, UserRound } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api, errorMessage } from "../api/client";
import type { ChatMessage, Citation } from "../api/types";
import { EmptyState, PageHeader } from "../components/AppShell";

type DisplayMessage = ChatMessage & { citations?: Citation[]; grounded?: boolean };

export function TutorPage() {
  const documents = useQuery({ queryKey: ["documents"], queryFn: api.documents });
  const [selected, setSelected] = useState<string[]>([]);
  const [mode, setMode] = useState("programming_tutor");
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [hintProblem, setHintProblem] = useState("");
  const [hints, setHints] = useState<string[]>([]);
  const [error, setError] = useState("");
  const selectionInitialized = useRef(false);
  useEffect(() => {
    if (!documents.data) return;
    const available = new Set(documents.data.map(item => item.id));
    setSelected(current => selectionInitialized.current ? current.filter(id => available.has(id)) : [...available]);
    selectionInitialized.current = true;
  }, [documents.data]);
  const history = useMemo(() => messages.map(({ role, content }) => ({ role, content })), [messages]);
  const ask = useMutation({ mutationFn: (query: string) => api.tutor(query, mode, selected, history), onSuccess: result => { setMessages(value => [...value, { role: "assistant", content: result.answer, citations: result.citations, grounded: result.grounded }]); }, onError: reason => setError(errorMessage(reason)) });
  const hint = useMutation({ mutationFn: () => api.hint(hintProblem, history, hints), onSuccess: result => setHints(result.hints), onError: reason => setError(errorMessage(reason)) });

  function submit(event: FormEvent) { event.preventDefault(); const value = question.trim(); if (!value || !selected.length) return; setError(""); setMessages(items => [...items, { role: "user", content: value }]); setQuestion(""); ask.mutate(value); }
  function toggle(id: string) { setSelected(items => items.includes(id) ? items.filter(value => value !== id) : [...items, id]); }

  return <div className="page tutor-page"><PageHeader eyebrow="GROUNDED AI TUTOR" title="Ask, reason, and understand." description="Choose course resources and a learning style, then work through the idea together." action={<button className="secondary" onClick={() => { setMessages([]); setHints([]); setHintProblem(""); }}>Clear conversation</button>}/>
    <section className="tutor-controls"><label>Learning style<select value={mode} onChange={e => setMode(e.target.value)}><option value="programming_tutor">Programming tutor</option><option value="rubber_duck">Rubber duck assistant</option></select></label><div><span>Course context</span><div className="document-chips">{documents.data?.map(doc => <button className={selected.includes(doc.id) ? "selected" : ""} onClick={() => toggle(doc.id)} key={doc.id}>{doc.name}</button>)}</div></div></section>
    <section className="conversation">{messages.length === 0 ? <EmptyState icon={<Lightbulb/>} title="What would you like to understand?">Ask about a concept, paste an error, or request an explanation from your selected resources.</EmptyState> : messages.map((message, index) => <article className={`message ${message.role}`} key={index}><div className="avatar">{message.role === "user" ? <UserRound/> : <Bot/>}</div><div className="message-body"><div className="message-meta">{message.role === "user" ? "You" : "RubberDuck"}{message.role === "assistant" && <span className={message.grounded ? "grounded" : "ungrounded"}>{message.grounded ? "Grounded" : "No supporting evidence"}</span>}</div><p>{message.content}</p>{message.citations && message.citations.length > 0 && <details><summary><BookOpen size={16}/>Sources used <ChevronDown size={15}/></summary>{message.citations.map((citation, i) => <div className="citation" key={`${citation.chunk_id}-${i}`}><div><strong>[{i + 1}] {citation.source_uri ? <a href={citation.source_uri} target="_blank" rel="noreferrer">{citation.source_name}</a> : citation.source_name}</strong><span>{citation.location}</span></div><p>{citation.excerpt}</p><small>Chunk: {citation.chunk_id ?? "unknown"}{citation.score === null ? "" : ` · Relevance: ${citation.score.toFixed(3)}`}</small></div>)}</details>}</div></article>)}{ask.isPending && <div className="thinking"><LoaderCircle className="spin"/>Finding evidence and preparing an explanation…</div>}</section>
    {error && <div className="notice error">{error}</div>}
    <section className="hint-panel"><div className="hint-problem"><label htmlFor="hint-problem">Need a hint instead?</label><textarea id="hint-problem" rows={3} value={hintProblem} onChange={event => { setHintProblem(event.target.value); setHints([]); }} placeholder="Describe the problem, paste your code, and say where you are stuck…"/><button onClick={() => hint.mutate()} disabled={hint.isPending || !hintProblem.trim()}><Lightbulb/>{hint.isPending ? "Thinking…" : `Reveal hint ${hints.length + 1}`}</button></div>{hints.map((item, index) => <div className="hint" key={index}><strong>Hint {index + 1}</strong><p>{item}</p></div>)}</section>
    <form className="composer" onSubmit={submit}><textarea rows={2} value={question} onChange={e => setQuestion(e.target.value)} placeholder={selected.length ? "Ask a question about the selected material" : "Select at least one course resource"} disabled={!selected.length || ask.isPending} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }}/><button aria-label="Send question" disabled={!question.trim() || !selected.length || ask.isPending}><Send/></button></form>
  </div>;
}
