"use client";

import { useEffect, useState } from "react";
import { Menu, Settings, LogIn, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useUser } from "@auth0/nextjs-auth0/client";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { NewChatButton } from "./NewChatButton";
import { ChatThreadList, type Thread } from "./ChatThreadList";
import { ConnectedMcpServers } from "@/components/settings/ConnectedMcpServers";
import { ModelReload } from "@/components/settings/ModelReload";
import { StreamingToggle } from "@/components/settings/StreamingToggle";

interface SidebarProps {
  threads: Thread[];
  activeId: string | null;
  onNewChat: () => void;
  onSelectThread: (id: string) => void;
}

const SIDEBAR_COLLAPSED_KEY = "sidebar-collapsed";

function SidebarContent({
  threads,
  activeId,
  onNewChat,
  onSelectThread,
  collapsed,
  onToggleCollapse,
}: SidebarProps & { collapsed?: boolean; onToggleCollapse?: () => void }) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined" && sessionStorage.getItem("mcp_oauth_return") === "1") {
      sessionStorage.removeItem("mcp_oauth_return");
      setSettingsOpen(true);
    }
  }, []);

  if (collapsed) {
    return (
      <div className="flex h-full w-12 flex-col items-stretch border-r border-sidebar-border bg-sidebar">
        <button
          type="button"
          onClick={onToggleCollapse}
          aria-label="Expand sidebar"
          className="flex shrink-0 items-center justify-center border-b border-sidebar-border p-3 hover:bg-sidebar-accent"
        >
          <Menu className="h-5 w-5" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full w-64 flex-col border-r border-sidebar-border bg-sidebar">
      <div className="flex items-center gap-2 border-b border-sidebar-border p-2">
        {onToggleCollapse && (
          <button
            type="button"
            onClick={onToggleCollapse}
            aria-label="Collapse sidebar"
            className="flex shrink-0 items-center justify-center rounded-md p-2 hover:bg-sidebar-accent"
          >
            <Menu className="h-5 w-5" />
          </button>
        )}
        <NewChatButton onClick={onNewChat} />
      </div>
      <div className="px-2 py-1">
        <p className="text-xs font-medium text-muted-foreground">Chats</p>
      </div>
      <ChatThreadList
        threads={threads}
        activeId={activeId}
        onSelect={onSelectThread}
      />
      <div className="mt-auto space-y-1 border-t border-sidebar-border p-2">
        <Sheet open={settingsOpen} onOpenChange={setSettingsOpen}>
          <SheetTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
            >
              <Settings className="h-4 w-4" />
              Settings & help
            </button>
          </SheetTrigger>
          <SheetContent side="right" className="flex w-[min(440px,95vw)] max-w-none flex-col gap-0 overflow-y-auto p-0 sm:max-w-none">
            <div className="sticky top-0 z-10 border-b bg-background px-6 py-4">
              <h2 className="text-lg font-semibold">Settings</h2>
            </div>
            <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
              <section className="rounded-lg border bg-muted/30 p-4">
                <StreamingToggle />
              </section>
              <section className="rounded-lg border bg-muted/30 p-4">
                <ModelReload />
              </section>
              <section className="rounded-lg border bg-muted/30 p-4">
                <ConnectedMcpServers />
              </section>
            </div>
          </SheetContent>
        </Sheet>
        <AuthButtons />
      </div>
    </div>
  );
}

function AuthButtons() {
  if (process.env.NEXT_PUBLIC_AUTH_DISABLED === "true") return null;
  const { user, isLoading } = useUser();
  if (isLoading) return null;
  if (user) {
    return (
      <a
        href="/auth/logout"
        className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
      >
        <LogOut className="h-4 w-4" />
        Log out
      </a>
    );
  }
  return (
    <a
      href="/auth/login"
      className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
    >
      <LogIn className="h-4 w-4" />
      Log in
    </a>
  );
}

export function Sidebar(props: SidebarProps) {
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1");
  }, []);

  const toggleCollapse = () => {
    setCollapsed((c) => {
      const next = !c;
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
      return next;
    });
  };

  return (
    <>
      <div className="hidden shrink-0 md:block">
        <SidebarContent
          {...props}
          collapsed={collapsed}
          onToggleCollapse={toggleCollapse}
        />
      </div>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button variant="ghost" size="icon" className="md:hidden">
            <Menu className="h-5 w-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-64 p-0">
          <SidebarContent
            {...props}
            onSelectThread={(id) => {
              props.onSelectThread(id);
              setOpen(false);
            }}
          />
        </SheetContent>
      </Sheet>
    </>
  );
}
