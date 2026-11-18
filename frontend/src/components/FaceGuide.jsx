import { DEFAULT_ZONE } from "@/lib/faces"

const COLOR = { ok: "#16a34a", off: "#d97706", none: "#dc2626", many: "#dc2626" }

// The camera picture with the oval the face must stay in and a box on every face the browser sees. Shown mirrored, like a video call
// (the pictures kept as evidence are not). The drawing uses the video's own pixels with "slice", so it lines up with object-cover.
// With `sample` there is no camera: a drawn head, for the exam setup page.
export default function FaceGuide({ videoRef, seen, zone = DEFAULT_ZONE, state = "ok", sample = false, className = "" }) {
  const w = seen?.w || 640, h = seen?.h || 480
  const rx = w * zone / 200, ry = h * zone / 200, c = COLOR[state] ?? COLOR.ok
  const oval = `M${w / 2 - rx} ${h / 2}A${rx} ${ry} 0 1 0 ${w / 2 + rx} ${h / 2}A${rx} ${ry} 0 1 0 ${w / 2 - rx} ${h / 2}Z`
  return (
    <div className={"relative aspect-[4/3] overflow-hidden bg-black " + className} data-testid="face-guide" data-state={state} data-zone={zone}>
      <div className="size-full -scale-x-100">
        {sample
          ? <div className="size-full bg-gradient-to-b from-slate-600 to-slate-800" />
          : <video ref={videoRef} muted playsInline className="size-full object-cover" />}
        <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid slice" className="absolute inset-0 size-full" aria-hidden="true">
          <path d={`M0 0H${w}V${h}H0Z${oval}`} fillRule="evenodd" fill="#000" fillOpacity="0.35" />
          {sample && <g fill="#cbd5e1"><circle cx={w / 2} cy={h * 0.42} r={h * 0.17} /><path d={`M${w * 0.28} ${h}Q${w / 2} ${h * 0.58} ${w * 0.72} ${h}Z`} /></g>}
          <path d={oval} fill="none" stroke={c} strokeWidth="3" strokeDasharray="10 6" vectorEffect="non-scaling-stroke" data-testid="face-oval" />
          {(sample ? [{ x: w * 0.4, y: h * 0.27, w: w * 0.2, h: h * 0.3 }] : seen?.faces ?? []).map((f, i) => (
            <rect key={i} x={f.x} y={f.y} width={f.w} height={f.h} rx="8" fill="none" stroke={c} strokeWidth="3" vectorEffect="non-scaling-stroke" data-testid="face-box" />
          ))}
        </svg>
      </div>
    </div>
  )
}
