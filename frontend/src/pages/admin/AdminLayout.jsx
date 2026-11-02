import { NavLink, Outlet } from "react-router-dom"
import { Building2, ClipboardList, FileQuestion, LogOut, MonitorPlay, Trophy } from "lucide-react"
import { useAuth } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarHeader, SidebarInset,
  SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarProvider, SidebarTrigger,
} from "@/components/ui/sidebar"

const NAV = [
  { to: "/admin", label: "Exams", icon: ClipboardList, end: true },
  { to: "/admin/questions", label: "Question bank", icon: FileQuestion },
  { to: "/admin/departments", label: "Departments", icon: Building2 },
  { to: "/admin/monitor", label: "Live monitor", icon: MonitorPlay },
  { to: "/admin/results", label: "Results", icon: Trophy },
]

export default function AdminLayout() {
  const { user, logout } = useAuth()
  return (
    <SidebarProvider>
      <Sidebar>
        <SidebarHeader className="px-4 py-3"><span className="font-brand text-lg font-bold">GLOBX <span className="text-primary">Assess</span></span></SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                {NAV.map(({ to, label, icon: Icon, end }) => (
                  <SidebarMenuItem key={to}>
                    <NavLink to={to} end={end}>
                      {({ isActive }) => (
                        <SidebarMenuButton asChild isActive={isActive}>
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
