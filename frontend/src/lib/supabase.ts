import { createClient, RealtimeChannel } from "@supabase/supabase-js";

const supabaseUrl =
  process.env.NEXT_PUBLIC_SUPABASE_URL || "https://vomjhhpmppqmbldbzper.supabase.co";
const supabaseAnonKey =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZvbWpoaHBtcHBxbWJsZGJ6cGVyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTQwMzQxMDEsImV4cCI6MjEwOTYxMDEwMX0.2v0rZPasgpp0c3pYdeenf5X2nO-Boo7gSByTgKYQwzI";

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  realtime: {
    params: {
      eventsPerSecond: 10,
    },
  },
});

/**
 * Subscribe to realtime changes on a Supabase table.
 * Automatically cleans up on channel unsubscribe.
 */
export function subscribeToTable(
  tableName: string,
  onInsert?: (row: any) => void,
  onUpdate?: (row: any) => void,
  onDelete?: (row: any) => void
): RealtimeChannel {
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
