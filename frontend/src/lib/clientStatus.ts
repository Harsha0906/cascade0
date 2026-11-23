/** Fields of the Client Agent record (GET /api/v1/client/{run_id}) that the UI reads. */
export interface ClientRecord {
  run_id?: string;
  status: "DRAFTED" | "APPROVED" | "SENT" | "ANSWERING" | "ACCEPTED" | "REFUSED" | string;
  client?: string;
  order_id?: string;
  extension_hours?: number;
  reason?: string;
  draft_message?: string;
  partial_penalty_inr?: number;
  approved_by?: string | null;
  replan_deadline_hours?: number | null;
  replan_run_id?: string | null;
  replan_recommended_plan_id?: string | null;
  mode?: string;
  events?: unknown[];
}

/** One plain sentence describing where the extension request stands. */
export function clientStatusText(
  r: Pick<ClientRecord, "status" | "client" | "extension_hours" | "replan_deadline_hours"> | null
): string {
  if (!r) return "No extension request yet.";
  const who = r.client || "the client";
  switch (r.status) {
    case "DRAFTED":
      return `Draft: ${r.extension_hours}h extension request to ${who}. Not sent; awaiting human approval.`;
    case "APPROVED":
      return `Approved; sending to ${who}.`;
    case "SENT":
      return `Sent to ${who}; awaiting their answer.`;
    case "ANSWERING":
      return "Answer recorded; re-planning is in progress. Submit the same answer again to resume if it stalls.";
    case "ACCEPTED":
      return `${who} accepted; deadline now ${r.replan_deadline_hours ?? "?"}h. Re-planned.`;
    case "REFUSED":
      return `${who} refused the extension. Re-planned with the original deadline.`;
    default:
      return `Extension request status: ${r.status}.`;
  }
}
