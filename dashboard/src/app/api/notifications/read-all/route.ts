import { prisma } from "@/lib/prisma";
import { successResponse, errorResponse } from "@/lib/api/response";

export async function POST() {
  try {
    await prisma.notification.updateMany({
      where: { read: false },
      data: { read: true },
    });
    return successResponse({ success: true });
  } catch (e) {
    return errorResponse("Failed to mark notifications read", 500);
  }
}
