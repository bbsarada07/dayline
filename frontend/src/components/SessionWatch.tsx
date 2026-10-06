import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { onSessionChange, secondLoginUrl, type SessionMessage } from "@/lib/session";
import type { Me } from "@/lib/types";

const ROLE = { student: "student", canteen: "canteen staff", print: "print shop", admin: "admin" } as const;

/**
 * One browser holds one login. When another tab logs in or out, this tab says so
 * plainly and follows, instead of quietly showing an old account's data.
 */
export function SessionWatch() {
  const client = useQueryClient();
  const [change, setChange] = useState<SessionMessage | null>(null);

  useEffect(
    () =>
      onSessionChange((message) => {
        const current = client.getQueryData<Me | null>(["me"]);
        const same = message.me && current && message.me.kind === current.kind && message.me.id === current.id;
        if (same || (!message.me && !current)) return;
        client.removeQueries({ predicate: (q) => q.queryKey[0] !== "clock" });
        client.invalidateQueries({ queryKey: ["me"] });
        // Explain when this tab was showing someone, and keep the notice current
        // if the other tab logs out and then in as someone else.
        setChange((open) => (current || open ? message : open));
      }),
    [client],
  );

  const second = secondLoginUrl();
  const who = change?.me;

  return (
    <Sheet
      open={change !== null}
      onOpenChange={(open) => !open && setChange(null)}
      title={who ? `Now logged in as ${who.name}` : "You logged out in another tab"}
      description={
        who
          ? `Another tab logged in as ${who.name} (${ROLE[who.role]}). A browser keeps one login at a time, so this tab switched too.`
          : "A browser keeps one login at a time, so this tab is logged out too."
      }
    >
      <div className="rounded-surface border-2 border-dashed border-edge p-4">
        <p className="font-bold">Want two accounts side by side?</p>
        <p className="mt-1 text-muted">
          {second
            ? "Open the second account at this computer's other address. It keeps its own login."
            : "Open the second account in a private window or another browser."}
        </p>
        {second ? (
          <a href={second} target="_blank" rel="noopener" className={buttonVariants({ variant: "secondary", className: "mt-3" })}>
            <ExternalLink aria-hidden /> Open a second login
          </a>
        ) : null}
      </div>
      <Button size="lg" className="mt-4 w-full" onClick={() => setChange(null)}>
        {who ? `Continue as ${who.name}` : "Go to log in"}
      </Button>
    </Sheet>
  );
}
