import { prisma } from "@/lib/prisma";
import { successResponse, errorResponse } from "@/lib/api/response";

export async function POST() {
  try {
    const result = await prisma.order.updateMany({
      where: { status: "resting" },
      data: { status: "cancelled" },
    });
    return successResponse({ cancelled: result.count });
  } catch (e) {
    return errorResponse("Failed to cancel orders", 500);
  }
}
