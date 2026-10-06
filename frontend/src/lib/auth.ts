import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./api";
import { announceSession } from "./session";
import type { Me, Role } from "./types";

/** The logged-in user, or null when logged out. */
export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<Me>("/auth/me");
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 5 * 60_000,
  });
}

export function homeFor(role: Role): string {
  if (role === "student") return "/";
  if (role === "admin") return "/admin";
  return "/staff";
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { kind: "student" | "staff"; username: string; pin: string }) =>
      api<Me>("/auth/login", { method: "POST", body }),
    onSuccess: (me) => {
      client.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" && q.queryKey[0] !== "clock" });
      client.setQueryData(["me"], me);
      announceSession(me);
    },
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api("/auth/logout", { method: "POST" }),
    onSuccess: () => {
      client.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" && q.queryKey[0] !== "clock" });
      client.setQueryData(["me"], null);
      announceSession(null);
    },
  });
}
