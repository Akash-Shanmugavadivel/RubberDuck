import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/AppShell";

export function TutorPolicyPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const policy = useQuery({ queryKey: ["tutor-policy"], queryFn: api.tutorPolicy });
  const [directAnswers, setDirectAnswers] = useState(true);
  const [codeSolutions, setCodeSolutions] = useState(true);
  const [hintsOnly, setHintsOnly] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!policy.data) return;
    setDirectAnswers(policy.data.allow_direct_answers);
    setCodeSolutions(policy.data.allow_code_solutions);
    setHintsOnly(policy.data.hints_only);
  }, [policy.data]);

  const save = useMutation({
    mutationFn: () => api.updateTutorPolicy({
      allow_direct_answers: hintsOnly ? false : directAnswers,
      allow_code_solutions: hintsOnly ? false : codeSolutions,
      hints_only: hintsOnly,
    }),
    onSuccess: result => {
      queryClient.setQueryData(["tutor-policy"], result);
      setMessage("Tutor assistance policy updated.");
      setError("");
    },
    onError: reason => {
      setError(errorMessage(reason));
      setMessage("");
    },
  });

  if (user?.role !== "instructor") return <Navigate to="/" replace/>;

  return <div className="page">
    <PageHeader eyebrow="INSTRUCTOR CONTROLS" title="Tutor assistance policy" description="Set the maximum help RubberDuck may provide to every student. Teaching behavior choices can never bypass these limits."/>
    <section className="policy-card">
      <div className="policy-heading"><ShieldCheck/><div><h2>Allowed assistance</h2><p>Changes apply to new tutor responses immediately.</p></div></div>
      <label className="policy-option"><input type="checkbox" checked={hintsOnly} onChange={event => setHintsOnly(event.target.checked)}/><span><strong>Hints only</strong><small>Never reveal direct answers or complete solutions.</small></span></label>
      <label className="policy-option"><input type="checkbox" checked={directAnswers} disabled={hintsOnly} onChange={event => setDirectAnswers(event.target.checked)}/><span><strong>Allow direct explanations</strong><small>Explain the answer directly when the student selects Explain mode.</small></span></label>
      <label className="policy-option"><input type="checkbox" checked={codeSolutions} disabled={hintsOnly} onChange={event => setCodeSolutions(event.target.checked)}/><span><strong>Allow complete code solutions</strong><small>Permit ready-to-run solutions instead of pseudocode and small fragments.</small></span></label>
      {message && <div className="notice success">{message}</div>}
      {error && <div className="notice error">{error}</div>}
      <button className="primary policy-save" disabled={save.isPending || policy.isLoading} onClick={() => save.mutate()}><Save size={17}/>{save.isPending ? "Saving…" : "Save policy"}</button>
    </section>
  </div>;
}
