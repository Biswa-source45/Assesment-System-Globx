import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import App from "@/App"
import { AuthProvider } from "@/lib/auth"
import { TooltipProvider } from "@/components/ui/tooltip"
import { Toaster } from "@/components/ui/sonner"
import { ConfirmProvider } from "@/components/ConfirmDialog"
import "@/index.css"

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <TooltipProvider>
          <ConfirmProvider>
            <App />
          </ConfirmProvider>
          <Toaster richColors />
        </TooltipProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>
)
