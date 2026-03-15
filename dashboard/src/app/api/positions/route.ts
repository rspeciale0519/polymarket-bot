import { prisma } from "@/lib/prisma";
import { successResponse, errorResponse } from "@/lib/api/response";

export async function GET() {
  try {
    const positions = await prisma.position.findMany({
      where: { isOpen: true },
      orderBy: { updatedAt: "desc" },
    });
    return successResponse(positions);
  } catch (e) {
    return errorResponse("Failed to fetch positions", 500);
  }
}
