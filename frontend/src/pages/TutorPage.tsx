import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, BookOpen, Bot, Edit3, History, Lightbulb, LoaderCircle, Pin, PinOff, Plus, RefreshCw, Search, Send, Square, StickyNote, Trash2, UserRound } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api, errorMessage } from "../api/client";
import type { ChatMessage, Citation, ConversationSummary, TeachingBehavior, TutorDifficulty } from "../api/types";
import { EmptyState, PageHeader } from "../components/AppShell";
import { MarkdownMessage } from "../components/MarkdownMessage";

type DisplayMessage = ChatMessage & { id?: string; citations?: Citation[]; grounded?: boolean | null };

function dateLabel(value: string) {
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return "Today";
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function TutorPage() {
  const queryClient = useQueryClient();
  const documents = useQuery({ queryKey: ["documents"], queryFn: api.documents });
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.conversations });
  const policy = useQuery({ queryKey: ["tutor-policy"], queryFn: api.tutorPolicy });
  const notes = useQuery({ queryKey: ["notes"], queryFn: api.notes });
  const [conversationId, setConversationId] = useState<string | null>(null);
  const conversation = useQuery({ queryKey: ["conversation", conversationId], queryFn: () => api.conversation(conversationId!), enabled: Boolean(conversationId) });
  const [selected, setSelected] = useState<string[]>([]);
  const [behavior, setBehavior] = useState<TeachingBehavior>("explain");
  const [difficulty, setDifficulty] = useState<TutorDifficulty>("intermediate");
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [historySearch, setHistorySearch] = useState("");
  const [hintProblem, setHintProblem] = useState("");
  const [hints, setHints] = useState<string[]>([]);
  const [previewCitation, setPreviewCitation] = useState<Citation | null>(null);
  const [error, setError] = useState("");
  const selectionInitialized = useRef(false);
  const abortController = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!documents.data) return;
    const available = new Set(documents.data.map(item => item.id));
    setSelected(current => selectionInitialized.current ? current.filter(id => available.has(id)) : [...available]);
    selectionInitialized.current = true;
  }, [documents.data]);

  useEffect(() => {
    if (!conversation.data || !documents.data) return;
    const available = new Set(documents.data.map(item => item.id));
    setBehavior(conversation.data.behavior);
    setDifficulty(conversation.data.difficulty);
    setSelected(conversation.data.document_ids.filter(id => available.has(id)));
    setMessages(conversation.data.messages.map(message => ({ id: message.id, role: message.role, content: message.content, citations: message.citations, grounded: message.grounded })));
    setHints([]); setHintProblem(""); setPreviewCitation(null);
  }, [conversation.data, documents.data]);

  useEffect(() => { if (typeof endRef.current?.scrollIntoView === "function") endRef.current.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages, hints]);

  const history = useMemo(() => messages.map(({ role, content }) => ({ role, content })), [messages]);
  const mode = behavior === "socratic" ? "rubber_duck" : "programming_tutor";
  const filteredConversations = useMemo(() => (conversations.data ?? []).filter(item => item.title.toLowerCase().includes(historySearch.toLowerCase())), [conversations.data, historySearch]);
  const groupedConversations = useMemo(() => {
    const documentNames = new Map((documents.data ?? []).map(item => [item.id, item.name]));
    return filteredConversations.reduce<Record<string, ConversationSummary[]>>((groups, item) => {
      const material = item.document_ids.map(id => documentNames.get(id)).filter(Boolean).join(", ") || "Unavailable material";
      const key = `${dateLabel(item.updated_at)} · ${material}`;
      (groups[key] ??= []).push(item);
      return groups;
    }, {});
  }, [filteredConversations, documents.data]);

  const ask = useMutation({
    mutationFn: (query: string) => {
      abortController.current = new AbortController();
      return api.tutor(query, mode, selected, history, conversationId, behavior, difficulty, abortController.current.signal);
    },
    onSuccess: result => {
      setConversationId(result.conversation_id);
      setMessages(value => [...value, { role: "assistant", content: result.answer, citations: result.citations, grounded: result.grounded }]);
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      void queryClient.invalidateQueries({ queryKey: ["conversation", result.conversation_id] });
    },
    onError: reason => { if ((reason as Error).name === "AbortError") { setError("Generation stopped in this browser. Refresh history shortly in case the provider already completed the response."); window.setTimeout(() => void queryClient.invalidateQueries({ queryKey: ["conversations"] }), 2000); } else setError(errorMessage(reason)); },
    onSettled: () => { abortController.current = null; },
  });
  const regenerate = useMutation({
    mutationFn: () => api.regenerate(conversationId!),
    onSuccess: result => { setMessages(items => [...items.slice(0, -1), { role: "assistant", content: result.answer, citations: result.citations, grounded: result.grounded }]); void queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] }); },
    onError: reason => setError(errorMessage(reason)),
  });
  const hint = useMutation({ mutationFn: () => api.hint(hintProblem, history, hints), onSuccess: result => setHints(result.hints), onError: reason => setError(errorMessage(reason)) });
  const removeConversation = useMutation({ mutationFn: (id: string) => api.deleteConversation(id), onSuccess: () => { startNewConversation(); void queryClient.invalidateQueries({ queryKey: ["conversations"] }); }, onError: reason => setError(errorMessage(reason)) });
  const saveConversation = useMutation({ mutationFn: ({ id, update }: { id: string; update: { title?: string; pinned?: boolean } }) => api.updateConversation(id, update), onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["conversations"] }), onError: reason => setError(errorMessage(reason)) });
  const saveNote = useMutation({ mutationFn: api.createNote, onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notes"] }), onError: reason => setError(errorMessage(reason)) });
  const removeNote = useMutation({ mutationFn: api.deleteNote, onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notes"] }), onError: reason => setError(errorMessage(reason)) });

  function startNewConversation() { setConversationId(null); setMessages([]); setHints([]); setHintProblem(""); setPreviewCitation(null); setError(""); }
  function submit(event: FormEvent) { event.preventDefault(); const value = question.trim(); if (!value || !selected.length) return; setError(""); setMessages(items => [...items, { role: "user", content: value }]); setQuestion(""); ask.mutate(value); }
  function toggle(id: string) { setSelected(items => items.includes(id) ? items.filter(value => value !== id) : [...items, id]); }
  function rename(item: ConversationSummary) { const title = window.prompt("Conversation title", item.title)?.trim(); if (title && title !== item.title) saveConversation.mutate({ id: item.id, update: { title } }); }
  function storeMessage(message: DisplayMessage) { saveNote.mutate({ kind: "note", title: message.content.slice(0, 70), content: message.content, conversation_id: conversationId, message_id: message.id ?? null, citations: message.citations ?? [] }); }
  function bookmark(citation: Citation) { saveNote.mutate({ kind: "bookmark", title: citation.source_name, content: citation.excerpt, conversation_id: conversationId, message_id: null, citations: [citation] }); }

  return <div className="page tutor-page">
    <PageHeader eyebrow="GROUNDED AI TUTOR" title="Ask, reason, and understand." description="Learn from trusted material, save useful explanations, and continue any conversation." action={<button className="secondary" onClick={startNewConversation}><Plus size={17}/>New conversation</button>}/>
    <section className="history-browser"><div className="history-title"><History size={18}/><strong>Conversation history</strong></div><label className="history-search"><Search size={16}/><input aria-label="Search conversations" value={historySearch} onChange={event => setHistorySearch(event.target.value)} placeholder="Search history…"/></label><div className="history-groups">{Object.entries(groupedConversations).map(([group, items]) => <div key={group}><small>{group}</small>{items.map(item => <div className={`history-item ${item.id === conversationId ? "active" : ""}`} key={item.id}><button onClick={() => setConversationId(item.id)}>{item.pinned && <Pin size={13}/>}<span>{item.title}</span></button><button title="Rename" onClick={() => rename(item)}><Edit3 size={14}/></button><button title={item.pinned ? "Unpin" : "Pin"} onClick={() => saveConversation.mutate({ id: item.id, update: { pinned: !item.pinned } })}>{item.pinned ? <PinOff size={14}/> : <Pin size={14}/>}</button></div>)}</div>)}{filteredConversations.length === 0 && <span className="muted">No matching conversations.</span>}</div></section>
    <section className="conversation-actions">{conversationId && <><button className="secondary" onClick={() => regenerate.mutate()} disabled={ask.isPending || regenerate.isPending}><RefreshCw size={15}/>{regenerate.isPending ? "Regenerating…" : "Regenerate"}</button><button className="danger-button" onClick={() => removeConversation.mutate(conversationId)}><Trash2 size={15}/>Delete conversation</button></>}</section>
    <section className="tutor-controls"><label>Teaching behavior<select value={behavior} onChange={e => setBehavior(e.target.value as TeachingBehavior)}><option value="socratic">Socratic questions</option><option value="explain">Direct explanation</option><option value="exam_prep">Exam preparation</option><option value="debug_coach">Debug coach</option></select></label><label>Difficulty<select value={difficulty} onChange={e => setDifficulty(e.target.value as TutorDifficulty)}><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label><div><span>Course material</span><div className="document-chips">{documents.data?.map(doc => <button className={selected.includes(doc.id) ? "selected" : ""} onClick={() => toggle(doc.id)} key={doc.id}>{doc.name}</button>)}</div></div></section>
    {policy.data && (!policy.data.allow_direct_answers || !policy.data.allow_code_solutions || policy.data.hints_only) && <div className="notice policy-notice"><strong>Instructor assistance policy:</strong> {policy.data.hints_only ? "Hints only" : policy.data.allow_direct_answers ? "Guided answers" : "No direct answers"}{!policy.data.allow_code_solutions && " · Complete code solutions disabled"}</div>}
    {conversation.isLoading ? <div className="thinking"><LoaderCircle className="spin"/>Loading conversation…</div> : <section className="conversation">{messages.length === 0 ? <EmptyState icon={<Lightbulb/>} title="What would you like to understand?">Ask about a concept, paste an error, or request an explanation from your selected resources.</EmptyState> : messages.map((message, index) => <article className={`message ${message.role}`} key={message.id ?? index}><div className="avatar">{message.role === "user" ? <UserRound/> : <Bot/>}</div><div className="message-body"><div className="message-meta">{message.role === "user" ? "You" : "RubberDuck"}{message.role === "assistant" && <span className={message.grounded ? "grounded" : "ungrounded"}>{message.grounded ? "Grounded" : "Insufficient evidence"}</span>}</div>{message.role === "assistant" && message.grounded === false && <div className="evidence-warning">The selected material does not contain enough evidence for a reliable answer.</div>}<MarkdownMessage>{message.content}</MarkdownMessage>{message.role === "assistant" && <button className="message-tool" onClick={() => storeMessage(message)}><StickyNote size={14}/>Save as note</button>}{message.citations && message.citations.length > 0 && <div className="citation-list"><strong><BookOpen size={15}/>Sources used</strong>{message.citations.map((citation, i) => <button onClick={() => setPreviewCitation(citation)} key={`${citation.chunk_id}-${i}`}>[{i + 1}] {citation.source_name}</button>)}</div>}</div></article>)}{ask.isPending && <div className="thinking"><LoaderCircle className="spin"/>Finding evidence and preparing an explanation… <button className="danger-button" onClick={() => abortController.current?.abort()}><Square size={14}/>Stop</button></div>}<div ref={endRef}/></section>}
    {previewCitation && <aside className="citation-preview"><div><strong>{previewCitation.source_name}</strong><button onClick={() => setPreviewCitation(null)}>×</button></div><span>{previewCitation.location}</span><p>{previewCitation.excerpt}</p><button className="secondary" onClick={() => bookmark(previewCitation)}><Bookmark size={15}/>Bookmark source</button></aside>}
    {error && <div className="notice error">{error}</div>}
    <section className="saved-notes"><h2><StickyNote/>Saved notes and bookmarks</h2>{notes.data?.length ? notes.data.map(note => <article key={note.id}><span>{note.kind === "bookmark" ? <Bookmark/> : <StickyNote/>}</span><div><strong>{note.title}</strong><MarkdownMessage>{note.content}</MarkdownMessage></div><button aria-label={`Delete ${note.title}`} onClick={() => removeNote.mutate(note.id)}><Trash2/></button></article>) : <p className="muted">Save an explanation or bookmark a citation to find it here.</p>}</section>
    <section className="hint-panel"><div className="hint-problem"><label htmlFor="hint-problem">Need a hint instead?</label><textarea id="hint-problem" rows={3} value={hintProblem} onChange={event => { setHintProblem(event.target.value); setHints([]); }} placeholder="Describe the problem, paste your code, and say where you are stuck…"/><button onClick={() => hint.mutate()} disabled={hint.isPending || !hintProblem.trim()}><Lightbulb/>{hint.isPending ? "Thinking…" : `Reveal hint ${hints.length + 1}`}</button></div>{hints.map((item, index) => <div className="hint" key={index}><strong>Hint {index + 1}</strong><MarkdownMessage>{item}</MarkdownMessage></div>)}</section>
    <form className="composer" onSubmit={submit}><textarea rows={2} value={question} onChange={e => setQuestion(e.target.value)} placeholder={selected.length ? "Ask a question about the selected material" : "Select at least one course resource"} disabled={!selected.length || ask.isPending || conversation.isLoading} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }}/><button aria-label="Send question" disabled={!question.trim() || !selected.length || ask.isPending || conversation.isLoading}><Send/></button></form>
  </div>;
}
