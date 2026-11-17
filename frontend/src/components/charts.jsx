// Small hand-drawn charts (no chart library): each is plain SVG or divs, readable on a phone, with a text description for screen readers.
export const COLOR = { blue: "#1d4ed8", sky: "#93c5fd", green: "#16a34a", red: "#dc2626", amber: "#d97706", slate: "#94a3b8", ink: "#0f172a" }
export const RISK_COLOR = { low: COLOR.green, medium: COLOR.amber, high: "#ea580c", critical: COLOR.red }
const clamp = (v, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, v))

export function Panel({ title, hint, children, ...rest }) {
  return (
    <section className="grid content-start gap-3 rounded-2xl border bg-white p-5 shadow-sm" {...rest}>
      {title && <div><h2 className="font-semibold">{title}</h2>{hint && <p className="text-xs text-muted-foreground">{hint}</p>}</div>}
      {children}
    </section>
  )
}

export function Tile({ label, value, sub, ...rest }) {
  return (
    <div className="rounded-xl border bg-white p-3 shadow-sm" {...rest}>
      <p className="text-[11px] font-semibold tracking-wide text-muted-foreground">{label.toUpperCase()}</p>
      <p className="text-lg font-semibold" data-testid="tile-value">{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  )
}

export function Ring({ percent, result }) {
  const color = { passed: "#16a34a", not_passed: "#dc2626", not_attempted: "#d97706" }[result] ?? COLOR.blue
  const r = 52, c = 2 * Math.PI * r, p = clamp(percent)
  return (
    <svg viewBox="0 0 128 128" className="size-32 shrink-0" role="img" aria-label={`${percent} percent`}>
      <circle cx="64" cy="64" r={r} fill="none" stroke="#e2e8f0" strokeWidth="11" />
      {p > 0 && <circle cx="64" cy="64" r={r} fill="none" stroke={color} strokeWidth="11" strokeLinecap="round" strokeDasharray={`${(c * p) / 100} ${c}`} transform="rotate(-90 64 64)" />}
      <text x="64" y="68" textAnchor="middle" className="fill-slate-900 text-[26px] font-semibold" style={{ fontFamily: "Poppins, sans-serif" }}>{percent}%</text>
    </svg>
  )
}

// A horizontal bar. `average` draws a dark mark on the bar (the class). Text defaults can be replaced.
export function Bar({ label, score, max, average, text, averageText, color, ...rest }) {
  const w = (v) => `${clamp(max ? (100 * v) / max : 0)}%`
  return (
    <div className="grid gap-1" data-testid="rc-bar" {...rest}>
      <div className="flex items-baseline justify-between gap-2 text-sm"><span className="min-w-0 break-words font-medium">{label}</span><span className="shrink-0 font-semibold">{text ?? `${score} / ${max}`}</span></div>
      <div className="relative h-2.5 rounded-full bg-slate-200">
        <div className="h-full rounded-full bg-primary" style={{ width: w(score), ...(color ? { background: color } : {}) }} />
        {average != null && <div className="absolute -top-1 w-0.5 bg-slate-900" style={{ left: w(average), height: 18 }} title={averageText ?? `Class average ${average}`} />}
      </div>
      {(average != null || averageText) && <span className="text-right text-xs text-muted-foreground">{averageText ?? `class average ${average}`}</span>}
    </div>
  )
}

const W = 340
const tick = "fill-slate-500 text-[11px]"

// Counts in ten bins of 10 percent each. `you` highlights one bin; `marks` are vertical lines at a percent: [{at, label, color}].
export function Histogram({ bins, you, marks = [], xLabel = "Score (%)", name = "Score distribution", ...rest }) {
  const L = 30, R = 8, T = 30, B = 34, H = 200, pw = W - L - R, ph = H - T - B
  const top = Math.max(1, ...bins), bw = pw / bins.length
  const x = (v) => L + (clamp(v) / 100) * pw
  const ticks = top >= 4 ? [0, Math.round(top / 2), top] : Array.from({ length: top + 1 }, (_, i) => i)
  const total = bins.reduce((a, b) => a + b, 0)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto w-full max-w-xl" role="img" aria-label={`${name}: ${bins.map((n, i) => `${i * 10} to ${i * 10 + 10} percent ${n}`).join(", ")}`} {...rest}>
      {ticks.map((t) => <g key={t}><line x1={L} x2={W - R} y1={T + ph - (t / top) * ph} y2={T + ph - (t / top) * ph} stroke="#e2e8f0" /><text x={L - 5} y={T + ph - (t / top) * ph + 3} textAnchor="end" className={tick}>{t}</text></g>)}
      {bins.map((n, i) => {
        const h = (n / top) * ph
        return (
          <g key={i} data-testid="hist-bin" data-count={n}>
            <rect x={L + i * bw + 3} y={T + ph - h} width={bw - 6} height={Math.max(h, 0)} rx="3" fill={i === you ? COLOR.green : COLOR.blue} opacity={i === you ? 1 : 0.85}>
              <title>{`${i * 10} to ${i * 10 + 10}%: ${n} candidate${n === 1 ? "" : "s"}${i === you ? " (you)" : ""}`}</title>
            </rect>
            {n > 0 && <text x={L + i * bw + bw / 2} y={T + ph - h - 4} textAnchor="middle" className="fill-slate-700 text-[11px] font-medium">{n}</text>}
          </g>
        )
      })}
      {bins.map((_, i) => <text key={i} x={L + i * bw} y={H - B + 13} textAnchor="middle" className={tick}>{i * 10}</text>)}
      <text x={L + pw} y={H - B + 13} textAnchor="middle" className={tick}>100</text>
      <text x={L + pw / 2} y={H - 4} textAnchor="middle" className={tick}>{xLabel}</text>
      {marks.map((m, i) => (
        <g key={m.label} data-testid="hist-mark">
          <line x1={x(m.at)} x2={x(m.at)} y1={T - 6} y2={T + ph} stroke={m.color ?? COLOR.ink} strokeWidth="1.5" strokeDasharray="4 3" />
          <text x={clamp(x(m.at), L + 28, W - R - 28)} y={9 + (i % 2) * 11} textAnchor="middle" className="fill-slate-700 text-[11px] font-medium">{m.label}</text>
        </g>
      ))}
      {total === 0 && <text x={L + pw / 2} y={T + ph / 2} textAnchor="middle" className="fill-slate-400 text-xs">Nothing to show yet</text>}
    </svg>
  )
}

