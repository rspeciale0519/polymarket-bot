import { NextRequest } from "next/server";
import { prisma } from "@/lib/prisma";
import { successResponse, errorResponse } from "@/lib/api/response";

export async function GET(req: NextRequest) {
  try {
    const unread = req.nextUrl.searchParams.get("unread") === "true";
    const where = unread ? { read: false } : {};

    const notifications = await prisma.notification.findMany({
      where,
      orderBy: { createdAt: "desc" },
      take: 20,
    });

    return successResponse(notifications);
  } catch (e) {
    return errorResponse("Failed to fetch notifications", 500);
  }
}
