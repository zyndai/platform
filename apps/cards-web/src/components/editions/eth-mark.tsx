import type { CSSProperties } from "react";

/** The Ethereum diamond, drawn from the official mark's geometry (256 x 417):
 *  two pyramids, the upper one split into its four visible faces. Recoloured
 *  in the edition's lavender instead of the stock greys. */
export function EthMark({ size = 20, className, style }: { size?: number; className?: string; style?: CSSProperties }) {
  return (
    <svg viewBox="0 0 256 417" width={(size * 256) / 417} height={size} className={className} style={style} aria-hidden>
      <path fill="#4B3FC9" d="m127.961 0-2.795 9.5v275.668l2.795 2.79 127.962-75.638z" />
      <path fill="#8F86F2" d="M127.962 0 0 212.32l127.962 75.639V154.158z" />
      <path fill="#5A4FD6" d="m127.961 312.187-1.575 1.92v98.199l1.575 4.601 128.038-180.32z" />
      <path fill="#8F86F2" d="M127.962 416.905v-104.72L0 236.585z" />
      <path fill="#2E2499" d="m127.961 287.958 127.96-75.637-127.96-58.162z" />
      <path fill="#6C62E0" d="m0 212.32 127.96 75.638v-133.8z" />
    </svg>
  );
}
