import { LogOut } from "lucide-react"
import { useAuth } from "@/lib/auth"
import { useConfirm } from "@/components/ConfirmDialog"
import { Button } from "@/components/ui/button"

// Signing out asks first: a slip of the mouse must not end a session in the middle of work.
export default function SignOutButton({ icon = false }) {
  const { logout } = useAuth()
  const confirm = useConfirm()
  async function ask() {
    if (await confirm({ title: "Sign out?", description: "You will need your username and password to sign in again.", action: "Sign out" })) logout()
  }
  return <Button variant="outline" size="sm" onClick={ask}>{icon && <LogOut />} Sign out</Button>
}
