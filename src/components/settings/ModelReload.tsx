"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

export const MODELS_RELOAD_EVENT = "models-reload";

export function dispatchModelsReload() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(MODELS_RELOAD_EVENT));
  }
}

export function ModelReload() {
  const [loading, setLoading] = useState(false);

  const handleReload = () => {
    setLoading(true);
    dispatchModelsReload();
    setTimeout(() => setLoading(false), 1500);
  };

  return (
    <div className="flex items-center justify-between">
      <div>
        <p className="text-label">Models</p>
        <p className="text-caption">
          Reload if models were unavailable (e.g. before VPN)
        </p>
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={handleReload}
        disabled={loading}
      >
        <RefreshCw className={`mr-1.5 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        {loading ? "Reloading…" : "Reload"}
      </Button>
    </div>
  );
}
