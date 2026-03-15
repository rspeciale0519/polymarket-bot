"use client";

import { useState } from "react";
import { useBotMode } from "@/stores/bot-mode";
import { updateSettings } from "@/hooks/use-settings";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";

export function ModeToggle() {
  const { mode, setMode } = useBotMode();
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);

  const isLive = mode === "live";

  const handleToggle = async (checked: boolean) => {
    const newMode = checked ? "live" : "paper";

    if (newMode === "live" && !confirming) {
      setConfirming(true);
      return;
    }

    setSaving(true);
    const success = await updateSettings({ mode: newMode });
    if (success) {
      setMode(newMode);
    }
    setSaving(false);
    setConfirming(false);
  };

  if (confirming) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs text-amber-400">Switch to LIVE?</span>
        <button
          onClick={() => handleToggle(true)}
          disabled={saving}
          className="rounded bg-red-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-red-500 disabled:opacity-50"
        >
          {saving ? "..." : "Confirm"}
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground hover:bg-accent"
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Label className="text-xs text-muted-foreground">Paper</Label>
      <Switch
        checked={isLive}
        onCheckedChange={handleToggle}
        disabled={saving}
      />
      <Label className="text-xs text-muted-foreground">Live</Label>
    </div>
  );
}