// Dots: one per candidate. `points` = [{x, y, color, label}], x in minutes, y in percent.
export function Scatter({ points, xMax, xLabel = "Minutes taken", yLabel = "Score (%)", name = "Score against time taken", ...rest }) {
  const L = 34, R = 10, T = 10, B = 34, H = 240, pw = W - L - R, ph = H - T - B
  const hi = Math.max(1, xMax, ...points.map((p) => p.x)) * 1.04
  const px = (v) => L + (v / hi) * pw, py = (v) => T + ph - (clamp(v) / 100) * ph
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto w-full max-w-xl" role="img" aria-label={`${name}: ${points.length} candidates`} {...rest}>
      {[0, 25, 50, 75, 100].map((t) => <g key={t}><line x1={L} x2={W - R} y1={py(t)} y2={py(t)} stroke="#e2e8f0" /><text x={L - 5} y={py(t) + 3} textAnchor="end" className={tick}>{t}</text></g>)}
      {[0, 0.25, 0.5, 0.75, 1].map((f) => <text key={f} x={L + f * pw} y={H - B + 13} textAnchor="middle" className={tick}>{Math.round(f * hi)}</text>)}
      <text x={L + pw / 2} y={H - 4} textAnchor="middle" className={tick}>{xLabel}</text>
      <text transform={`translate(9 ${T + ph / 2}) rotate(-90)`} textAnchor="middle" className={tick}>{yLabel}</text>
      {points.map((p, i) => <circle key={i} data-testid="scatter-dot" cx={px(p.x)} cy={py(p.y)} r="4.5" fill={p.color ?? COLOR.blue} fillOpacity="0.75" stroke="#fff" strokeWidth="1"><title>{p.label}</title></circle>)}
      {points.length === 0 && <text x={L + pw / 2} y={T + ph / 2} textAnchor="middle" className="fill-slate-400 text-xs">Nothing to show yet</text>}
    </svg>
  )
}

// Score of each exam over time. `points` = [{label, you, avg}] oldest first; one exam is a dot, more are joined by a line.
export function LineChart({ points, name = "Your scores", ...rest }) {
  const L = 30, R = 14, T = 12, B = 40, H = 200, pw = W - L - R, ph = H - T - B
  const px = (i) => L + (points.length === 1 ? pw / 2 : (i / (points.length - 1)) * pw), py = (v) => T + ph - (clamp(v) / 100) * ph
  const path = (key) => points.map((p, i) => `${i ? "L" : "M"}${px(i)},${py(p[key])}`).join(" ")
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto w-full max-w-xl" role="img" aria-label={`${name}: ${points.map((p) => `${p.label} ${p.you} percent`).join(", ")}`} {...rest}>
      {[0, 50, 100].map((t) => <g key={t}><line x1={L} x2={W - R} y1={py(t)} y2={py(t)} stroke="#e2e8f0" /><text x={L - 5} y={py(t) + 3} textAnchor="end" className={tick}>{t}</text></g>)}
      {points.length > 1 && <path d={path("avg")} fill="none" stroke={COLOR.slate} strokeWidth="2" strokeDasharray="5 4" />}
      {points.length > 1 && <path d={path("you")} fill="none" stroke={COLOR.blue} strokeWidth="2.5" />}
      {points.map((p, i) => (
        <g key={i} data-testid="line-dot">
          <circle cx={px(i)} cy={py(p.avg)} r="3.5" fill={COLOR.slate}><title>{`${p.label}: class average ${p.avg}%`}</title></circle>
          <circle cx={px(i)} cy={py(p.you)} r="5" fill={COLOR.blue} stroke="#fff" strokeWidth="1.5"><title>{`${p.label}: you ${p.you}%`}</title></circle>
          <text x={px(i)} y={H - B + 14} textAnchor="middle" className={tick}>{p.label.length > 12 ? p.label.slice(0, 11) + "…" : p.label}</text>
        </g>
      ))}
    </svg>
  )
}

export function Legend({ items }) {
  return <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">{items.map(([color, text]) => <span key={text} className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-full" style={{ background: color }} />{text}</span>)}</div>
}
