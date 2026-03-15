import { NextRequest } from "next/server";
import { prisma } from "@/lib/prisma";
import { successResponse, errorResponse } from "@/lib/api/response";

export async function GET(req: NextRequest) {
  try {
    const hours = parseInt(req.nextUrl.searchParams.get("hours") ?? "24");
    const cutoff = new Date(Date.now() - hours * 3600 * 1000);

    const snapshots = await prisma.portfolioSnapshot.findMany({
      where: { snapshotAt: { gte: cutoff } },
      orderBy: { snapshotAt: "asc" },
      select: {
        snapshotAt: true,
        equityCents: true,
        balanceCents: true,
      },
      take: 500,
    });

    return successResponse(
      snapshots.map((s) => ({
        snapshotAt: s.snapshotAt.toISOString(),
        equityCents: s.equityCents,
        balanceCents: s.balanceCents,
      }))
    );
  } catch (e) {
    return errorResponse("Failed to fetch portfolio history", 500);
  }
}
