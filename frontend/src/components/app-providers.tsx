"use client";

import { ReactNode } from "react";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import { CommandPalette } from "@/components/command-palette";
import { AppWebSocketProvider } from "@/contexts/app-websocket-context";
import { AuthProvider } from "@/contexts/auth-context";

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      <AuthProvider>
        <AppWebSocketProvider>
          {children}
        </AppWebSocketProvider>
      </AuthProvider>
      <Toaster />
      <CommandPalette />
    </ThemeProvider>
  );
}
