import { createClient, RealtimeChannel } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
// The anon key is a public, read-only key once RLS is enabled (supabase/migrations/001_rls_and_audit.sql).
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";

export const supabase =
  supabaseUrl && supabaseAnonKey
    ? createClient(supabaseUrl, supabaseAnonKey, { realtime: { params: { eventsPerSecond: 10 } } })
    : null;

if (!supabase && typeof window !== "undefined") {
  console.warn("Supabase env vars missing — realtime updates disabled; the dashboard will poll the API instead.");
}

/**
 * Subscribe to realtime changes on a Supabase table.
 * Automatically cleans up on channel unsubscribe.
 */
export function subscribeToTable(
  tableName: string,
  onInsert?: (row: any) => void,
  onUpdate?: (row: any) => void,
  onDelete?: (row: any) => void
): Pick<RealtimeChannel, "unsubscribe"> {
  if (!supabase) {
    return { unsubscribe: async () => "ok" as const };
  }
  const channel = supabase
    .channel(`realtime_${tableName}_${Math.random().toString(36).substring(7)}`)
    .on(
      "postgres_changes",
      { event: "*", schema: "public", table: tableName },
      (payload) => {
        if (payload.eventType === "INSERT" && onInsert) onInsert(payload.new);
        if (payload.eventType === "UPDATE" && onUpdate) onUpdate(payload.new);
        if (payload.eventType === "DELETE" && onDelete) onDelete(payload.old);
      }
    )
    .subscribe();

  return channel;
}
