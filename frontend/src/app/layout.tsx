import type { Metadata } from "next";
import "./globals.css";
import { ErrorBoundary } from "@/components/ErrorBoundary";

export const metadata: Metadata = {
  title: "CascadeZero — AI Crisis Control Tower & 2.5D Digital Twin",
  description:
    "Multi-Agent AI Copilot & 2.5D Digital Twin for Compound-Risk Orchestration in Manufacturing",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased selection:bg-acid selection:text-charcoal-950 min-h-screen">
        <ErrorBoundary>{children}</ErrorBoundary>
      </body>
    </html>
  );
}