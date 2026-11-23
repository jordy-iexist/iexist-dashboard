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
  ListChecks,
  Swords,
  Newspaper,
  Globe,
  Radar,
  ChartLine,
  ChevronLeft,
  ChevronRight,
  List,
  type LucideIcon,
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
  sectionFromPathname,
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

const CUSTOMERS_URL = "/dashboard/klanten";
const SEO_GEO_URL = "/dashboard/livegang/seo-geo";
const GOLIVE_URL = "/dashboard/livegang/oplevering";
const ANALYTICS_URL = "/dashboard/livegang/analytics";

const BLOGS_URL = "/dashboard/blogs";
const BLOG_UPLOAD_URL = "/dashboard/blogs/upload";

// Shopify-admin look: compact items, light pill for active, no sub-menu guide line
const itemClass =
  "h-8 rounded-lg text-[13px] font-medium text-white/85 hover:bg-white/10 hover:text-white data-[active=true]:bg-white/10 data-[active=true]:font-semibold data-[active=true]:text-white [&>svg]:text-white/70 data-[active=true]:[&>svg]:text-white";
const subClass =
  "h-7 rounded-lg text-[13px] text-white/70 hover:bg-white/10 hover:text-white data-[active=true]:bg-white/10 data-[active=true]:font-semibold data-[active=true]:text-white [&>svg]:text-white/60 data-[active=true]:[&>svg]:text-white";
const subMenuClass = "ml-3.5 border-l-0 pl-1.5";

type NavLeafItem = {
  title: string;
  /** Adres waarop het item actief is (prefix). */
  url: string;
  /** Adres waar de link heen gaat (kan de actieve klant bevatten). */
  href: string;
  icon: LucideIcon;
};

type NavGroupItem = NavLeafItem & {
  /** Derde niveau: verschijnt in een eigen paneel rechts naast de sidebar. */
  children?: NavLeafItem[];
};

type NavGroupConfig = {
  title: string;
  icon: LucideIcon;
  items: NavGroupItem[];
};

// Het item met het langste passende adres is actief, zodat een subpagina
// (bijv. /blogs/upload) niet ook het bovenliggende item (/blogs) oplicht.
function activeItemUrl(items: NavLeafItem[], pathname: string) {
  return (
    items
      .map((item) => item.url)
      .filter((url) => pathname.startsWith(url))
      .sort((a, b) => b.length - a.length)[0] ?? null
  );
}

// Uitklapbare kop in het menu. Staat open op de eigen pagina's, ook als je er
// vanaf een andere pagina naartoe navigeert (de sidebar blijft dan gemount).
function NavGroup({
  group,
  pathname,
  onOpenSubNav,
}: {
  group: NavGroupConfig;
  pathname: string;
  /** Klik op een item met een derde niveau: het paneel (weer) openen. */
  onOpenSubNav: (url: string) => void;
}) {
  const { state, isMobile, setOpen } = useSidebar();

  // Op mobiel is er geen ruimte voor het paneel rechts: daar staan de items
  // van het derde niveau gewoon in de groep zelf.
  const items: NavGroupItem[] = isMobile
    ? group.items.flatMap((item) => item.children ?? [item])
    : group.items;
  const activeUrl = activeItemUrl(items, pathname);
  const onGroup = activeUrl !== null;

  const [groupOpen, setGroupOpen] = React.useState(onGroup);
  const [wasOnGroup, setWasOnGroup] = React.useState(onGroup);
  if (onGroup !== wasOnGroup) {
    setWasOnGroup(onGroup);
    if (onGroup) setGroupOpen(true);
  }

  // Ingeklapt tot iconen is het submenu verborgen: klappen we dan alleen de groep
  // open, dan gebeurt er zichtbaar niets. Daarom eerst de sidebar uitklappen.
  const openFromIcon = (event: React.MouseEvent) => {
    if (state !== "collapsed" || isMobile) return;
    event.preventDefault();
    setOpen(true);
    setGroupOpen(true);
  };

  return (
    <Collapsible
      asChild
      open={groupOpen}
      onOpenChange={setGroupOpen}
      className="group/collapsible"
    >
      <SidebarMenuItem>
        <CollapsibleTrigger asChild onClick={openFromIcon}>
          <SidebarMenuButton
            isActive={onGroup}
            tooltip={group.title}
            className={itemClass}
          >
            <group.icon />
            <span>{group.title}</span>
            <ChevronDown className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-180" />
          </SidebarMenuButton>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <SidebarMenuSub className={subMenuClass}>
            {items.map((item) => (
              <SidebarMenuSubItem key={item.url}>
                <SidebarMenuSubButton
                  asChild
                  isActive={item.url === activeUrl}
                  className={subClass}
                >
                  <Link
                    href={item.href}
                    onClick={
                      item.children ? () => onOpenSubNav(item.url) : undefined
                    }
                  >
                    <item.icon />
                    <span>{item.title}</span>
                    {item.children && <ChevronRight className="ml-auto" />}
                  </Link>
                </SidebarMenuSubButton>
              </SidebarMenuSubItem>
            ))}
          </SidebarMenuSub>
        </CollapsibleContent>
      </SidebarMenuItem>
    </Collapsible>
  );
}

