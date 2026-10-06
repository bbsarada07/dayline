import { useCallback, useEffect, useState } from "react";

export type ThemePref = "light" | "dark" | "system";

const KEY = "theme";
const media = () => window.matchMedia("(prefers-color-scheme: dark)");

function read(): ThemePref {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function apply(pref: ThemePref) {
  const dark = pref === "dark" || (pref === "system" && media().matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

/** Light, dark or follow the device. Saved per browser. */
export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(read);

  useEffect(() => {
    apply(pref);
    if (pref !== "system") return;
    const query = media();
    const onChange = () => apply("system");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [pref]);

  const choose = useCallback((next: ThemePref) => {
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* storage unavailable: the choice still applies for this visit */
    }
    setPref(next);
  }, []);

  return { pref, choose };
}

/**
 * Boards (kitchen) default to dark. A choice the person saved still wins.
 * Restores the normal theme when the board unmounts.
 */
export function useBoardTheme() {
  useEffect(() => {
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(KEY);
    } catch {
      /* storage unavailable */
    }
    if (saved === null) document.documentElement.dataset.theme = "dark";
    return () => apply(read());
  }, []);
}
