import type { HTMLAttributes } from "react";

type Size = "lg" | "md" | "sm" | "xs";

interface MonogramProps extends HTMLAttributes<HTMLSpanElement> {
  size?: Size;
}

export function Monogram({
  size = "md",
  className = "",
  ...rest
}: MonogramProps) {
  return (
    <span
      aria-hidden="true"
      className={`monogram monogram-${size} ${className}`.trim()}
      {...rest}
    >
      <img src="/zynd.png" alt="" draggable={false} />
    </span>
  );
}
