import { useSyncExternalStore } from "react";

/** True while the media query matches (e.g. laptop layout). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", cb);
      return () => list.removeEventListener("change", cb);
    },
    () => window.matchMedia(query).matches,
  );
}
