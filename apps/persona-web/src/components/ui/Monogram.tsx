import type { HTMLAttributes } from "react";

type Size = "lg" | "md" | "sm" | "xs";

interface MonogramProps extends HTMLAttributes<HTMLSpanElement> {
  size?: Size;
}

const SIZE_PX: Record<Size, number> = {
  lg: 40,
  md: 28,
  sm: 22,
  xs: 16,
};

export function Monogram({
  size = "md",
  className = "",
  style,
  ...rest
}: MonogramProps) {
  const px = SIZE_PX[size];

  return (
    <span
      aria-hidden="true"
      className={`monogram monogram-${size} ${className}`.trim()}
      style={{
        width: px,
        height: px,
        minWidth: px,
        minHeight: px,
        ...style,
      }}
      {...rest}
    >
      <img
        src="/zynd.png"
        alt=""
        draggable={false}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          display: "block",
          pointerEvents: "none",
        }}
      />
    </span>
  );
}
