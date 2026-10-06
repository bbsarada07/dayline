import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type SheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
};

/** Bottom sheet on phones, centred card on wider screens. */
export function Sheet({ open, onOpenChange, title, description, children }: SheetProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[rgb(10_11_38/0.55)]" />
        <Dialog.Content
          className={cn(
            "fixed inset-x-0 bottom-0 z-50 max-h-[88dvh] overflow-y-auto rounded-t-[22px] border-t-2 border-edge bg-sheet p-5 pb-[max(20px,env(safe-area-inset-bottom))]",
            "sm:inset-x-auto sm:top-1/2 sm:bottom-auto sm:left-1/2 sm:w-[min(500px,calc(100vw-32px))] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-[18px] sm:border-2 sm:shadow-hard-lg",
          )}
        >
          <div aria-hidden className="mx-auto -mt-1 mb-3 h-1.5 w-12 rounded-full bg-line sm:hidden" />
          <div className="mb-4 flex items-start justify-between gap-4">
            <div className="min-w-0">
              <Dialog.Title className="font-display text-28 font-extrabold">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="mt-1 text-15 text-muted">{description}</Dialog.Description>
              ) : (
                <Dialog.Description className="sr-only">{title}</Dialog.Description>
              )}
            </div>
            <Dialog.Close className="press inline-flex size-11 shrink-0 items-center justify-center rounded-button border-2 border-edge bg-sheet shadow-hard-sm">
              <X className="size-5" aria-hidden />
              <span className="sr-only">Close</span>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
