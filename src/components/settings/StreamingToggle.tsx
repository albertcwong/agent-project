"use client";

import { useState, useEffect } from "react";
import { getAgentStreaming, setAgentStreaming } from "@/lib/threads";
import { cn } from "@/lib/utils";

export function StreamingToggle() {
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    setEnabled(getAgentStreaming());
  }, []);

  const handleToggle = () => {
    const next = !enabled;
    setEnabled(next);
    setAgentStreaming(next);
  };

  return (
    <div className="flex items-center justify-between">
      <label htmlFor="streaming-toggle" className="cursor-pointer text-sm font-medium">
        Stream agent responses
      </label>
      <button
        id="streaming-toggle"
        type="button"
        role="switch"
        aria-checked={enabled}
        onClick={handleToggle}
        className={cn(
          "relative h-6 w-11 shrink-0 rounded-full transition-colors",
          enabled ? "bg-primary" : "bg-muted"
        )}
      >
        <span
          className={cn(
            "absolute top-1 h-4 w-4 rounded-full bg-background shadow transition-transform",
            enabled ? "left-7" : "left-1"
          )}
        />
      </button>
    </div>
  );
}
