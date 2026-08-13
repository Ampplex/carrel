/**
 * The evidence panel — where a claim stops being a claim.
 *
 * `query_memory` returns prose, which is exactly what an examiner is entitled to
 * distrust. This panel renders the raw ranked context instead: the same episodes
 * the answer was built from, with the graph edges the narration flattens away,
 * and — the thing that matters — Reeve's own `(superseded)` marker on facts it
 * knows have been replaced.
 *
 * The raw toggle is not a debug affordance. The parser reads an internal
 * rendering that carries no compatibility promise, so the untouched string stays
 * one click away, always.
 */

import { useState } from "react";
import { ParsedContext } from "../api";

export function Evidence({ ctx }: { ctx: ParsedContext }) {
  const [showRaw, setShowRaw] = useState(false);

  if (ctx.empty && ctx.pending.length === 0) {
    return <p className="hint">Nothing in memory matched this question.</p>;
  }

  const superseded = ctx.episodes.flatMap((e) => e.states.filter((s) => s.superseded));

  return (
    <div>
      <div className="row" style={{ marginBottom: "0.6rem" }}>
        <span className="chip">{ctx.episodes.length} episodes</span>
        {superseded.length > 0 && (
          <span className="chip">{superseded.length} superseded fact(s)</span>
        )}
        {ctx.pending.length > 0 && (
          <span className="chip">{ctx.pending.length} not yet indexed</span>
        )}
        <button className="grow" style={{ flex: "0 0 auto", marginLeft: "auto" }} onClick={() => setShowRaw((v) => !v)}>
          {showRaw ? "Hide" : "Show"} raw context
        </button>
      </div>

      {ctx.pending.length > 0 && (
        <div className="caveat">
          <strong>Still settling.</strong> Reeve is answering partly from a
          short-term buffer of writes it has accepted but not yet indexed:
          <ul style={{ margin: "0.3rem 0 0", paddingLeft: "1.1rem" }}>
            {ctx.pending.map((p, i) => (
              <li key={i} style={{ fontSize: "0.82rem" }}>{p}</li>
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
            <div className="fact">entities: {ep.entities.join(", ")}</div>
          )}
          {ep.actions.map((a, j) => (
            <div className="fact" key={`a${j}`}>
              {a.actor} — {a.verb}
              {a.object ? ` → ${a.object}` : ""}
            </div>
          ))}
          {ep.relations.map((r, j) => (
            <div className="fact" key={`r${j}`}>
              {r.subject} {r.relation} {r.object}
            </div>
          ))}
          {ep.states.map((s, j) => (
            <div className={`fact ${s.superseded ? "superseded" : ""}`} key={`s${j}`}>
              {s.entity}.{s.attribute} = {s.value}
              {s.superseded && <span className="tag">superseded</span>}
            </div>
          ))}
          {ep.locations.length > 0 && (
            <div className="fact">location: {ep.locations.join(", ")}</div>
          )}
        </div>
      ))}

      {Object.keys(ctx.roles).length > 0 && (
        <div style={{ marginTop: "0.6rem" }}>
          <strong style={{ fontSize: "0.85rem" }}>Roles</strong>
          {Object.entries(ctx.roles).map(([entity, role]) => (
            <div className="fact" key={entity}>
              {entity} → {role}
            </div>
          ))}
        </div>
      )}

      {showRaw && <pre className="raw">{ctx.raw}</pre>}
    </div>
  );
}
