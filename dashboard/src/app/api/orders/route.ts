import { NextRequest } from "next/server";
import { prisma } from "@/lib/prisma";
import { successResponse, errorResponse } from "@/lib/api/response";

export async function GET() {
  try {
    const orders = await prisma.order.findMany({
      where: { status: "resting" },
      orderBy: { createdAt: "desc" },
      take: 100,
    });
    return successResponse(orders);
  } catch (e) {
    return errorResponse("Failed to fetch orders", 500);
  }
}

export async function DELETE(req: NextRequest) {
  try {
    const id = req.nextUrl.searchParams.get("id");
    if (!id) return errorResponse("Missing order id", 400);

    await prisma.order.update({
      where: { externalOrderId: id },
      data: { status: "cancelled" },
    });
    return successResponse({ cancelled: true });
  } catch (e) {
    return errorResponse("Failed to cancel order", 500);
  }
}
