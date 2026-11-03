// Words shown to staff for statuses coming from the server.
export const STATUS = {
  invited: "Not started", in_progress: "In progress", submitted: "Submitted", auto_submitted: "Submitted", evaluating: "Submitted",
  test_taken: "Submitted", review_pending: "Submitted", evaluated: "Marked", banned: "Locked", cancelled: "Cancelled", expired: "Expired",
}

// Why an attempt ended (Attempt.submit_reason).
export const ENDED = {
  submitted: "Submitted by candidate", user: "Submitted by candidate", time_over: "Time ran out", time: "Time ran out",
  violation_limit: "Too many window leaves", face_violation: "Face rule: locked", admin_ended: "Ended by admin",
}

// Where an exam's results stand (the server derives it).
export const RESULT_STATE = { open: "Open", calculating: "Calculating", needs_attention: "Needs attention", ready: "Ready to declare", declared: "Declared" }

export const RISK = { low: "Low", medium: "Medium", high: "High", critical: "Critical" }

// Local-time helpers: <input type="datetime-local"> is in the browser's time zone, the server stores UTC.
const two = (n) => String(n).padStart(2, "0")
export const toLocalInput = (iso) => {
  if (!iso) return ""
  const d = new Date(iso)
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}T${two(d.getHours())}:${two(d.getMinutes())}`
}
export const fromLocalInput = (v) => (v ? new Date(v).toISOString() : null)
export const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "-")
