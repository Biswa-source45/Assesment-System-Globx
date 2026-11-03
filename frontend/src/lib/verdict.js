// One look for right and wrong, used wherever a reviewer or candidate reads a result: green with a tick, red with a cross, amber for part marks,
// grey for nothing. Each also has an icon and words, so it still reads for someone who cannot tell red from green.
export const TONE = {
  good: "border-green-600 bg-green-50 text-green-900",
  bad: "border-red-600 bg-red-50 text-red-900",
  part: "border-amber-500 bg-amber-50 text-amber-900",
  none: "border-border bg-muted/40 text-muted-foreground",
  info: "border-primary bg-primary/10 text-primary",
}

// The coloured pills of the results screens: what happened to a person, and where an exam's results stand.
export const OUTCOME_TONE = { submitted: "good", time_over: "part", violation_limit: "bad", face_violation: "bad", admin_ended: "bad", absent: "none", in_progress: "info" }
export const STATE_TONE = { open: "none", calculating: "part", needs_attention: "bad", ready: "info", declared: "good" }
export const BAR = { good: "border-l-green-600", bad: "border-l-red-600", part: "border-l-amber-500", none: "border-l-border" }
export const VERDICT_TEXT = { good: "Correct", bad: "Wrong", part: "Partly correct", none: "Not answered" }

export function verdictOf(score, marks, answered) {
  if (!answered) return "none"
  if (marks > 0 && score >= marks - 1e-9) return "good"
  if (score <= 0) return "bad"
  return "part"
}
