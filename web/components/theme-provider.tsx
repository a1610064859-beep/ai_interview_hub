"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type AppTheme = "day" | "night";

const THEME_STORAGE_KEY = "ai-interview-hub-theme";
const ThemeContext = createContext<{ theme: AppTheme; setTheme: (theme: AppTheme) => void } | null>(null);

function readSavedTheme(): AppTheme {
  try {
    const savedCookie = document.cookie
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith(`${THEME_STORAGE_KEY}=`));
    if (savedCookie) return savedCookie.slice(THEME_STORAGE_KEY.length + 1) === "night" ? "night" : "day";
  } catch {
    // Continue to localStorage when cookies are unavailable.
  }

  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY) === "night" ? "night" : "day";
  } catch {
    return "day";
  }
}

function saveTheme(next: AppTheme) {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    // Keep the current page usable when browser storage is unavailable.
  }

  try {
    document.cookie = `${THEME_STORAGE_KEY}=${next}; Max-Age=31536000; Path=/; SameSite=Lax`;
  } catch {
    // The preference still applies for this page even when persistent storage is blocked.
  }
}

export function useAppTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useAppTheme must be used inside ThemeProvider");
  return context;
}

export default function ThemeProvider({
  children,
  initialTheme,
}: {
  children: ReactNode;
  initialTheme: AppTheme;
}) {
  const [theme, setThemeState] = useState<AppTheme>(initialTheme);

  const setTheme = useCallback((next: AppTheme) => {
    setThemeState(next);
    document.documentElement.dataset.theme = next;
    saveTheme(next);
  }, []);

  useEffect(() => {
    const initial = readSavedTheme();
    setThemeState(initial);
    document.documentElement.dataset.theme = initial;

    const metaTheme = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    if (metaTheme) metaTheme.content = initial === "day" ? "#f7f8fc" : "#070b14";
  }, []);

  useEffect(() => {
    const metaTheme = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    if (metaTheme) metaTheme.content = theme === "day" ? "#f7f8fc" : "#070b14";
  }, [theme]);

  const contextValue = useMemo(() => ({ theme, setTheme }), [theme, setTheme]);

  return (
    <ThemeContext.Provider value={contextValue}>
      {children}
      <button
        type="button"
        className="theme-toggle"
        onClick={() => setTheme(theme === "day" ? "night" : "day")}
        aria-label={`切换到${theme === "day" ? "夜间" : "日间"}模式`}
        aria-pressed={theme === "night"}
        title={`切换到${theme === "day" ? "夜间" : "日间"}模式`}
      >
        <svg className="theme-toggle-icon" viewBox="0 0 24 24" aria-hidden="true">
          {theme === "day" ? (
            <path d="M20.1 15.3A8.3 8.3 0 0 1 8.7 3.9 8.7 8.7 0 1 0 20.1 15.3Z" />
          ) : (
            <>
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" />
            </>
          )}
        </svg>
        <span>{theme === "day" ? "日间" : "夜间"}</span>
      </button>
    </ThemeContext.Provider>
  );
}
