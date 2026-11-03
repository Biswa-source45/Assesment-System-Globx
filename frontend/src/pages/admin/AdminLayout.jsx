import { useEffect, useState } from "react"
import { NavLink, Outlet } from "react-router-dom"
import { Building2, ClipboardList, FileQuestion, LogOut, MonitorPlay, Trophy, Users } from "lucide-react"
import { useAuth } from "@/lib/auth"
import { get } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarHeader, SidebarInset,
  SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarProvider, SidebarTrigger,
} from "@/components/ui/sidebar"

// `can` is the permission the server grants (see /auth/me): a person only sees the screens they may use.
const NAV = [
  { to: "/admin", label: "Exams", icon: ClipboardList, end: true, can: "view" },
  { to: "/admin/questions", label: "Question bank", icon: FileQuestion, can: "bank" },
  { to: "/admin/departments", label: "Departments", icon: Building2, can: "view" },
  { to: "/admin/monitor", label: "Live monitor", icon: MonitorPlay, can: "view" },
  { to: "/admin/results", label: "Results", icon: Trophy, can: "view" },
  { to: "/admin/users", label: "Users", icon: Users, can: "admin" },
]

export default function AdminLayout() {
  const { user, logout } = useAuth()
  const [unsafe, setUnsafe] = useState(false)  // production without the isolated judge: candidate code would run inside the server
  useEffect(() => { get("/system/sandboxes").then((s) => setUnsafe(s.unsafe_in_production)).catch(() => {}) }, [])
  return (
    <SidebarProvider>
      <Sidebar>
        <SidebarHeader className="h-12 flex-row items-center px-4 py-0"><span className="font-brand text-lg font-bold" data-testid="brand">GLOBX <span className="text-primary">Assess</span></span></SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu className="gap-1.5">
                {NAV.filter((n) => user.can[n.can]).map(({ to, label, icon: Icon, end }) => (
                  <SidebarMenuItem key={to}>
                    <NavLink to={to} end={end}>
                      {({ isActive }) => (
                        <SidebarMenuButton asChild isActive={isActive} size="lg" className="gap-3 px-3 text-[15px] [&>svg]:size-5">
                          <span><Icon /> {label}</span>
                        </SidebarMenuButton>
                      )}
                    </NavLink>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="gap-2 p-3">
          <div className="truncate text-sm">
            <div className="font-medium">{user.name || user.email}</div>
            <div className="text-xs text-muted-foreground">{user.roles.join(", ")}</div>
          </div>
          <Button variant="outline" size="sm" onClick={logout}><LogOut /> Sign out</Button>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        <header className="flex h-12 items-center gap-2 border-b px-4" data-testid="topbar">
          <SidebarTrigger />
          <Separator orientation="vertical" className="h-5" />
          <span className="text-sm text-muted-foreground" data-testid="company">{user.org_name}</span>
        </header>
        {unsafe && (
          <div role="alert" data-testid="unsafe-judge" className="border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-sm font-medium text-destructive">
            Coding and SQL questions are switched off: the isolated judge is not set up, and candidate code must never run inside the exam server. Ask the administrator to start it.
          </div>
        )}
        <main className="p-6"><Outlet /></main>
      </SidebarInset>
    </SidebarProvider>
  )
}
