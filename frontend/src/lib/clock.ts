import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { ClockInfo } from "./types";

/**
 * App time, synced with the server clock service (which may be in demo time).
 * Between syncs it ticks locally from the last server reading.
 */
export function useClock(tickMs = 15_000) {
  const query = useQuery({
    queryKey: ["clock"],
    queryFn: () => api<ClockInfo>("/clock"),
    refetchInterval: 5 * 60_000,
    staleTime: 60_000,
  });
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), tickMs);
    return () => clearInterval(id);
  }, [tickMs]);

  const data = query.data;
  const now = data ? new Date(new Date(data.now).getTime() + (Date.now() - query.dataUpdatedAt)) : null;
  return { now, demo: data?.demo ?? false, query };
}
