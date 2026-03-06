"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { ChevronDown } from "lucide-react";
import { MODELS_RELOAD_EVENT } from "@/components/settings/ModelReload";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const MODEL_STORAGE_KEY = "chat-selected-model";
const PROVIDER_STORAGE_KEY = "chat-selected-provider";

export interface ModelOption {
  id: string;
  provider: string;
}

interface ModelSelectorProps {
  value: ModelOption | null;
  onChange: (model: string, provider: string) => void;
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  salesforce: "Salesforce",
  endor: "Endor",
};

export function ModelSelector({ value, onChange }: ModelSelectorProps) {
  const [modelsByProvider, setModelsByProvider] = useState<
    Record<string, { id: string }[]>
  >({});
  const [loading, setLoading] = useState(true);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const fetchModels = useCallback(() => {
    setLoading(true);
    const storedModel = typeof window !== "undefined" ? localStorage.getItem(MODEL_STORAGE_KEY) : null;
    const storedProvider = typeof window !== "undefined" ? localStorage.getItem(PROVIDER_STORAGE_KEY) : null;

    fetch("/api/models")
      .then((res) => res.json())
      .then((data) => {
        setModelsByProvider(data);
        const cb = onChangeRef.current;
        if (Object.keys(data).length === 0) return;
        if (storedModel && storedProvider && data[storedProvider]?.some((m: { id: string }) => m.id === storedModel)) {
          cb(storedModel, storedProvider);
          return;
        }
        const firstProvider = Object.keys(data)[0];
        const firstModel = data[firstProvider]?.[0]?.id;
        if (firstModel) {
          cb(firstModel, firstProvider);
          if (typeof window !== "undefined") {
            localStorage.setItem(MODEL_STORAGE_KEY, firstModel);
            localStorage.setItem(PROVIDER_STORAGE_KEY, firstProvider);
          }
        }
      })
      .catch(() => {
        setModelsByProvider({});
        onChangeRef.current("gpt-4", "openai");
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchModels();
  }, [fetchModels]);

  useEffect(() => {
    const handler = () => fetchModels();
    window.addEventListener(MODELS_RELOAD_EVENT, handler);
    return () => window.removeEventListener(MODELS_RELOAD_EVENT, handler);
  }, [fetchModels]);

  const handleSelect = (modelId: string, provider: string) => {
    onChange(modelId, provider);
    if (typeof window !== "undefined") {
      localStorage.setItem(MODEL_STORAGE_KEY, modelId);
      localStorage.setItem(PROVIDER_STORAGE_KEY, provider);
    }
  };

  const displayLabel = value
    ? `${value.id} (${PROVIDER_LABELS[value.provider] || value.provider})`
    : "Select model";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" disabled={loading} className="h-8 gap-1.5 text-caption hover:text-foreground">
          {loading ? "Loading..." : displayLabel}
          <ChevronDown className="ml-1 h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        {Object.entries(modelsByProvider).map(([provider, models]) =>
          models.length > 0 ? (
            <div key={provider}>
              <DropdownMenuLabel>
                {PROVIDER_LABELS[provider] || provider}
              </DropdownMenuLabel>
              {models.map((m) => (
                <DropdownMenuItem
                  key={`${provider}-${m.id}`}
                  onClick={() => handleSelect(m.id, provider)}
                >
                  {m.id}
                </DropdownMenuItem>
              ))}
            </div>
          ) : null
        )}
        {!loading && Object.keys(modelsByProvider).length === 0 && (
          <DropdownMenuLabel className="text-muted-foreground">
            No models available
          </DropdownMenuLabel>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
