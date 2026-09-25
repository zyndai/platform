import { connection } from "next/server";
import type { ReactNode } from "react";
import DashboardClientLayout from "./DashboardClientLayout";

export default async function DashboardLayout({
  children,
}: {
  children: ReactNode;
}) {
  await connection();

  return <DashboardClientLayout>{children}</DashboardClientLayout>;
}
