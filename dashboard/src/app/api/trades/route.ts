import { NextRequest } from "next/server";
import { prisma } from "@/lib/prisma";
import { successResponse, errorResponse } from "@/lib/api/response";

export async function GET(req: NextRequest) {
  try {
    const page = parseInt(req.nextUrl.searchParams.get("page") ?? "1");
    const pageSize = parseInt(req.nextUrl.searchParams.get("pageSize") ?? "25");
    const skip = (page - 1) * pageSize;

    const [trades, total] = await Promise.all([
      prisma.fill.findMany({
        orderBy: { createdAt: "desc" },
        skip,
        take: pageSize,
      }),
      prisma.fill.count(),
    ]);

    return successResponse({ trades, total });
  } catch (e) {
    return errorResponse("Failed to fetch trades", 500);
  }
}
