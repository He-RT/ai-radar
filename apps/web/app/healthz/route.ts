import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json(
    { status: "ok", service: "zhenfu-ai-radar-web" },
    { headers: { "Cache-Control": "no-store" } }
  );
}
