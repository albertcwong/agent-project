import { NextResponse } from "next/server";

/** When AUTH_DISABLED, bypass middleware hits this route; return 204 so useUser() gets null. */
export async function GET() {
  if (process.env.AUTH_DISABLED !== "true") return new NextResponse(null, { status: 401 });
  return new NextResponse(null, { status: 204 });
}
