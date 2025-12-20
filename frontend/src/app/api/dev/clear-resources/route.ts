import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function DELETE(request: NextRequest) {
  try {
    const { projectId } = await request.json();

    if (!projectId) {
      return NextResponse.json(
        { error: "projectId is required" },
        { status: 400 }
      );
    }

    // Forward cookies for auth
    const cookieHeader = request.headers.get("cookie") || "";

    // Fetch all resources for the project
    const listRes = await fetch(`${API_BASE}/projects/${projectId}/resources`, {
      headers: { Cookie: cookieHeader },
    });

    if (!listRes.ok) {
      return NextResponse.json(
        { error: `Failed to list resources: ${listRes.status}` },
        { status: listRes.status }
      );
    }

    const resources = await listRes.json();

    // Delete each resource
    let deleted = 0;
    const errors: string[] = [];

    for (const resource of resources) {
      try {
        const deleteRes = await fetch(
          `${API_BASE}/projects/${projectId}/resources/${resource.id}`,
          {
            method: "DELETE",
            headers: { Cookie: cookieHeader },
          }
        );
        if (deleteRes.ok) {
          deleted++;
        } else {
          errors.push(`Failed to delete ${resource.filename}: ${deleteRes.status}`);
        }
      } catch (err) {
        errors.push(`Error deleting ${resource.filename}: ${err instanceof Error ? err.message : "Unknown"}`);
      }
    }

    return NextResponse.json({
      success: true,
      deleted,
      total: resources.length,
      errors: errors.length > 0 ? errors : undefined,
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unknown error" },
      { status: 500 }
    );
  }
}
