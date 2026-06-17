"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Settings,
  BarChart3,
  Users,
  LogOut,
  FileText,
  Upload,
  ChevronDown,
  Search,
  ScanLine,
  Globe,
} from "lucide-react";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { type AuthUser } from "@/lib/auth-types";

const menuItems = [
  {
    title: "Dashboard",
    url: "/dashboard",
    icon: LayoutDashboard,
  },
  {
    title: "Klanten",
    url: "/dashboard/klanten",
    icon: Users,
  },
];

const blogItems = [
  {
    title: "Alle blogs",
    url: "/dashboard/blogs",
    icon: FileText,
  },
  {
    title: "CSV Upload",
    url: "/dashboard/blogs/upload",
    icon: Upload,
  },
  {
    title: "Instellingen",
    url: "/dashboard/blogs/settings",
    icon: Settings,
  },
];

const landingPageItems = [
  { title: "Alle pagina's", url: "/dashboard/landing-pages", icon: FileText },
  { title: "CSV Upload", url: "/dashboard/landing-pages/upload", icon: Upload },
  { title: "Instellingen", url: "/dashboard/landing-pages/settings", icon: Settings },
]

const seoItems = [
  {
    title: "SEO Tracker",
    url: "/dashboard/seo/tracker",
    icon: Search,
  },
  {
    title: "Meta Generator",
    url: "/dashboard/seo/meta-generator",
    icon: FileText,
  },
];

const auditItems = [
  {
    title: "Website Audit",
    url: "/dashboard/audit",
    icon: ScanLine,
  },
];

export function AppSidebar({ user }: { user: AuthUser }) {
  const pathname = usePathname();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/dashboard">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                  <img src="/iExist-favicon-X-blauwgeel.svg" alt="Logo" className="size-4" />
                </div>
                <div className="flex flex-col gap-0.5 leading-none">
                  <span className="font-semibold">Dashboard</span>
                  <span className="text-xs">App</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigatie</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {menuItems.map((item) => {
                const isActive = pathname === item.url;
                return (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      asChild
                      isActive={isActive}
                      tooltip={item.title}
                    >
                      <Link href={item.url}>
                        <item.icon />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}

              {/* Blog Generator Dropdown */}
              <Collapsible asChild className="group/collapsible">
                <SidebarMenuItem>
                  <CollapsibleTrigger asChild>
                    <SidebarMenuButton tooltip="Blog Generator">
                      <FileText />
                      <span>Blog Generator</span>
                      <ChevronDown className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-180" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub>
                      {blogItems.map((item) => {
                        const isActive = pathname === item.url;
                        return (
                          <SidebarMenuSubItem key={item.title}>
                            <SidebarMenuSubButton asChild isActive={isActive}>
                              <Link href={item.url}>
                                <item.icon />
                                <span>{item.title}</span>
                              </Link>
                            </SidebarMenuSubButton>
                          </SidebarMenuSubItem>
                        );
                      })}
                    </SidebarMenuSub>
                  </CollapsibleContent>
                </SidebarMenuItem>
              </Collapsible>

              {/* Landingspagina's Dropdown */}
              <Collapsible asChild className="group/collapsible">
                <SidebarMenuItem>
                  <CollapsibleTrigger asChild>
                    <SidebarMenuButton
                      isActive={pathname.startsWith("/dashboard/landing-pages")}
                      tooltip="Landingspagina's"
                    >
                      <Globe />
                      <span>Landingspagina&apos;s</span>
                      <ChevronDown className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-180" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub>
                      {landingPageItems.map((item) => {
                        const isActive = pathname === item.url;
                        return (
                          <SidebarMenuSubItem key={item.title}>
                            <SidebarMenuSubButton asChild isActive={isActive}>
                              <Link href={item.url}>
                                <item.icon />
                                <span>{item.title}</span>
                              </Link>
                            </SidebarMenuSubButton>
                          </SidebarMenuSubItem>
                        );
                      })}
                    </SidebarMenuSub>
                  </CollapsibleContent>
                </SidebarMenuItem>
              </Collapsible>

              <Collapsible asChild className="group/collapsible">
                <SidebarMenuItem>
                  <CollapsibleTrigger asChild>
                    <SidebarMenuButton
                      tooltip="SEO Tools"
                      className="text-muted-foreground"
                    >
                      <Search />
                      <span>SEO Tools</span>
                      <span className="ml-auto rounded bg-sidebar-accent px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                        Binnenkort
                      </span>
                      <ChevronDown className="transition-transform duration-200 group-data-[state=open]/collapsible:rotate-180" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub>
                      {seoItems.map((item) => (
                        <SidebarMenuSubItem key={item.title}>
                          <SidebarMenuSubButton
                            aria-disabled
                            className="cursor-not-allowed opacity-50"
                          >
                            <item.icon />
                            <span>{item.title}</span>
                            <span className="ml-auto rounded bg-sidebar-accent px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                              Binnenkort
                            </span>
                          </SidebarMenuSubButton>
                        </SidebarMenuSubItem>
                      ))}
                    </SidebarMenuSub>
                  </CollapsibleContent>
                </SidebarMenuItem>
              </Collapsible>

              <Collapsible asChild className="group/collapsible">
                <SidebarMenuItem>
                  <CollapsibleTrigger asChild>
                    <SidebarMenuButton
                      tooltip="Audit Tools"
                      className="text-muted-foreground"
                    >
                      <ScanLine />
                      <span>Audit Tools</span>
                      <span className="ml-auto rounded bg-sidebar-accent px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                        Binnenkort
                      </span>
                      <ChevronDown className="transition-transform duration-200 group-data-[state=open]/collapsible:rotate-180" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub>
                      {auditItems.map((item) => (
                        <SidebarMenuSubItem key={item.title}>
                          <SidebarMenuSubButton
                            aria-disabled
                            className="cursor-not-allowed opacity-50"
                          >
                            <item.icon />
                            <span>{item.title}</span>
                            <span className="ml-auto rounded bg-sidebar-accent px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                              Binnenkort
                            </span>
                          </SidebarMenuSubButton>
                        </SidebarMenuSubItem>
                      ))}
                    </SidebarMenuSub>
                  </CollapsibleContent>
                </SidebarMenuItem>
              </Collapsible>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              isActive={pathname === "/dashboard/settings"}
              tooltip="Instellingen"
            >
              <Link href="/dashboard/settings">
                <Settings />
                <span>Instellingen</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" className="cursor-default">
              <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-accent">
                <Users className="size-4" />
              </div>
              <div className="flex flex-col gap-0.5 leading-none">
                <span className="font-semibold text-xs truncate">
                  {user.email}
                </span>
                <span className="text-xs text-muted-foreground">Account</span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton asChild tooltip="Logout">
              <form action="/api/auth/signout" method="POST">
                <button
                  type="submit"
                  className="flex w-full items-center gap-2"
                >
                  <LogOut />
                  <span>Uitloggen</span>
                </button>
              </form>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}
