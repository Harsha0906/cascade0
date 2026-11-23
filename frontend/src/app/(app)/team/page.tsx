"use client";

import React, { useState } from "react";
import { Send } from "lucide-react";
import { useApiData } from "@/lib/useApiData";
import { callApi } from "@/lib/api";
import { hasErrors, validateMember, type Errors } from "@/lib/forms";
import { Badge, Banner, Btn, Card, DataTable, EmptyState, Field, INPUT, Loading, PageHeader } from "@/components/ui";
import { useShell } from "@/components/ShellContext";

const ROLE_HELP: Record<string, string> = {
  owner: "Can do everything, including managing the team.",
  approver: "Can edit data and approve recovery plans.",
  viewer: "Can look, but not change anything.",
};

export default function TeamPage() {
  const { role, email: myEmail } = useShell();
  const team = useApiData<{ members: any[]; linked_chats: any[] }>("/api/v1/team");
  const [email, setEmail] = useState("");
  const [newRole, setNewRole] = useState("approver");
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [code, setCode] = useState<{ code: string; expires: string } | null>(null);

  const invite = async (e: React.FormEvent) => {
    e.preventDefault();
    const errs = validateMember({ email, role: newRole });
    setErrors(errs);
    setError("");
    setNote("");
    if (hasErrors(errs)) return;
    setBusy(true);
    const r = await callApi("/api/v1/team", "POST", { email: email.trim(), role: newRole });
    setBusy(false);
    if (!r.ok) return setError(r.error);
    setNote(`${email.trim()} added as ${newRole}.`);
    setEmail("");
    void team.reload();
  };

  const changeRole = async (m: any, next: string) => {
    setError("");
    const r = await callApi(`/api/v1/team/${encodeURIComponent(m.user_id)}`, "PATCH", { role: next });
    if (!r.ok) setError(r.error);
    void team.reload();
  };

  const remove = async (m: any) => {
    if (!window.confirm(`Remove ${m.email}? They will lose access to this factory.`)) return;
    setError("");
    const r = await callApi(`/api/v1/team/${encodeURIComponent(m.user_id)}`, "DELETE");
    if (!r.ok) setError(r.error);
    void team.reload();
  };

  const linkTelegram = async () => {
    setError("");
    const r = await callApi("/api/v1/channels/link-code", "POST");
    if (r.status === 404) return setError("Telegram linking is not available on this server yet.");
    if (!r.ok) return setError(r.error);
    const exp = r.data.expires_at ? new Date(r.data.expires_at).toLocaleTimeString("en-IN", { timeStyle: "short" }) : r.data.expires_in_seconds ? `${Math.round(r.data.expires_in_seconds / 60)} min` : "";
    setCode({ code: r.data.code, expires: exp });
  };

  return (
    <>
      <PageHeader
        title="Team"
        sub="Who can see and change this factory."
        action={<Btn variant="quiet" onClick={linkTelegram}><Send className="h-4 w-4" aria-hidden /> Link my Telegram</Btn>}
      />
      {code && (
        <div className="mb-4">
          <Banner tone="green">
            Send <strong>/link {code.code}</strong> to the CascadeZero bot on Telegram{code.expires ? ` (works until ${code.expires})` : ""}. Then you can approve plans from your phone.
          </Banner>
        </div>
      )}
      {error && <div className="mb-4"><Banner>{error}</Banner></div>}
      {note && <div className="mb-4"><Banner tone="green">{note}</Banner></div>}

      {team.loading ? (
        <Loading />
      ) : team.status === 403 || role !== "owner" ? (
        <Card><EmptyState title="Only owners can manage the team" body={team.error || "Ask the factory owner to add or change people."} /></Card>
      ) : (
        !team.error && (
          <>
            <DataTable
              rows={team.data?.members ?? []}
              rowKey={(r) => r.user_id}
              searchLabel="Search people"
              empty={<EmptyState title="No one yet" />}
              columns={[
                { key: "email", header: "Person", render: (r) => <span className="font-semibold">{r.email}{r.email === myEmail && <span className="ml-2 text-sm font-normal text-charcoal-600">(you)</span>}</span>, text: (r) => r.email ?? "" },
                {
                  key: "role",
                  header: "Role",
                  render: (r) => (
                    <select aria-label={`Role for ${r.email}`} className={`${INPUT} !w-auto !py-1.5`} value={r.role} onChange={(e) => changeRole(r, e.target.value)}>
                      <option value="owner">Owner</option>
                      <option value="approver">Approver</option>
                      <option value="viewer">Viewer</option>
                    </select>
                  ),
                  text: (r) => r.role,
                },
              ]}
              actions={(r) => <Btn variant="danger" small onClick={() => remove(r)}>Remove</Btn>}
            />

            <Card className="mt-8 p-5">
              <h2 className="mb-1 font-display text-lg font-bold">Invite someone</h2>
              <p className="mb-4 text-charcoal-600">They need to sign up first, then add their email here.</p>
              <form onSubmit={invite} noValidate className="grid gap-3 sm:grid-cols-[1fr_auto_auto] sm:items-end">
                <Field label="Email" error={errors.email}><input className={INPUT} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" /></Field>
                <Field label="Role" error={errors.role} hint={ROLE_HELP[newRole]}>
                  <select className={INPUT} value={newRole} onChange={(e) => setNewRole(e.target.value)}>
                    <option value="approver">Approver</option>
                    <option value="viewer">Viewer</option>
                    <option value="owner">Owner</option>
                  </select>
                </Field>
                <Btn type="submit" busy={busy}>Add to team</Btn>
              </form>
            </Card>

            <h2 className="mb-3 mt-8 font-display text-lg font-bold">Linked chats</h2>
            {team.data?.linked_chats?.length ? (
              <Card className="divide-y divide-rule">
                {team.data.linked_chats.map((c) => (
                  <p key={`${c.channel}-${c.address}`} className="flex items-center justify-between gap-3 px-4 py-3">
                    <span>{c.email ?? "Someone"}</span>
                    <Badge tone="green">{c.channel} connected ✓</Badge>
                  </p>
                ))}
              </Card>
            ) : (
              <p className="text-charcoal-600">Nobody has linked Telegram yet.</p>
            )}
          </>
        )
      )}
    </>
  );
}
