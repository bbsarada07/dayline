import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router";
import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { homeFor, useMe } from "@/lib/auth";
import { useRealtime } from "@/lib/realtime";
import type { Role } from "@/lib/types";
import { ErrorState } from "@/components/states";
import { SessionWatch } from "@/components/SessionWatch";
import { Skeleton } from "@/components/ui/skeleton";
import { buttonVariants } from "@/components/ui/button";
import { Brand, StaffLayout, StudentLayout } from "./layouts";
import { LoginPage } from "@/features/auth/LoginPage";
import { TodayPage } from "@/features/today/TodayPage";
import { AttendancePage } from "@/features/attendance/AttendancePage";
import { ProfilePage } from "@/features/profile/ProfilePage";
import { AdminPage } from "@/features/admin/AdminPage";
import { StaffHomePage } from "@/features/staff/StaffHomePage";
import { PrintPage } from "@/features/print/PrintPage";
import { CanteenPage } from "@/features/canteen/CanteenPage";
import { MemoryPage } from "@/features/memory/MemoryPage";

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    // A 401 anywhere means the session ended: drop to the login screen.
    onError: (error, query) => {
      if (error instanceof ApiError && error.status === 401 && query.queryKey[0] !== "me") {
        queryClient.setQueryData(["me"], null);
      }
    },
  }),
  defaultOptions: {
    queries: {
      retry: (count, error) => count < 1 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
      staleTime: 30_000,
    },
  },
});

function FullPageLoading() {
  return (
    <div className="mx-auto max-w-lg space-y-3 p-6" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-20" />
      <Skeleton className="h-20" />
    </div>
  );
}

/** Only lets `roles` through; everyone else goes to login or their own home. */
function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const me = useMe();
  if (me.isPending) return <FullPageLoading />;
  if (me.isError) {
    return (
      <div className="mx-auto max-w-lg p-6">
        <ErrorState error={me.error} onRetry={() => me.refetch()} />
      </div>
    );
  }
  if (!me.data) return <Navigate to="/login" replace />;
  if (!roles.includes(me.data.role)) return <Navigate to={homeFor(me.data.role)} replace />;
  return children;
}

function NotFound() {
  return (
    <div className="mx-auto max-w-lg p-6 pt-16 text-center">
      <p aria-hidden className="misprint font-display text-64 font-extrabold">404</p>
      <h1 className="mt-2 text-28 font-extrabold">This page doesn't exist</h1>
      <p className="mt-2 text-muted">The link may be old or mistyped.</p>
      <Link to="/" className={buttonVariants({ className: "mt-6" })}>
        Go to your home screen
      </Link>
    </div>
  );
}

const BOOT_RETRY_MS = 3_000;
const BOOT_PATIENCE_MS = 60_000;

/**
 * First load. A free host may be waking the server up, so the first request can take up
 * to a minute or fail outright: keep asking every few seconds, and offer Retry after a minute.
 * Once the server has answered once, the app renders and later errors are handled per screen.
 */
function BootGate({ children }: { children: ReactNode }) {
  const me = useMe();
  const [started] = useState(() => Date.now());
  const [waitedLong, setWaitedLong] = useState(false);
  const answered = me.isSuccess || (me.isError && me.error instanceof ApiError && me.error.status > 0 && me.error.status < 500);

  useEffect(() => {
    if (answered) return;
    const patience = setTimeout(() => setWaitedLong(true), Math.max(0, BOOT_PATIENCE_MS - (Date.now() - started)));
    return () => clearTimeout(patience);
  }, [answered, started]);

  useEffect(() => {
    if (answered || !me.isError) return;
    const retry = setTimeout(() => me.refetch(), BOOT_RETRY_MS);
    return () => clearTimeout(retry);
  }, [answered, me.isError, me.errorUpdatedAt, me]);

  if (answered) return children;
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-5 p-6 text-center" aria-busy="true">
      <Brand className="text-40" />
      <p role="status" className="max-w-xs text-17 font-semibold text-muted">
        Starting Dayline. This can take up to a minute.
      </p>
      <span aria-hidden className="pulse-dot size-3 rounded-full bg-magenta" />
      {waitedLong ? (
        <button type="button" onClick={() => me.refetch()} className={buttonVariants()}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

function Realtime() {
  const me = useMe().data;
  useRealtime(me ? `${me.kind}-${me.id}` : "anonymous");
  return null;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <BootGate>
          <Realtime />
          <SessionWatch />
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              element={
                <RequireRole roles={["student"]}>
                  <StudentLayout />
                </RequireRole>
              }
            >
              <Route index element={<TodayPage />} />
              <Route path="canteen" element={<CanteenPage />} />
              <Route path="print" element={<PrintPage />} />
              <Route path="attendance" element={<AttendancePage />} />
              <Route path="memory" element={<MemoryPage />} />
              <Route path="profile" element={<ProfilePage />} />
            </Route>
            <Route
              element={
                <RequireRole roles={["admin"]}>
                  <StaffLayout />
                </RequireRole>
              }
            >
              <Route path="admin" element={<AdminPage />} />
            </Route>
            <Route
              element={
                <RequireRole roles={["canteen", "print"]}>
                  <StaffLayout />
                </RequireRole>
              }
            >
              <Route path="staff" element={<StaffHomePage />} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BootGate>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
