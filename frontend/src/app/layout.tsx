import type { Metadata } from "next";
import "./globals.css";
import { ErrorBoundary } from "@/components/ErrorBoundary";

export const metadata: Metadata = {
  title: "CascadeZero — recover from factory disruptions",
  description: "Spot orders at risk, compare recovery plans and ask your suppliers, in one calm place.",
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