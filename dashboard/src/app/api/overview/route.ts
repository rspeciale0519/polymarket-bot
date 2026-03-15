import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { successResponse, errorResponse } from "@/lib/api/response";

export async function GET() {
  try {
    const [status, latestSnapshot, todayFills, weekFills, monthFills, allFills, openOrders] =
      await Promise.all([
        prisma.engineStatus.findUnique({ where: { id: "singleton" } }),
        prisma.portfolioSnapshot.findFirst({ orderBy: { snapshotAt: "desc" } }),
        prisma.fill.aggregate({
          _sum: { pnlCents: true },
          where: { createdAt: { gte: startOfDay() } },
        }),
        prisma.fill.aggregate({
          _sum: { pnlCents: true },
          where: { createdAt: { gte: startOfWeek() } },
        }),
        prisma.fill.aggregate({
          _sum: { pnlCents: true },
          where: { createdAt: { gte: startOfMonth() } },
        }),
        prisma.fill.aggregate({ _sum: { pnlCents: true } }),
        prisma.order.count({ where: { status: "resting" } }),
      ]);

    const activePositions = await prisma.position.count({
      where: { isOpen: true },
    });

    return successResponse({
      balanceCents: latestSnapshot?.balanceCents ?? 0,
      equityCents: latestSnapshot?.equityCents ?? 0,
      todayPnlCents: todayFills._sum.pnlCents ?? 0,
      weekPnlCents: weekFills._sum.pnlCents ?? 0,
      monthPnlCents: monthFills._sum.pnlCents ?? 0,
      allTimePnlCents: allFills._sum.pnlCents ?? 0,
      activePositions,
      openOrders,
      mode: status?.mode ?? "paper",
      connected: status?.connected ?? false,
      lastTradeAt: status?.lastTradeAt?.toISOString() ?? null,
      circuitBreakerState: status?.circuitBreakerState ?? "ok",
      circuitBreakerReason: status?.circuitBreakerReason ?? null,
      isRunning: status?.isRunning ?? false,
      isPaused: status?.isPaused ?? false,
    });
  } catch (e) {
    return errorResponse("Failed to fetch overview", 500);
  }
}

function startOfDay(): Date {
  const d = new Date();
  d.setUTCHours(0, 0, 0, 0);
  return d;
}

function startOfWeek(): Date {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - d.getUTCDay());
  d.setUTCHours(0, 0, 0, 0);
  return d;
}

function startOfMonth(): Date {
  const d = new Date();
  d.setUTCDate(1);
  d.setUTCHours(0, 0, 0, 0);
  return d;
}
