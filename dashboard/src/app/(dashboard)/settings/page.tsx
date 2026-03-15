"use client";

import { useEffect, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useSettings, updateSettings } from "@/hooks/use-settings";
import { toast } from "sonner";
import type { BotSettings } from "@/types/bot";
import { Save } from "lucide-react";

export default function SettingsPage() {
  const { data: settings, loading } = useSettings();
  const [form, setForm] = useState<Partial<BotSettings>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (settings) setForm(settings);
  }, [settings]);

  const handleSave = async () => {
    setSaving(true);
    const ok = await updateSettings(form);
    if (ok) toast.success("Settings saved");
    else toast.error("Failed to save settings");
    setSaving(false);
  };

  const field = (key: keyof BotSettings, label: string, type: string = "number") => (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {loading ? (
        <Skeleton className="h-9 w-full" />
      ) : (
        <Input
          type={type}
          value={form[key] ?? ""}
          onChange={(e) => {
            const val = type === "number" ? parseFloat(e.target.value) : e.target.value;
            setForm((f) => ({ ...f, [key]: val }));
          }}
          className="bg-background font-mono text-sm"
        />
      )}
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-display)" }}>
            Settings
          </h2>
          <p className="text-sm text-muted-foreground">Engine configuration (changes apply within 10 seconds)</p>
        </div>
        <Button onClick={handleSave} disabled={saving}>
          <Save className="mr-1.5 h-3.5 w-3.5" />
          {saving ? "Saving..." : "Save Changes"}
        </Button>
      </div>

      <Tabs defaultValue="risk">
        <TabsList>
          <TabsTrigger value="risk">Risk</TabsTrigger>
          <TabsTrigger value="strategy">Strategy</TabsTrigger>
          <TabsTrigger value="markets">Market Selection</TabsTrigger>
          <TabsTrigger value="milestone">Milestones</TabsTrigger>
          <TabsTrigger value="notifications">Notifications</TabsTrigger>
          <TabsTrigger value="polling">Polling</TabsTrigger>
        </TabsList>

        <TabsContent value="risk">
          <Card className="bg-card/60 border-border/40">
            <CardHeader><CardTitle className="text-sm">Risk Parameters</CardTitle></CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              {field("maxPositionPerMarket", "Max Position Per Market")}
              {field("globalExposureLimitCents", "Global Exposure Limit (cents)")}
              {field("dailyLossLimitCents", "Daily Loss Limit (cents)")}
              {field("drawdownLimit", "Max Drawdown (0-1)")}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="strategy">
          <Card className="bg-card/60 border-border/40">
            <CardHeader><CardTitle className="text-sm">Strategy Parameters</CardTitle></CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              {field("baseGamma", "Base Gamma (risk aversion)")}
              {field("sigma", "Sigma (volatility estimate)")}
              {field("minSpreadCents", "Min Spread (cents)")}
              {field("orderSize", "Order Size (contracts)")}
              {field("signalWeight", "Signal Weight (0-1)")}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="markets">
          <Card className="bg-card/60 border-border/40">
            <CardHeader><CardTitle className="text-sm">Market Selection Criteria</CardTitle></CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              {field("minVolume", "Min 24h Volume")}
              {field("maxMarketSpreadCents", "Max Spread (cents)")}
              {field("minTimeToExpiry", "Min Time to Expiry (seconds)")}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="milestone">
          <Card className="bg-card/60 border-border/40">
            <CardHeader><CardTitle className="text-sm">Paper Trading Milestone</CardTitle></CardHeader>
            <CardContent className="max-w-sm">
              {field("paperMilestoneDays", "Target Profitable Days")}
              <p className="mt-2 text-xs text-muted-foreground">
                Advisory only — does not block live trading. You will receive a notification when the milestone is reached.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="notifications">
          <Card className="bg-card/60 border-border/40">
            <CardHeader><CardTitle className="text-sm">Telegram Configuration</CardTitle></CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              {field("telegramToken", "Bot Token", "password")}
              {field("telegramChatId", "Chat ID", "text")}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="polling">
          <Card className="bg-card/60 border-border/40">
            <CardHeader><CardTitle className="text-sm">Polling Intervals</CardTitle></CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              {field("settingsPollIntervalSec", "Settings Poll (seconds)")}
              {field("reconciliationIntervalSec", "Reconciliation (seconds)")}
              {field("snapshotIntervalSec", "Portfolio Snapshot (seconds)")}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
