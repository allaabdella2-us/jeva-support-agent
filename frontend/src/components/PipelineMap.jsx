import { useEffect, useMemo, useRef, useState } from "react";
import { NODES, EDGES, OWNER_COLOR, VIEW_H, edgePath, buildPlan, stateAt } from "../mapModel.js";

const STEP_MS = 380;
const reduceMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function Values({ id, rows }) {
  const [x, top, w] = NODES[id];
  return rows.map((row, i) => {
    const y = top + 31 + i * 14;
    const cell = (v) => {
      const s = String(v);
      const warn = s.startsWith("!");
      const text = warn ? s.slice(1) : s;
      return { text, cls: `v${warn ? " flag" : ""}${text === "…" ? " ph" : ""}` };
    };
    if (Array.isArray(row)) {
      const v = cell(row[1]);
      return (
        <g key={i}>
          <text className="vl" x={x - w / 2 + 11} y={y} textAnchor="start">{row[0]}</text>
          <text className={v.cls} x={x + w / 2 - 8} y={y} textAnchor="end">{v.text}</text>
        </g>
      );
    }
    const v = cell(row);
    return <text key={i} className={v.cls} x={x + 2} y={y} textAnchor="middle">{v.text}</text>;
  });
}

// Animated architecture map. Replays whenever a new trace arrives.
export default function PipelineMap({ trace, senderName, runKey, llmLabel = "Claude" }) {
  const steps = useMemo(() => (trace ? buildPlan(trace, senderName) : []), [trace, senderName]);
  const [upto, setUpto] = useState(-1);
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!steps.length) { setUpto(-1); return; }
    if (reduceMotion()) { setUpto(steps.length - 1); return; }
    setUpto(0);
    let i = 0;
    const timer = setInterval(() => {
      i += 1;
      setUpto(i);
      if (i >= steps.length - 1) clearInterval(timer);
    }, STEP_MS);
    return () => clearInterval(timer);
  }, [steps, runKey]);

  const s = stateAt(steps, upto);

  // Keep the active node in view inside the scroll area.
  useEffect(() => {
    if (!s.now || !wrapRef.current) return;
    const el = wrapRef.current.querySelector(`[data-node="${s.now}"]`);
    if (!el) return;
    const wr = wrapRef.current.getBoundingClientRect();
    const er = el.getBoundingClientRect();
    wrapRef.current.scrollBy({
      top: er.top - wr.top - wr.height / 2 + er.height / 2,
      behavior: reduceMotion() ? "auto" : "smooth",
    });
  }, [s.now]);

  return (
    <div className="map-panel">
      <p className="map-caption" aria-live="polite">{s.caption}</p>
      <div className="map-scroll" ref={wrapRef}>
        <svg
          className={`map${s.done ? " settled" : ""}`}
          viewBox={`0 0 340 ${VIEW_H}`}
          role="img"
          aria-label="Pipeline architecture from customer ticket to customer response"
        >
          {EDGES.map(([a, b]) => (
            <path key={`${a}-${b}`} className={`medge${s.edges.has(`${a}-${b}`) ? " on" : ""}`} d={edgePath([a, b])} />
          ))}
          {Object.entries(NODES).map(([id, [x, top, w, h, title, owner, placeholder]]) => {
            const cls = s.nodes[id];
            const classes = ["mnode", cls, s.now === id ? "now" : ""].filter(Boolean).join(" ");
            return (
              <g key={id} className={classes} data-node={id}>
                <rect className="box" x={x - w / 2} y={top} width={w} height={h} rx="8" />
                <rect x={x - w / 2 + 1} y={top + 8} width="4" height={h - 16} rx="2" fill={OWNER_COLOR[owner]} />
                <text className="t" x={x + 2} y={top + 15}>{title.replace("Claude", llmLabel)}</text>
                <Values id={id} rows={s.vals[id] || placeholder} />
              </g>
            );
          })}
        </svg>
      </div>
      <div className="legend">
        <span><i style={{ background: "var(--orange)" }} />Customer</span>
        <span><i style={{ background: "var(--muted)" }} />Python owns it</span>
        <span><i style={{ background: "var(--teal)" }} />Jev understands</span>
        <span><i style={{ background: "var(--purple)" }} />{llmLabel} writes</span>
      </div>
    </div>
  );
}
