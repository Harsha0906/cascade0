"use client";

import React, { Component, ErrorInfo, ReactNode } from "react";
import { AlertOctagon, RotateCcw } from "lucide-react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("CascadeZero Caught Exception:", error, errorInfo);
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center min-h-screen bg-[#07090e] text-white p-6">
          <div className="max-w-md w-full p-6 rounded-3xl bg-surface/90 border border-white/10 shadow-2xl flex flex-col items-center text-center">
            <div className="w-12 h-12 rounded-2xl bg-rose-500/15 border border-brand-crimson/40 flex items-center justify-center mb-4 text-brand-crimsonBright">
              <AlertOctagon className="w-6 h-6" />
            </div>
            <h1 className="text-base font-bold tracking-tight text-white mb-2">
              CascadeZero Encountered an Exception
            </h1>
            <p className="text-xs text-slate-400 font-mono mb-4 bg-black/40 p-3 rounded-xl border border-white/5 w-full text-left overflow-auto max-h-32">
              {this.state.error?.message || "An unexpected rendering fault occurred."}
            </p>
            <button
              onClick={this.handleReload}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-brand-emerald hover:bg-brand-emerald/90 text-black font-semibold text-xs font-mono shadow-lg transition-all"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Reload Command Center</span>
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