// Paneel voor het derde niveau, vast tegen de rechterkant van de sidebar.
// Staat zichtbaar zolang je op een pagina van het bovenliggende item bent.
function SubNavPanel({
  item,
  pathname,
  onClose,
}: {
  item: NavGroupItem;
  pathname: string;
  onClose: () => void;
}) {
  const children = item.children ?? [];
  const activeUrl = activeItemUrl(children, pathname);
  return (
    <aside
      aria-label={item.title}
      className="sticky top-0 hidden h-svh w-52 shrink-0 flex-col border-l border-white/10 bg-sidebar p-2 text-sidebar-foreground md:flex"
    >
      <div className="flex h-10 items-center gap-2 px-2">
        <item.icon className="size-4 text-white/70" />
        <span className="truncate text-sm font-semibold text-white">
          {item.title}
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label={`${item.title}-menu sluiten`}
          title="Menu sluiten"
          className="ml-auto flex size-7 items-center justify-center rounded-lg text-white/70 hover:bg-white/10 hover:text-white"
        >
          <ChevronLeft className="size-4" />
        </button>
      </div>
      <SidebarMenu className="mt-2">
        {children.map((child) => (
          <SidebarMenuItem key={child.url}>
            <SidebarMenuButton
              asChild
              isActive={child.url === activeUrl}
              className={itemClass}
            >
              <Link href={child.href}>
                <child.icon />
                <span>{child.title}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </aside>
  );
}

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
    getServerTabCustomerId,
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
    fallback: string,
  ) => (activeCustomerId ? customerHref(section, activeCustomerId) : fallback);
  const customerHomePath = activeCustomerId
    ? customerHref("home", activeCustomerId)
    : null;
  // De concurrentieanalyse staat onder de klantpagina, maar heeft een eigen menu-item.
  const onAnalyses = sectionFromPathname(pathname) === "analyses";
  const isPathActive = (url: string): boolean => {
    if (url === "/dashboard") {
      return (
        pathname === "/dashboard" ||
        (customerHomePath !== null &&
          !onAnalyses &&
          (pathname === customerHomePath ||
            pathname.startsWith(`${customerHomePath}/`)))
      );
    }
    return pathname.startsWith(url);
  };
  const menuHref = (url: string) =>
    url === "/dashboard" ? hrefFor("home", url) : url;

  const navGroups: NavGroupConfig[] = [
    {
      title: "Website",
      icon: Globe,
      items: [
        {
          title: "Livegang",
          url: GOLIVE_URL,
          href: hrefFor("oplevering", GOLIVE_URL),
          icon: ListChecks,
        },
      ],
    },
    {
      title: "Vindbaarheid",
      icon: Radar,
      items: [
        {
          title: "SEO/GEO-scan",
          url: SEO_GEO_URL,
          href: hrefFor("seoGeo", SEO_GEO_URL),
          icon: Search,
        },
      ],
    },
    {
      title: "Content",
      icon: Newspaper,
      items: [
        {
          title: "Blogs",
          url: BLOGS_URL,
          href: hrefFor("blogs", BLOGS_URL),
          icon: FileText,
          children: [
            {
              title: "Alle blogs",
              url: BLOGS_URL,
              href: hrefFor("blogs", BLOGS_URL),
              icon: List,
            },
            {
              title: "Blog CSV-upload",
              url: BLOG_UPLOAD_URL,
              href: BLOG_UPLOAD_URL,
              icon: Upload,
            },
          ],
        },
      ],
    },
    {
      title: "Rapportage",
      icon: BarChart3,
      items: [
        {
          title: "Analytics",
          url: ANALYTICS_URL,
          href: hrefFor("analytics", ANALYTICS_URL),
          icon: ChartLine,
        },
      ],
    },
  ];

  // Staat je op een pagina van een item met een derde niveau, dan komt dat
  // niveau in een eigen paneel rechts naast de sidebar.
  const subNavItem = navGroups
    .flatMap((group) => group.items)
    .find((item) => item.children && pathname.startsWith(item.url));
  const subNavUrl = subNavItem?.url ?? null;

  // Het paneel kan dicht met het pijltje. Het gaat weer open als je in het
  // menu op het item klikt, of als je de sectie verlaat en later terugkomt.
  const [closedSubNavUrl, setClosedSubNavUrl] = React.useState<string | null>(
    null,
  );
  const [prevSubNavUrl, setPrevSubNavUrl] = React.useState(subNavUrl);
  if (subNavUrl !== prevSubNavUrl) {
    setPrevSubNavUrl(subNavUrl);
    setClosedSubNavUrl(null);
  }
  const showSubNav = subNavItem && closedSubNavUrl !== subNavItem.url;

  return (
    <>
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

                <SidebarMenuItem>
                  <SidebarMenuButton
                    asChild
                    isActive={onAnalyses}
                    tooltip="Concurrentieanalyse"
                    className={itemClass}
                  >
                    <Link href={hrefFor("analyses", CUSTOMERS_URL)}>
                      <Swords />
                      <span>Concurrentieanalyse</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>

                {navGroups.map((group) => (
                  <NavGroup
                    key={group.title}
                    group={group}
                    pathname={pathname}
                    onOpenSubNav={() => setClosedSubNavUrl(null)}
                  />
                ))}
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
      {showSubNav && (
        <SubNavPanel
          item={subNavItem}
          pathname={pathname}
          onClose={() => setClosedSubNavUrl(subNavItem.url)}
        />
      )}
    </>
  );
}
