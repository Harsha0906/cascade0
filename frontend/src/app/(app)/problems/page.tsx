"use client";

import React from "react";
import Link from "next/link";
import { useFactoryStore } from "@/store/useFactoryStore";
import { GuidedFlow } from "@/components/GuidedFlow";
import { Card, EmptyState, PageHeader } from "@/components/ui";

export default function ProblemsPage() {
  const activeRunId = useFactoryStore((s) => s.activeRunId);
  return (
    <>
      <PageHeader title="Problem" sub="See what is affected, pick a plan, and approve it." />
      {activeRunId ? (
        <GuidedFlow key={activeRunId} />
      ) : (
        <Card>
          <EmptyState
            title="No problem reported"
            body="When something goes wrong, tell us on the Today page and we will work out your options."
            action={<Link href="/" className="inline-block rounded-xl bg-forest px-5 py-2.5 font-semibold text-white">Go to Today</Link>}
          />
        </Card>
      )}
    </>
  );
}
