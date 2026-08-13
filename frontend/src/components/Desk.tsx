/**
 * Capture and ask — the everyday surface.
 *
 * The capture box has no edit button, and says so. Restating something IS the
 * edit: Reeve marks the previous fact superseded and keeps both, which is the
 * behaviour the whole project is about. An edit button would quietly destroy the
 * history that makes "when was it originally due?" answerable.
 */

import { useState } from "react";
import { ApiError, Answer, PendingWrite, api } from "../api";
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

  const ask = async (withEvidence: boolean) => {
    if (!question.trim()) return;
    setAsking(true);
    setError(null);
    try {
      setAnswer(await api.ask(question, withEvidence));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setAnswer(null);
    } finally {
      setAsking(false);
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
          placeholder="Prof. Nair moved the DSP mini-project report deadline to 19 November."
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
          <button className="primary" onClick={() => ask(false)} disabled={asking || !question.trim()}>
            Ask · 1 query
          </button>
          <button onClick={() => ask(true)} disabled={asking || !question.trim()}>
            Ask + show evidence · 2 queries
          </button>
          {asking && <span className="hint" style={{ margin: 0 }}>Thinking…</span>}
        </div>
        <p className="hint" style={{ marginTop: "0.5rem" }}>
          The cost is on the button on purpose. Evidence mode makes a second call
          to fetch the raw retrieval context behind the answer.
        </p>
      </section>

      {error && <div className="error">{error}</div>}

      {answer && (
        <section className="card">
          {unsettled > 0 && (
            <div className="caveat">
              {unsettled} {unsettled === 1 ? "memory is" : "memories are"} still
              settling. This answer may not include {unsettled === 1 ? "it" : "them"} yet.
            </div>
          )}
          <p className="answer">{answer.answer}</p>
          <div className="meta">
            {answer.queries_used} quer{answer.queries_used === 1 ? "y" : "ies"} · {answer.took_ms} ms
          </div>
          {answer.evidence && (
            <div style={{ marginTop: "1rem", borderTop: "1px solid var(--border)", paddingTop: "0.8rem" }}>
              <Evidence ctx={answer.evidence} />
            </div>
          )}
        </section>
      )}
    </>
  );
}
