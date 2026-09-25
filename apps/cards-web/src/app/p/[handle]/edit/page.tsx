import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getMyCard } from "@/lib/cards";
import { EditProfileClient } from "./edit-client";

interface PageProps {
  params: Promise<{ handle: string }>;
}

export default async function EditProfilePage({ params }: PageProps) {
  const { handle } = await params;
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session?.access_token) redirect(`/p/${handle}`);

  const myCard = await getMyCard(session.access_token);
  if (!myCard || myCard.handle !== handle) redirect(`/p/${handle}`);

  return (
    <EditProfileClient
      initialCard={myCard.card}
      handle={handle}
      token={session.access_token}
    />
  );
}
