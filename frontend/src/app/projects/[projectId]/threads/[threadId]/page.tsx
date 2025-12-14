"use client";

import { useEffect } from "react";
import { useParams } from "next/navigation";
import { useProject } from "@/contexts/project-context";
import ProjectPage from "../../page";

export default function ThreadPage() {
  const params = useParams();
  const threadId = params.threadId as string;
  const { selectThread, selectedProject } = useProject();

  // When the thread page loads, select the thread from URL
  useEffect(() => {
    if (threadId && selectedProject) {
      selectThread(threadId);
    }
  }, [threadId, selectedProject, selectThread]);

  // Render the same project page - the context will handle showing the correct thread
  return <ProjectPage />;
}
