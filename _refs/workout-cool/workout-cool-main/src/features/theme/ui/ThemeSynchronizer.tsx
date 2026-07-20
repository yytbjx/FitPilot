"use client";

import { useEffect } from "react";
import { useTheme } from "next-themes";

/**
 * Synchronizes the <meta name="theme-color"> tag with the current theme (light/dark).
 * Ensures the browser UI (mobile address bar, etc.) matches the user's selected theme.
 */
export function ThemeSynchronizer() {
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    const themeColor = resolvedTheme === "dark" ? "#18181b" : "#f3f4f6";
    let meta = document.querySelector("meta[name=theme-color]");
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "theme-color");
      document.head.appendChild(meta);
    }
    meta.setAttribute("content", themeColor);
  }, [resolvedTheme]);

  return null;
}
