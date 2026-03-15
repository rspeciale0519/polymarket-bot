import { NextRequest } from "next/server";
import { prisma } from "@/lib/prisma";
import { successResponse, errorResponse } from "@/lib/api/response";

export async function GET() {
  try {
    const markets = await prisma.marketConfig.findMany({
      orderBy: { updatedAt: "desc" },
    });
    return successResponse(markets);
  } catch (e) {
    return errorResponse("Failed to fetch markets", 500);
  }
}

export async function PATCH(req: NextRequest) {
  try {
    const ticker = req.nextUrl.searchParams.get("ticker");
    if (!ticker) return errorResponse("Missing ticker", 400);

    const body = await req.json();
    await prisma.marketConfig.update({
      where: { ticker },
      data: { enabled: body.enabled },
    });
    return successResponse({ updated: true });
  } catch (e) {
    return errorResponse("Failed to update market", 500);
  }
}
