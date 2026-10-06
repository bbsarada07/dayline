import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      className={cn(
        "min-h-12 w-full rounded-button border-2 border-edge bg-sheet px-3 text-17 font-semibold text-ink placeholder:font-normal placeholder:text-muted",
        "focus-visible:shadow-hard-sm aria-[invalid=true]:border-alert",
        className,
      )}
      {...props}
    />
  );
});

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("block text-15 font-bold text-ink", className)} {...props} />;
}
