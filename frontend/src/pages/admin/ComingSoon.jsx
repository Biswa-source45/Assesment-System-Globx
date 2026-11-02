export default function ComingSoon({ title }) {
  return (
    <div className="grid gap-2">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="text-sm text-muted-foreground">Not built yet.</p>
    </div>
  )
}
