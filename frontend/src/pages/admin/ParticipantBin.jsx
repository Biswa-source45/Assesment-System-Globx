import { useState } from "react"
import { toast } from "sonner"
import { RotateCcw, Trash2 } from "lucide-react"
import { del, post } from "@/lib/api"
import { fmtDate } from "@/lib/labels"
import { useDebounced, usePaged } from "@/lib/usePaged"
import { useConfirm } from "@/components/ConfirmDialog"
import MoreRows from "@/components/MoreRows"
import { Loading } from "@/components/Spinner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

// The people deleted from this exam. They are in no list, result or Excel file; here they can come back or be removed for good.
export default function ParticipantBin({ testId, onChange }) {
  const confirm = useConfirm()
  const [search, setSearch] = useState("")
  const paged = usePaged(`/tests/${testId}/candidates`, { deleted: true, q: useDebounced(search.trim()) }, { idKey: "assignment_id" })
  const { rows } = paged

  async function restore(r) {
    try { await post(`/assignments/${r.assignment_id}/restore`); toast.success(`${r.name} is back in the participants list`); paged.reload(); onChange() } catch (e) { toast.error(e.message) }
  }
  async function forever(r) {
    const yes = await confirm({
      title: `Delete ${r.name} for good?`,
      description: "Their login, answers, marks, camera pictures and recordings are removed from the server. This cannot be undone and they will not appear in any result or Excel file. If you only want them out of the list for now, keep them in the bin.",
      action: "Delete for good", destructive: true,
    })
    if (!yes) return
    try { await del(`/assignments/${r.assignment_id}/permanent`); toast.success(`${r.name} was deleted for good`); paged.reload(); onChange() } catch (e) { toast.error(e.message) }
  }

  return (
    <div className="grid gap-3" data-testid="participant-bin">
      <p className="text-sm text-muted-foreground">People deleted from this exam. They are not counted in the participants, the results or the Excel file. Restore a person to bring them back exactly as they were, or delete them for good.</p>
      <Input className="w-64" placeholder="Search by name or username" aria-label="Search the bin" value={search} onChange={(e) => setSearch(e.target.value)} />
      {rows === null && !paged.error && <Loading />}
      {paged.error && !rows && <p className="text-sm text-destructive">{paged.error}</p>}
      {rows && (
        <Table>
          <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Username</TableHead><TableHead>Email</TableHead><TableHead>What they had done</TableHead><TableHead>Score</TableHead><TableHead>Deleted</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.assignment_id} data-testid="bin-row">
                <TableCell className="font-medium">{r.name}</TableCell>
                <TableCell className="font-mono text-xs">{r.username || r.email}</TableCell>
                <TableCell className="text-xs">{r.email.endsWith("@exam.local") ? <span className="text-muted-foreground">No email</span> : r.email}</TableCell>
                <TableCell>{r.outcome_label}</TableCell>
                <TableCell>{r.score != null ? `${r.score} / ${r.max}` : "-"}</TableCell>
                <TableCell className="text-xs">{fmtDate(r.deleted_at)}</TableCell>
                <TableCell>
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="outline" onClick={() => restore(r)}><RotateCcw /> Restore</Button>
                    <Button size="sm" variant="outline" className="text-destructive" onClick={() => forever(r)}><Trash2 /> Delete for good</Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && <TableRow><TableCell colSpan={7} className="text-muted-foreground">{search.trim() ? "Nobody matches." : "The bin is empty."}</TableCell></TableRow>}
          </TableBody>
        </Table>
      )}
      <MoreRows paged={paged} what="people" />
    </div>
  )
}
