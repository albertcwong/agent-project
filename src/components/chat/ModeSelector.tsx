"use client";

import { ChevronDown, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface ModeSelectorProps {
  value: boolean;
  onChange: (agentMode: boolean) => void;
}

export function ModeSelector({ value, onChange }: ModeSelectorProps) {
  const label = value ? "Tableau" : "Chat";
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="h-8 gap-1.5 text-caption hover:text-foreground">
          <Wrench className="h-4 w-4" />
          {label}
          <ChevronDown className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-32">
        <DropdownMenuItem onClick={() => onChange(false)}>Chat</DropdownMenuItem>
        <DropdownMenuItem onClick={() => onChange(true)}>Tableau</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
