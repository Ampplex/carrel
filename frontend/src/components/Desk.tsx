/**
 * Capture and ask — the everyday surface.
 *
 * The capture box has no edit button, and says so. Restating something IS the
 * edit: Reeve keeps both versions with their times, which is the behaviour the
 * whole project is about. An edit button would destroy the history that makes
 * "when was it originally due?" answerable.
 *
 * Evidence is fetched lazily, and that is a measured decision rather than a
 * stylistic one. Bundling it into the ask meant every question paid for two
 * sequential round trips — 28 seconds end to end — even though most answers are
 * simply read and accepted. Asking first and fetching the receipts only when
 * someone wants them roughly halves the wait and spends the second query only
 * when it is actually going to be looked at.
 */

import { useEffect, useRef, useState } from "react";
import { ApiError, Answer, ParsedContext, PendingWrite, api } from "../api";
import { Evidence } from "./Evidence";

export function Desk({
  onWrite,
  unsettled,
}: {
  onWrite: (pending: PendingWrite[]) => void;
  unsettled: number;
}) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedNote, setSavedNote] = useState("");

  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [evidence, setEvidence] = useState<ParsedContext | null>(null);
  const [loadingEvidence, setLoadingEvidence] = useState(false);

  // Answers take tens of seconds — a spinner with no number reads as "stuck".
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef(0);
  useEffect(() => {
    if (!asking && !loadingEvidence) return;
    startedAt.current = Date.now();
    setElapsed(0);
    const timer = setInterval(
      () => setElapsed(Math.round((Date.now() - startedAt.current) / 1000)),
      1000
    );
    return () => clearInterval(timer);
  }, [asking, loadingEvidence]);

  const capture = async () => {
    if (!text.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const result = await api.storeNote(text);
      onWrite(result.pending);
      setSavedNote(
        result.chunked
          ? `Stored as ${result.pending.length} memories — long notes are split so one fact does not get diluted by the rest.`
          : "Stored."
      );
      setText("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const ask = async () => {
    if (!question.trim()) return;
    setAsking(true);
    setError(null);
    setEvidence(null);
    try {
      setAnswer(await api.ask(question, false));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setAnswer(null);
    } finally {
      setAsking(false);
    }
  };

  const showEvidence = async () => {
    setLoadingEvidence(true);
    setError(null);
    try {
      setEvidence((await api.context(question)).parsed);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoadingEvidence(false);
    }
  };

  return (
    <>
      <section className="card">
        <h2>Remember this</h2>
        <p className="hint">
          A lecture, a decision, a deadline, who is doing what. To correct
          something later, just say the new version — there is no edit button,
          because replacing a fact is something the memory should record, not
          something it should forget.
        </p>
        <textarea
          rows={3}
          value={text}
          placeholder="The DSP mini-project report deadline is now 19 November."
          onChange={(e) => setText(e.target.value)}
        />
        <div className="row" style={{ marginTop: "0.6rem" }}>
          <button className="primary" onClick={capture} disabled={saving || !text.trim()}>
            {saving ? "Storing…" : "Remember this"}
          </button>
          {savedNote && <span className="hint" style={{ margin: 0 }}>{savedNote}</span>}
        </div>
      </section>

      <section className="card">
        <h2>Ask</h2>
        <textarea
          rows={2}
          value={question}
          placeholder="When is the DSP report due?"
          onChange={(e) => setQuestion(e.target.value)}
        />
        <div className="row" style={{ marginTop: "0.6rem" }}>
          <button className="primary" onClick={ask} disabled={asking || !question.trim()}>
            {asking ? `Thinking… ${elapsed}s` : "Ask · 1 query"}
          </button>
          <span className="hint" style={{ margin: 0 }}>
            Answers usually take 10–30 seconds.
          </span>
        </div>
      </section>

      {error && <div className="error">{error}</div>}

      {answer && (
        <section className="card answer-card">
          {unsettled > 0 && (
            <div className="caveat">
              {unsettled} {unsettled === 1 ? "memory is" : "memories are"} still
              settling. This answer may not include {unsettled === 1 ? "it" : "them"} yet.
            </div>
          )}
          <p className="question-echo">{question}</p>
          <p className="answer">{answer.answer}</p>
          <div className="meta">
            <span>{answer.queries_used} quer{answer.queries_used === 1 ? "y" : "ies"}</span>
            <span>{(answer.took_ms / 1000).toFixed(1)}s</span>
          </div>

          {!evidence && (
            <div className="row" style={{ marginTop: "0.8rem" }}>
              <button onClick={showEvidence} disabled={loadingEvidence}>
                {loadingEvidence ? `Fetching… ${elapsed}s` : "Show the evidence · 1 query"}
              </button>
              <span className="hint" style={{ margin: 0 }}>
                The ranked memories this answer was built from.
              </span>
            </div>
          )}

          {evidence && (
            <div style={{ marginTop: "1rem", borderTop: "1px solid var(--border)", paddingTop: "0.8rem" }}>
              <Evidence ctx={evidence} />
            </div>
          )}
        </section>
      )}
    </>
  );
}
