"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  LayoutDashboard,
  Settings,
  BarChart3,
  LogOut,
  FileText,
  Upload,
  ChevronDown,
  Search,
  ScanLine,
  Globe,
  ListChecks,
} from "lucide-react";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { type AuthUser } from "@/lib/auth-types";
import {
  customerHref,
  customerIdFromLocation,
  persistActiveCustomer,
  readTabCustomerId,
  subscribeTabCustomer,
  writeActiveCustomerCookie,
} from "@/lib/active-customer";
import {
  CustomerSwitcher,
  fetchCustomerOptions,
  type CustomerOption,
} from "@/components/klanten/CustomerSwitcher";

const menuItems = [
  {
    title: "Dashboard",
    url: "/dashboard",
    icon: LayoutDashboard,
  },
];

const LIVEGANG_URL = "/dashboard/livegang";
const SEO_GEO_URL = "/dashboard/livegang/seo-geo";
const GOLIVE_URL = "/dashboard/livegang/oplevering";
const ANALYTICS_URL = "/dashboard/livegang/analytics";

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
];

const landingPageItems = [
  { title: "Alle pagina's", url: "/dashboard/landing-pages", icon: FileText },
  { title: "CSV Upload", url: "/dashboard/landing-pages/upload", icon: Upload },
];

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

// Shopify-admin look: compact items, light pill for active, no sub-menu guide line
const itemClass =
  "h-8 rounded-lg text-[13px] font-medium text-white/85 hover:bg-white/10 hover:text-white data-[active=true]:bg-white/10 data-[active=true]:font-semibold data-[active=true]:text-white [&>svg]:text-white/70 data-[active=true]:[&>svg]:text-white";
const subClass =
  "h-7 rounded-lg text-[13px] text-white/70 hover:bg-white/10 hover:text-white data-[active=true]:bg-white/10 data-[active=true]:font-semibold data-[active=true]:text-white [&>svg]:text-white/60 data-[active=true]:[&>svg]:text-white";
const subMenuClass = "ml-3.5 border-l-0 pl-1.5";
const badgeClass =
  "ml-auto rounded-md bg-white/10 px-1.5 py-0.5 text-[10px] font-medium text-white/70";

// Server-snapshot voor sessionStorage: op de server en bij hydratie is er geen
// tabblad-klant, zodat de eerste render overeenkomt met de server-HTML.
const getServerTabCustomerId = () => null;

