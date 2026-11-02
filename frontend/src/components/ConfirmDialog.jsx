import { createContext, useCallback, useContext, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"

const ConfirmContext = createContext(null)

// One in-app dialog replaces the browser's confirm box everywhere:
//   const confirm = useConfirm()
//   if (!(await confirm({ title: "Remove it?", description: "...", action: "Remove", destructive: true }))) return
export function ConfirmProvider({ children }) {
  const [ask, setAsk] = useState(null)
  const settle = useRef(null)

  const confirm = useCallback((options) => new Promise((done) => { settle.current = done; setAsk(options) }), [])
  const answer = (yes) => { settle.current?.(yes); settle.current = null; setAsk(null) }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog open={!!ask} onOpenChange={(open) => !open && answer(false)}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{ask?.title}</DialogTitle>
            <DialogDescription>{ask?.description}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => answer(false)}>Cancel</Button>
            <Button className={ask?.destructive ? "bg-destructive text-white hover:bg-destructive/90" : ""} onClick={() => answer(true)}>{ask?.action ?? "Confirm"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ConfirmContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export const useConfirm = () => useContext(ConfirmContext)
