import { redirect } from "next/navigation";
import { AdminConsole } from "@/components/admin/AdminConsole";
import { createClient } from "@/lib/supabase/server";

export const metadata = { title: "Admin" };
export const dynamic = "force-dynamic";

export default async function AdminPage() {
  // The middleware already gates this route; this is defence in depth for the
  // case where the matcher is ever changed.
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/auth/login?next=/admin");

  const { data: admin } = await supabase
    .from("admin_users")
    .select("user_id")
    .eq("user_id", user.id)
    .maybeSingle();
  if (!admin) redirect("/dashboard?error=not-admin");

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-3xl font-extrabold tracking-tight">Review queue</h1>
      <p className="mt-1 text-sm text-muted">
        Approve, edit or reject AI-summarised entries before they reach the feed.
      </p>
      <AdminConsole />
    </div>
  );
}
