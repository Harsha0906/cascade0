"use client";

import React from "react";
import { AgentPipelineStrip } from "@/components/AgentPipelineStrip";
import { FlowCanvas } from "@/components/FlowCanvas";
import { AgentStream } from "@/components/AgentStream";
import { PlaybookSidebar } from "@/components/PlaybookSidebar";
import { PageHeader } from "@/components/ui";

/** Power-user view: the digital twin, the agent pipeline and its logs. Technical terms live here. */
export default function AdvancedPage() {
  return (
    <>
      <PageHeader title="Advanced" sub="The digital twin, the agent log and the detailed plan numbers. You do not need this for day-to-day use." />
      <div className="advanced-surface space-y-4 p-3 sm:p-5">
        <AgentPipelineStrip />
        <div className="flex flex-col items-start gap-4 lg:flex-row">
          <div className="flex w-full min-w-0 flex-1 flex-col gap-4">
            <FlowCanvas />
            <AgentStream />
          </div>
          <div className="w-full shrink-0 lg:w-[380px]">
            <PlaybookSidebar />
          </div>
        </div>
      </div>
    </>
  );
}
