import { NextRequest } from "next/server";
import { prisma } from "@/lib/prisma";
import { successResponse, errorResponse, validationErrorResponse } from "@/lib/api/response";
import { z } from "zod";

const UpdateSchema = z.object({
  mode: z.enum(["paper", "live"]).optional(),
  maxPositionPerMarket: z.number().int().positive().max(10000).optional(),
  globalExposureLimitCents: z.number().int().positive().optional(),
  dailyLossLimitCents: z.number().int().positive().optional(),
  drawdownLimit: z.number().min(0.01).max(0.99).optional(),
  baseGamma: z.number().positive().optional(),
  sigma: z.number().positive().optional(),
  minSpreadCents: z.number().int().min(1).max(50).optional(),
  orderSize: z.number().int().positive().optional(),
  signalWeight: z.number().min(0).max(1).optional(),
  minVolume: z.number().int().positive().optional(),
  maxMarketSpreadCents: z.number().int().min(1).max(99).optional(),
  minTimeToExpiry: z.number().int().positive().optional(),
  paperMilestoneDays: z.number().int().min(1).max(365).optional(),
  telegramToken: z.string().nullable().optional(),
  telegramChatId: z.string().nullable().optional(),
  settingsPollIntervalSec: z.number().int().min(5).max(300).optional(),
  reconciliationIntervalSec: z.number().int().min(10).max(300).optional(),
  snapshotIntervalSec: z.number().int().min(60).max(3600).optional(),
});

export async function GET() {
  try {
    let settings = await prisma.botSettings.findUnique({
      where: { id: "singleton" },
    });

    if (!settings) {
      settings = await prisma.botSettings.create({
        data: { id: "singleton" },
      });
    }

    return successResponse(settings);
  } catch (e) {
    return errorResponse("Failed to fetch settings", 500);
  }
}

export async function PUT(req: NextRequest) {
  try {
    const body = await req.json();
    const parsed = UpdateSchema.safeParse(body);
    if (!parsed.success) {
      return validationErrorResponse(parsed.error);
    }

    const settings = await prisma.botSettings.upsert({
      where: { id: "singleton" },
      update: parsed.data,
      create: { id: "singleton", ...parsed.data },
    });

    return successResponse(settings);
  } catch (e) {
    return errorResponse("Failed to update settings", 500);
  }
}
