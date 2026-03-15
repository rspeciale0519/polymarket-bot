import { prisma } from "@/lib/prisma";
import { successResponse, errorResponse } from "@/lib/api/response";

export async function GET() {
  try {
    const [totalFills, winningFills, allPnl, allFees, deposits] =
      await Promise.all([
        prisma.fill.count(),
        prisma.fill.count({ where: { pnlCents: { gt: 0 } } }),
        prisma.fill.aggregate({ _sum: { pnlCents: true } }),
        prisma.fill.aggregate({ _sum: { feeCents: true } }),
        prisma.deposit.aggregate({ _sum: { amountCents: true } }),
      ]);

    const makerFills = await prisma.fill.count({ where: { isMaker: true } });

    const lossingFills = await prisma.fill.count({
      where: { pnlCents: { lt: 0 } },
    });
    const totalWinPnl = await prisma.fill.aggregate({
      _sum: { pnlCents: true },
      where: { pnlCents: { gt: 0 } },
    });
    const totalLossPnl = await prisma.fill.aggregate({
      _sum: { pnlCents: true },
      where: { pnlCents: { lt: 0 } },
    });

    const winRate = totalFills > 0 ? (winningFills / totalFills) * 100 : 0;
    const grossWin = totalWinPnl._sum.pnlCents ?? 0;
    const grossLoss = Math.abs(totalLossPnl._sum.pnlCents ?? 0);
    const profitFactor = grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : 0;
    const makerRatio = totalFills > 0 ? (makerFills / totalFills) * 100 : 0;

    return successResponse({
      winRate,
      profitFactor: isFinite(profitFactor) ? profitFactor : 0,
      sharpeRatio: 0, // Computed from equity curve, not fills
      makerRatio,
      totalFills,
      totalFeesCents: allFees._sum.feeCents ?? 0,
      totalPnlCents: allPnl._sum.pnlCents ?? 0,
      depositsCents: deposits._sum.amountCents ?? 0,
      tradingPnlCents: allPnl._sum.pnlCents ?? 0,
    });
  } catch (e) {
    return errorResponse("Failed to fetch analytics", 500);
  }
}