export function AppSidebar({
  user,
  customers: initialCustomers,
  initialCustomerId,
  ...props
}: {
  user: AuthUser;
  customers: CustomerOption[];
  initialCustomerId: string | null;
} & React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { state, isMobile, setOpen } = useSidebar();

  // Klantenlijst: begint met de server-prop, de kiezer kan hem verversen.
  const [customers, setCustomers] = React.useState(initialCustomers);
  const [prevInitialCustomers, setPrevInitialCustomers] =
    React.useState(initialCustomers);
  if (initialCustomers !== prevInitialCustomers) {
    setPrevInitialCustomers(initialCustomers);
    setCustomers(initialCustomers);
  }

  // Actieve klant: adres, dan sessionStorage van dit tabblad, dan de cookie.
  const urlCustomerId = customerIdFromLocation(pathname, searchParams);
  const tabCustomerId = React.useSyncExternalStore(
    subscribeTabCustomer,
    readTabCustomerId,
    getServerTabCustomerId
  );
  const storedCustomerId = tabCustomerId ?? initialCustomerId;
  // Een id uit het adres geldt altijd (de lijst kan nog niet ververst zijn);
  // een onthouden id alleen als de klant nog bestaat.
  const activeCustomerId =
    urlCustomerId ??
    (storedCustomerId &&
    customers.some((customer) => customer.id === storedCustomerId)
      ? storedCustomerId
      : null);

  // Klant uit het adres onthouden voor dit tabblad en als laatst gekozen.
  React.useEffect(() => {
    if (urlCustomerId) persistActiveCustomer(urlCustomerId);
  }, [urlCustomerId]);

  // Staat de klant uit het adres niet in de lijst (bijv. net aangemaakt),
  // haal de lijst dan opnieuw op.
  const urlCustomerKnown =
    !urlCustomerId || customers.some((c) => c.id === urlCustomerId);
  React.useEffect(() => {
    if (urlCustomerKnown) return;
    let cancelled = false;
    void fetchCustomerOptions().then((fresh) => {
      if (fresh && !cancelled) setCustomers(fresh);
    });
    return () => {
      cancelled = true;
    };
  }, [urlCustomerId, urlCustomerKnown]);

  // Bij terugkeer naar dit tabblad de cookie op de klant van dit tabblad
  // zetten, zodat een server-redirect in dit tabblad de juiste klant pakt.
  const tabActiveCustomerId = urlCustomerId ?? tabCustomerId;
  React.useEffect(() => {
    if (!tabActiveCustomerId) return;
    const syncCookie = () => {
      if (document.visibilityState === "visible") {
        writeActiveCustomerCookie(tabActiveCustomerId);
      }
    };
    window.addEventListener("focus", syncCookie);
    document.addEventListener("visibilitychange", syncCookie);
    return () => {
      window.removeEventListener("focus", syncCookie);
      document.removeEventListener("visibilitychange", syncCookie);
    };
  }, [tabActiveCustomerId]);

  // Menu-links volgen de actieve klant; zonder klant de gewone adressen.
  const hrefFor = (
    section: Parameters<typeof customerHref>[0],
    fallback: string
  ) => (activeCustomerId ? customerHref(section, activeCustomerId) : fallback);
  const customerHomePath = activeCustomerId
    ? customerHref("home", activeCustomerId)
    : null;
  const isPathActive = (url: string): boolean => {
    if (url === "/dashboard") {
      return (
        pathname === "/dashboard" ||
        (customerHomePath !== null &&
          (pathname === customerHomePath ||
            pathname.startsWith(`${customerHomePath}/`)))
      );
    }
    return pathname.startsWith(url);
  };
  const menuHref = (url: string) =>
    url === "/dashboard" ? hrefFor("home", url) : url;
  const blogHref = (url: string) =>
    url === "/dashboard/blogs" ? hrefFor("blogs", url) : url;
  const landingPageHref = (url: string) =>
    url === "/dashboard/landing-pages" ? hrefFor("landingPages", url) : url;

  // "Livegang checklist" staat open op de eigen pagina's, ook als je er vanaf
  // een andere pagina naartoe navigeert (de sidebar blijft dan gemount).
  const onLivegang = pathname.startsWith(LIVEGANG_URL);
  const [livegangOpen, setLivegangOpen] = React.useState(onLivegang);
  const [wasOnLivegang, setWasOnLivegang] = React.useState(onLivegang);
  if (onLivegang !== wasOnLivegang) {
    setWasOnLivegang(onLivegang);
    if (onLivegang) setLivegangOpen(true);
  }

  // Ingeklapt tot iconen is het submenu verborgen: klappen we dan alleen de groep
  // open, dan gebeurt er zichtbaar niets. Daarom eerst de sidebar uitklappen.
  const openLivegangFromIcon = (event: React.MouseEvent) => {
    if (state !== "collapsed" || isMobile) return;
    event.preventDefault();
    setOpen(true);
    setLivegangOpen(true);
  };

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <div className="flex h-10 items-center gap-2 px-1 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
          <Link
            href="/dashboard"
            className="flex min-w-0 items-center gap-2 group-data-[collapsible=icon]:hidden"
          >
            <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-white">
              <img
                src="/iExist-favicon-X-blauwgeel.svg"
                alt="Logo"
                className="size-4"
              />
            </span>
            <span className="truncate text-sm font-semibold text-white">
              iExist
            </span>
          </Link>
          <SidebarTrigger className="ml-auto text-white/70 hover:bg-white/10 hover:text-white group-data-[collapsible=icon]:ml-0" />
        </div>
        <CustomerSwitcher
          customers={customers}
          activeCustomerId={activeCustomerId}
          onCustomersChange={setCustomers}
        />
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel className="text-xs text-white/50">
            Navigatie
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {menuItems.map((item) => {
                const isActive = isPathActive(item.url);
                return (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      asChild
                      isActive={isActive}
                      tooltip={item.title}
                      className={itemClass}
                    >
                      <Link href={menuHref(item.url)}>
                        <item.icon />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}

              {/* Livegang checklist Dropdown */}
              <Collapsible
                asChild
                open={livegangOpen}
                onOpenChange={setLivegangOpen}
                className="group/collapsible"
              >
                <SidebarMenuItem>
                  <CollapsibleTrigger asChild onClick={openLivegangFromIcon}>
                    <SidebarMenuButton
                      isActive={onLivegang}
                      tooltip="Livegang checklist"
                      className={itemClass}
                    >
                      <ListChecks />
                      <span>Livegang checklist</span>
                      <ChevronDown className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-180" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub className={subMenuClass}>
                      <SidebarMenuSubItem>
                        <SidebarMenuSubButton
                          asChild
                          isActive={pathname.startsWith(SEO_GEO_URL)}
                          className={subClass}
                        >
                          <Link href={hrefFor("seoGeo", SEO_GEO_URL)}>
                            <Search />
                            <span>SEO/GEO-scan</span>
                          </Link>
                        </SidebarMenuSubButton>
                      </SidebarMenuSubItem>
                      <SidebarMenuSubItem>
                        <SidebarMenuSubButton
                          asChild
                          isActive={pathname.startsWith(GOLIVE_URL)}
                          className={subClass}
                        >
                          <Link href={hrefFor("oplevering", GOLIVE_URL)}>
                            <ListChecks />
                            <span>Livegang</span>
                          </Link>
                        </SidebarMenuSubButton>
                      </SidebarMenuSubItem>
                      <SidebarMenuSubItem>
                        <SidebarMenuSubButton
                          asChild
                          isActive={pathname.startsWith(ANALYTICS_URL)}
                          className={subClass}
                        >
                          <Link href={hrefFor("analytics", ANALYTICS_URL)}>
                            <BarChart3 />
                            <span>Analytics</span>
                          </Link>
                        </SidebarMenuSubButton>
                      </SidebarMenuSubItem>
                    </SidebarMenuSub>
                  </CollapsibleContent>
                </SidebarMenuItem>
              </Collapsible>

              {/* Blog Generator Dropdown */}
              <Collapsible asChild className="group/collapsible">
                <SidebarMenuItem>
                  <CollapsibleTrigger asChild>
                    <SidebarMenuButton
                      tooltip="Blog Generator"
                      className={itemClass}
                    >
                      <FileText />
                      <span>Blog Generator</span>
                      <ChevronDown className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-180" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub className={subMenuClass}>
                      {blogItems.map((item) => {
                        const isActive = pathname === item.url;
                        return (
                          <SidebarMenuSubItem key={item.title}>
                            <SidebarMenuSubButton
                              asChild
                              isActive={isActive}
                              className={subClass}
                            >
                              <Link href={blogHref(item.url)}>
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
                      className={itemClass}
                    >
                      <Globe />
                      <span>Landingspagina&apos;s</span>
                      <ChevronDown className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-180" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub className={subMenuClass}>
                      {landingPageItems.map((item) => {
                        const isActive = pathname === item.url;
                        return (
                          <SidebarMenuSubItem key={item.title}>
                            <SidebarMenuSubButton
                              asChild
                              isActive={isActive}
                              className={subClass}
                            >
                              <Link href={landingPageHref(item.url)}>
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
                      className={`${itemClass} text-white/60`}
                    >
                      <Search />
                      <span>SEO Tools</span>
                      <span className={badgeClass}>Binnenkort</span>
                      <ChevronDown className="ml-1 transition-transform duration-200 group-data-[state=open]/collapsible:rotate-180" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub className={subMenuClass}>
                      {seoItems.map((item) => (
                        <SidebarMenuSubItem key={item.title}>
                          <SidebarMenuSubButton
                            aria-disabled
                            className={`${subClass} cursor-not-allowed opacity-50`}
                          >
                            <item.icon />
                            <span>{item.title}</span>
                            <span className={badgeClass}>Binnenkort</span>
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
                      className={`${itemClass} text-white/60`}
                    >
                      <ScanLine />
                      <span>Audit Tools</span>
                      <span className={badgeClass}>Binnenkort</span>
                      <ChevronDown className="ml-1 transition-transform duration-200 group-data-[state=open]/collapsible:rotate-180" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub className={subMenuClass}>
                      {auditItems.map((item) => (
                        <SidebarMenuSubItem key={item.title}>
                          <SidebarMenuSubButton
                            aria-disabled
                            className={`${subClass} cursor-not-allowed opacity-50`}
                          >
                            <item.icon />
                            <span>{item.title}</span>
                            <span className={badgeClass}>Binnenkort</span>
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
              isActive={pathname.startsWith("/dashboard/settings")}
              tooltip="Instellingen"
              className={itemClass}
            >
              <Link href="/dashboard/settings">
                <Settings />
                <span>Instellingen</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              size="lg"
              tooltip={user.email}
              className="cursor-default rounded-lg hover:bg-white/10 hover:text-white"
            >
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-white text-xs font-semibold text-black">
                {user.email.charAt(0).toUpperCase()}
              </span>
              <span className="flex min-w-0 flex-col gap-0.5 leading-none">
                <span className="truncate text-[13px] font-medium text-white">
                  {user.email}
                </span>
                <span className="text-xs text-white/50">Account</span>
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              tooltip="Uitloggen"
              className={itemClass}
            >
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
