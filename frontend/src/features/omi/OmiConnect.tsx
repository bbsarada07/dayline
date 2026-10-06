import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, CircleAlert, Mic, Radio } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, errorMessage } from "@/lib/api";
import type { OmiStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CopyField, OmiActivity, useOmiStatus } from "./omiShared";

/** Profile → Connect Omi: the student's Omi id, the two webhook URLs to paste into Omi, and setup steps. */
export function OmiConnect() {
  const client = useQueryClient();
  const status = useOmiStatus();
  const [uid, setUid] = useState("");
  const save = useMutation({
    mutationFn: (value: string) => api<OmiStatus>("/omi/connect", { method: "PUT", body: { uid: value } }),
    onSuccess: (data) => {
      client.setQueryData(["omi", "status"], data);
      setUid("");
    },
  });
  const remove = useMutation({
    mutationFn: () => api<OmiStatus>("/omi/connect", { method: "DELETE" }),
    onSuccess: (data) => client.setQueryData(["omi", "status"], data),
  });

  const onSave = (event: FormEvent) => {
    event.preventDefault();
    if (uid.trim()) save.mutate(uid.trim());
  };

  const s = status.data;
  const real = s?.connected && !s.is_demo_uid;
  return (
    <section aria-labelledby="omi-heading" className="rounded-[18px] border-2 border-edge bg-sheet p-4 shadow-hard">
      <div className="flex items-start justify-between gap-3">
        <h2 id="omi-heading" className="flex items-center gap-2.5 font-display text-21 font-extrabold">
          <span className="flex size-10 -rotate-6 items-center justify-center rounded-[11px] border-2 border-edge bg-hero text-hero-text">
            <Mic className="size-5" aria-hidden />
          </span>
          Connect Omi
        </h2>
        {s ? (
          <span
            className={cn(
              "shrink-0 rounded-full border-2 px-2.5 py-0.5 text-13 font-extrabold",
              real ? "border-stamp-text text-stamp-text" : "border-line text-muted",
            )}
          >
            {real ? "Connected" : s.connected ? "Demo id" : "Not connected"}
          </span>
        ) : null}
      </div>
      <p className="mt-2 font-semibold text-muted">
        Say “Hey Dayline” to your Omi and Dayline answers on your phone. When a conversation ends, Dayline keeps what
        matters (deadlines, things to print, food you like), never the conversation itself.
      </p>

      {status.isPending ? (
        <Skeleton className="mt-4 h-40" />
      ) : status.isError || !s ? (
        <p className="mt-4 font-semibold text-alert-text">Omi settings didn't load. {errorMessage(status.error)}</p>
      ) : (
        <div className="mt-4 space-y-5">
          <div>
            {s.connected ? (
              <p className="font-semibold">
                Omi user id: <code className="rounded-[6px] bg-tint px-1.5 py-0.5 font-mono text-13">{s.omi_uid}</code>
              </p>
            ) : null}
            {s.is_demo_uid ? (
              <p className="mt-1 text-13 font-semibold text-muted">
                A pretend id, so the Omi simulator works without a device. Paste your real Omi id to use your phone.
              </p>
            ) : null}
            <form onSubmit={onSave} className="mt-3">
              <Label htmlFor="omi-uid">{s.connected ? "Change Omi user id" : "Your Omi user id"}</Label>
              <div className="mt-1.5 flex gap-2">
                <Input
                  id="omi-uid"
                  value={uid}
                  onChange={(e) => {
                    setUid(e.target.value);
                    if (save.isError) save.reset();
                  }}
                  placeholder="From Omi → Settings → Developer Settings"
                  autoComplete="off"
                  maxLength={128}
                />
                <Button type="submit" disabled={!uid.trim() || save.isPending}>
                  {save.isPending ? "Saving…" : "Save"}
                </Button>
              </div>
            </form>
            {save.isError || remove.isError ? (
              <p role="alert" className="mt-2 flex items-start gap-1.5 text-13 font-bold text-alert-text">
                <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {errorMessage(save.error ?? remove.error)}
              </p>
            ) : null}
            <div className="mt-2 flex flex-wrap gap-2">
              {s.demo_uid && s.omi_uid !== s.demo_uid ? (
                <Button variant="secondary" onClick={() => save.mutate(s.demo_uid!)} disabled={save.isPending}>
                  Use the demo id
                </Button>
              ) : null}
              {s.connected ? (
                <Button variant="ghost" onClick={() => remove.mutate()} disabled={remove.isPending}>
                  Disconnect
                </Button>
              ) : null}
            </div>
          </div>

          <div className="space-y-3">
            <CopyField
              label="1. Real-time transcript webhook"
              hint="For the private “Dayline” app you create in Omi (trigger: Transcript Processed)."
              value={s.urls.transcript}
            />
            <CopyField
              label="2. Memory creation webhook"
              hint="For Omi → Settings → Developer Settings → Memory Creation Webhook."
              value={s.urls.memory}
            />
            <p className="text-13 font-semibold text-muted">
              These links are private to you: they only work with the Omi id saved above.
            </p>
          </div>

          <details className="rounded-[12px] border-2 border-line p-3">
            <summary className="cursor-pointer font-extrabold">Setup steps in the Omi app</summary>
            <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-15 font-semibold">
              <li>In Omi, open Settings and turn on <b>Developer Mode</b>. Copy your user id from <b>Developer Settings</b> and save it above.</li>
              <li>Go to <b>Explore</b> and create a new app called “Dayline”. Keep it <b>Private</b>.</li>
              <li>Choose the capability <b>External Integration</b> with the trigger <b>Transcript Processed</b>, and paste webhook 1.</li>
              <li>Install or enable the app for yourself. Its App ID and an API key go on the Dayline server as OMI_APP_ID and OMI_APP_SECRET, so replies reach your phone.</li>
              <li>In <b>Developer Settings → Memory Creation Webhook</b>, paste webhook 2.</li>
              <li>Start a recording in Omi (no wearable needed: the phone's microphone works) and say “Hey Dayline, what's my next class?”</li>
            </ol>
          </details>

          <p className="flex items-start gap-2 text-13 font-semibold">
            <Radio className="mt-0.5 size-4 shrink-0" aria-hidden />
            {s.notifications_configured
              ? "Replies are sent to your Omi app as notifications."
              : "Replies show in Dayline only: the server doesn't have the Omi app's id and key yet."}{" "}
            Wake phrase: “{s.wake_phrases.join("”, “")}”.
          </p>

          {s.simulator ? (
            <Link
              to="/omi-simulator"
              className="press flex items-center gap-3 rounded-[14px] border-2 border-edge bg-hero p-3 text-hero-text shadow-hard-sm"
            >
              <Mic className="size-5 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block font-display text-17 font-extrabold">Try the Omi simulator</span>
                <span className="block text-13 font-semibold text-hero-muted">No device needed: sends the same webhook calls Omi sends</span>
              </span>
              <ChevronRight className="size-5 shrink-0" aria-hidden />
            </Link>
          ) : null}

          <div>
            <h3 className="font-display text-17 font-extrabold">Recent Omi activity</h3>
            <OmiActivity limit={6} className="mt-2" />
          </div>
        </div>
      )}
    </section>
  );
}
