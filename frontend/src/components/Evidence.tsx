/**
 * The evidence panel — where a claim stops being a claim.
 *
 * `query_memory` returns prose, which is exactly what a reader is entitled to
 * distrust. This renders the raw ranked context instead: the same episodes the
 * answer was built from, the graph edges the narration flattens away, and —
 * the thing that matters — Reeve's own `(superseded)` marker on facts it knows
 * have been replaced.
 *
 * Everything here is set in mono on purpose. Mono means "this is the system's
 * output, not our writing", and the raw toggle is one click away because the
 * parser reads an internal rendering that carries no compatibility promise.
 */

import { useState } from "react";
import { ParsedContext } from "../api";

export function Evidence({ ctx }: { ctx: ParsedContext }) {
  const [showRaw, setShowRaw] = useState(false);

  if (ctx.empty && ctx.pending.length === 0) {
    return <p className="empty">Nothing in memory matched this question.</p>;
  }

  const superseded = ctx.episodes.flatMap((e) => e.states.filter((s) => s.superseded));

  return (
    <div>
      <div className="evidence-head">
        <span className="chip">{ctx.episodes.length} episodes</span>
        {superseded.length > 0 && (
          <span className="chip">{superseded.length} superseded</span>
        )}
        {ctx.pending.length > 0 && (
          <span className="chip">{ctx.pending.length} settling</span>
        )}
        <button className="ghost spacer" onClick={() => setShowRaw((v) => !v)}>
          {showRaw ? "Hide raw" : "View raw"}
        </button>
      </div>

      {ctx.pending.length > 0 && (
        <div className="caveat">
          <strong>Still settling.</strong> Part of this answer comes from memories
          Reeve has accepted but not yet indexed:
          <ul style={{ margin: "6px 0 0", paddingLeft: "18px" }}>
            {ctx.pending.map((p, i) => (
              <li key={i} style={{ fontSize: "13px" }}>{p}</li>
            ))}
          </ul>
        </div>
      )}

      {ctx.episodes.map((ep, i) => (
        <div className="episode" key={i}>
          <div className="ts">
            {ep.timestamp}
            {ep.importance !== null && ` · importance ${ep.importance}`}
            {ep.emotion && ` · ${ep.emotion}`}
          </div>
          <p className="text">{ep.display}</p>

          {ep.entities.length > 0 && (
            <div className="fact">
              <span className="label">who</span>
              <span className="value">{ep.entities.join(", ")}</span>
            </div>
          )}
          {ep.actions.map((a, j) => (
            <div className="fact" key={`a${j}`}>
              <span className="label">did</span>
              <span className="value">
                {a.actor} {a.verb}
                {a.object ? ` → ${a.object}` : ""}
              </span>
            </div>
          ))}
          {ep.relations.map((r, j) => (
            <div className="fact" key={`r${j}`}>
              <span className="label">relation</span>
              <span className="value">{r.subject} {r.relation} {r.object}</span>
            </div>
          ))}
          {ep.states.map((s, j) => (
            <div className={`fact ${s.superseded ? "superseded" : ""}`} key={`s${j}`}>
              <span className="label">state</span>
              <span className="value">
                {s.entity}.{s.attribute} = {s.value}
              </span>
              {s.superseded && <span className="tag">superseded</span>}
            </div>
          ))}
          {ep.locations.length > 0 && (
            <div className="fact">
              <span className="label">where</span>
              <span className="value">{ep.locations.join(", ")}</span>
            </div>
          )}
        </div>
      ))}

      {Object.keys(ctx.roles).length > 0 && (
        <div style={{ marginTop: "var(--s4)" }}>
          {Object.entries(ctx.roles).map(([entity, role]) => (
            <div className="fact" key={entity}>
              <span className="label">role</span>
              <span className="value">{entity} → {role}</span>
            </div>
          ))}
        </div>
      )}

      {showRaw && <pre className="raw">{ctx.raw}</pre>}
    </div>
  );
}
