import { BrainCircuit } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { errorMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export function AuthPage({ register = false }: { register?: boolean }) {
  const { user, login, register: createAccount } = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { register ? await createAccount(email, password) : await login(email, password); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  }

  return <div className="auth-layout">
    <section className="auth-story"><div className="brand auth-brand"><div className="brand-mark">⌁</div><div><strong>RubberDuck</strong><span>AI learning workspace</span></div></div><div><p className="eyebrow">YOUR AI PYTHON CLASSROOM</p><h1>Learn by asking,<br/>testing, and debugging.</h1><p>Grounded course answers, progressive hints, and isolated Python execution in one focused workspace.</p></div><div className="feature-pills"><span>Evidence-backed</span><span>Safe execution</span><span>Progressive hints</span></div></section>
    <main className="auth-panel"><form className="auth-card" onSubmit={submit}><BrainCircuit className="auth-icon"/><p className="eyebrow">{register ? "GET STARTED" : "WELCOME BACK"}</p><h2>{register ? "Create your account" : "Sign in to your classroom"}</h2><p className="muted">{register ? "Use an email and a password with at least 8 characters." : "Continue learning where you left off."}</p>{location.state?.message && <div className="notice success">{location.state.message}</div>}{error && <div className="notice error" role="alert">{error}</div>}<label>Email<input type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="student@college.edu"/></label><label>Password<input type="password" autoComplete={register ? "new-password" : "current-password"} required minLength={8} value={password} onChange={e => setPassword(e.target.value)} placeholder="At least 8 characters"/></label><button className="primary full" disabled={busy}>{busy ? "Please wait…" : register ? "Create account" : "Sign in"}</button><p className="auth-switch">{register ? "Already have an account?" : "New to RubberDuck?"} <Link to={register ? "/login" : "/register"}>{register ? "Sign in" : "Create one"}</Link></p></form></main>
  </div>;
}
