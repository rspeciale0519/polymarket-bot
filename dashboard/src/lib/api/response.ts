import { NextResponse } from "next/server";
import { ZodError } from "zod";

export function successResponse<T>(data: T, status = 200): NextResponse {
  return NextResponse.json({ data }, { status });
}

export function errorResponse(
  message: string,
  status = 400,
  code?: string
): NextResponse {
  const body: { error: string; code?: string } = { error: message };
  if (code) body.code = code;
  return NextResponse.json(body, { status });
}

export function validationErrorResponse(error: ZodError): NextResponse {
  const isDev = process.env.NODE_ENV === "development";
  if (isDev) {
    const issues = error.issues.map((issue) => ({
      field: issue.path.join("."),
      message: issue.message,
    }));
    return NextResponse.json(
      { error: "Validation failed", code: "VALIDATION_ERROR", details: issues },
      { status: 400 }
    );
  }
  return NextResponse.json(
    { error: "Validation failed", code: "VALIDATION_ERROR" },
    { status: 400 }
  );
}
