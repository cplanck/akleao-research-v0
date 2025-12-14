"use client";

import { useParams } from "next/navigation";
import { ProjectProvider } from "@/contexts/project-context";

export default function ProjectLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const projectId = params.projectId as string;
  const threadId = params.threadId as string | undefined;

  // WebSocket is now managed at app level (AppWebSocketProvider)
  // No need to connect/disconnect here
  return (
    <ProjectProvider initialProjectId={projectId} initialThreadId={threadId}>
      {children}
    </ProjectProvider>
  );
}
