import { NavLink, Outlet } from "react-router-dom"
import { Building2, ClipboardList, FileQuestion, LogOut, MonitorPlay, Trophy, Users } from "lucide-react"
import { useAuth } from "@/lib/auth"
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
  return (
    <SidebarProvider>
      <Sidebar>
        <SidebarHeader className="px-4 pt-5 pb-0">
          <span className="font-brand text-xl font-bold">GLOBX <span className="text-primary">Assess</span></span>
          <div className="mt-4 border-b-2 border-dotted border-muted-foreground/40" data-testid="brand-rule" />
        </SidebarHeader>
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
        <header className="flex h-12 items-center gap-2 border-b px-4">
          <SidebarTrigger />
          <Separator orientation="vertical" className="h-5" />
          <span className="text-sm text-muted-foreground">{user.org_name}</span>
        </header>
        <main className="p-6"><Outlet /></main>
      </SidebarInset>
    </SidebarProvider>
  )
}
