import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "press inline-flex shrink-0 items-center justify-center gap-2 rounded-button font-bold whitespace-nowrap disabled:opacity-55 [&_svg]:size-[18px] [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "border-2 border-edge bg-ink text-paper shadow-hard-sm",
        secondary: "border-2 border-edge bg-sheet text-ink shadow-hard-sm hover:bg-tint",
        ghost: "text-ink hover:bg-tint active:bg-tint",
        hero: "border-2 border-hero-text bg-hero-text text-hero shadow-[3px_3px_0_0_var(--magenta)]",
      },
      size: {
        md: "min-h-11 px-4 text-15",
        lg: "min-h-13 px-5 text-17",
        icon: "size-11",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>;

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, type = "button", ...props },
  ref,
) {
  return <button ref={ref} type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
});

export { buttonVariants };
