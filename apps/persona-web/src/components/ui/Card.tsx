import type { HTMLAttributes } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  raised?: boolean;
  interactive?: boolean;
}

export function Card({
  raised = false,
  interactive = false,
  className = "",
  children,
  ...rest
}: CardProps) {
  const classes = [
    "card",
    raised ? "card-raised" : "",
    interactive ? "card-interactive" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes} {...rest}>
      {children}
    </div>
  );
}
