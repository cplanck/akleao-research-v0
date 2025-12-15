"use client";

import { useCallback, useState, useRef, useEffect } from "react";
import dynamic from "next/dynamic";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Resource, GlobalResource, uploadResource, deleteResource, getResourceFileUrl, addUrlResource, addGitResource, reindexResource, getResource, listGlobalResources, linkResourceToProject } from "@/lib/api";
import { toast } from "sonner";

// Authenticated image component - fetches with credentials
function AuthenticatedImage({ src, alt, className }: { src: string; alt: string; className?: string }) {
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let blobUrl: string | null = null;

    const fetchImage = async () => {
      try {
        setLoading(true);
        setError(null);

        const response = await fetch(src, {
          credentials: "include",
        });

        if (!response.ok) {
          throw new Error(`Failed to load image: ${response.status}`);
        }

        const blob = await response.blob();
        blobUrl = URL.createObjectURL(blob);
        setImageSrc(blobUrl);
      } catch (err) {
        console.error("Error fetching image:", err);
        setError(err instanceof Error ? err.message : "Failed to load image");
      } finally {
        setLoading(false);
      }
    };

    fetchImage();

    return () => {
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl);
      }
    };
  }, [src]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-muted-foreground">Loading image...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-destructive">{error}</span>
      </div>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={imageSrc || ""} alt={alt} className={className} />
  );
}

// Dynamically import PdfViewer to avoid SSR issues with react-pdf
const PdfViewer = dynamic(
  () => import("@/components/pdf-viewer").then((mod) => mod.PdfViewer),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-full">
        <span className="text-muted-foreground">Loading PDF viewer...</span>
      </div>
    ),
  }
);

interface ResourcePanelProps {
  projectId: string;
  resources: Resource[];
  onRefresh: () => void;
}

// Helper functions for status normalization
function isReadyStatus(status: string): boolean {
  return ["ready", "indexed", "analyzed", "described"].includes(status.toLowerCase());
}

function isProcessingStatus(status: string): boolean {
  return ["pending", "uploaded", "extracting", "extracted", "stored", "indexing"].includes(status.toLowerCase());
}

function isFailedStatus(status: string): boolean {
  return status.toLowerCase() === "failed";
}

function isPartialStatus(status: string): boolean {
  return status.toLowerCase() === "partial";
}

function getStatusColor(status: string): string {
  if (isReadyStatus(status)) return "bg-green-500";
  if (isPartialStatus(status)) return "bg-yellow-500";
  if (isFailedStatus(status)) return "bg-red-500";
  if (isProcessingStatus(status)) return "bg-blue-500";
  return "bg-gray-500";
}

function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={`animate-spin ${className || ""}`}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}

// Upload icon component
function UploadIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" x2="12" y1="3" y2="15" />
    </svg>
  );
}

// Globe icon component
function GlobeIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
      <path d="M2 12h20" />
    </svg>
  );
}

// Computer icon component
function ComputerIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <rect width="14" height="8" x="5" y="2" rx="2" />
      <rect width="20" height="8" x="2" y="14" rx="2" />
      <path d="M6 18h2" />
      <path d="M12 18h6" />
    </svg>
  );
}

// Refresh icon component
function RefreshIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
      <path d="M21 3v5h-5" />
      <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
      <path d="M3 21v-5h5" />
    </svg>
  );
}

// Chevron icon component
function ChevronIcon({ className, expanded }: { className?: string; expanded: boolean }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`transition-transform ${expanded ? "rotate-90" : ""} ${className || ""}`}
    >
      <path d="m9 18 6-6-6-6" />
    </svg>
  );
}

// External link icon component
function ExternalLinkIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M15 3h6v6" />
      <path d="M10 14 21 3" />
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
    </svg>
  );
}

// File icon component
function FileIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
      <path d="M14 2v4a2 2 0 0 0 2 2h4" />
    </svg>
  );
}

// Trash icon component
function TrashIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M3 6h18" />
      <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
      <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
    </svg>
  );
}

// Git branch icon component
function GitBranchIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <line x1="6" x2="6" y1="3" y2="15" />
      <circle cx="18" cy="6" r="3" />
      <circle cx="6" cy="18" r="3" />
      <path d="M18 9a9 9 0 0 1-9 9" />
    </svg>
  );
}

// Library icon component
function LibraryIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="m16 6 4 14" />
      <path d="M12 6v14" />
      <path d="M8 8v12" />
      <path d="M4 4v16" />
    </svg>
  );
}

// Check icon component
function CheckIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

// Plus icon component
function PlusIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M5 12h14" />
      <path d="M12 5v14" />
    </svg>
  );
}

// Table/Data icon component (for CSV, Excel, JSON)
function TableIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M12 3v18" />
      <rect width="18" height="18" x="3" y="3" rx="2" />
      <path d="M3 9h18" />
      <path d="M3 15h18" />
    </svg>
  );
}

// Image icon component
function ImageIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
    </svg>
  );
}

// Helper functions for formatting
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  return `${minutes}m ${remainingSeconds}s`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

function formatRowCount(count: number): string {
  if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
  if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
  return count.toString();
}

// Get icon component for resource type
function ResourceTypeIcon({ type, className }: { type: Resource["type"]; className?: string }) {
  switch (type) {
    case "document":
      return <FileIcon className={className} />;
    case "website":
      return <GlobeIcon className={className} />;
    case "git_repository":
      return <GitBranchIcon className={className} />;
    case "data_file":
      return <TableIcon className={className} />;
    case "image":
      return <ImageIcon className={className} />;
    default:
      return <FileIcon className={className} />;
  }
}

export function ResourcePanel({ projectId, resources, onRefresh }: ResourcePanelProps) {
  const [isUploading, setIsUploading] = useState(false);
  const [isAddingUrl, setIsAddingUrl] = useState(false);
  const [isAddingGit, setIsAddingGit] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [viewingResource, setViewingResource] = useState<Resource | null>(null);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [urlInput, setUrlInput] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [gitUrlInput, setGitUrlInput] = useState("");
  const [gitBranchInput, setGitBranchInput] = useState("");
  const [gitError, setGitError] = useState<string | null>(null);
  const [expandedResources, setExpandedResources] = useState<Set<string>>(new Set());
  const [libraryResources, setLibraryResources] = useState<GlobalResource[]>([]);
  const [isLoadingLibrary, setIsLoadingLibrary] = useState(false);
  const [linkingResourceId, setLinkingResourceId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Track current project to prevent stale polling updates
  const currentProjectIdRef = useRef(projectId);
  useEffect(() => {
    currentProjectIdRef.current = projectId;
  }, [projectId]);

  const toggleExpanded = (resourceId: string) => {
    setExpandedResources(prev => {
      const next = new Set(prev);
      if (next.has(resourceId)) {
        next.delete(resourceId);
      } else {
        next.add(resourceId);
      }
      return next;
    });
  };

  const handleFiles = async (files: FileList | null, closeDialog: boolean = false) => {
    if (!files || files.length === 0) return;
    setIsUploading(true);
    try {
      const uploadedResources: Resource[] = [];
      for (const file of Array.from(files)) {
        const resource = await uploadResource(projectId, file);
        uploadedResources.push(resource);
      }
      onRefresh();
      if (closeDialog) {
        setAddDialogOpen(false);
      }
      toast.success(files.length === 1 ? "File uploaded, indexing..." : `${files.length} files uploaded, indexing...`);

      // Poll for completion of each uploaded resource
      for (const resource of uploadedResources) {
        const resourceName = resource.filename || resource.source;
        const originalWorkspaceId = projectId;
        const checkStatus = async (): Promise<void> => {
          // Stop polling if workspace changed
          if (currentProjectIdRef.current !== originalWorkspaceId) return;
          try {
            const updated = await getResource(originalWorkspaceId, resource.id);
            // Check again after the async call
            if (currentProjectIdRef.current !== originalWorkspaceId) return;
            onRefresh();

            if (isReadyStatus(updated.status)) {
              const duration = updated.indexing_duration_ms ? ` in ${formatDuration(updated.indexing_duration_ms)}` : "";
              toast.success(`Indexed "${resourceName}"${duration}`);
            } else if (isPartialStatus(updated.status)) {
              toast.success(`Uploaded "${resourceName}" (partial - enrichment skipped)`);
            } else if (isFailedStatus(updated.status)) {
              toast.error(`Failed to index "${resourceName}"`);
            } else if (isProcessingStatus(updated.status)) {
              setTimeout(checkStatus, 2000);
            }
          } catch (error) {
            console.error("Failed to check index status:", error);
          }
        };
        setTimeout(checkStatus, 2000);
      }
    } catch (error) {
      console.error("Failed to upload:", error);
      toast.error("Failed to upload file. Please try again.");
    } finally {
      setIsUploading(false);
    }
  };

  const handleAddUrl = async () => {
    if (!urlInput.trim()) return;

    // Basic URL validation
    try {
      new URL(urlInput.trim());
    } catch {
      setUrlError("Please enter a valid URL");
      return;
    }

    setIsAddingUrl(true);
    setUrlError(null);
    try {
      const resource = await addUrlResource(projectId, urlInput.trim());
      const resourceName = resource.filename || resource.source;
      const originalWorkspaceId = projectId;
      onRefresh();
      setUrlInput("");
      setAddDialogOpen(false);
      toast.success("Website added, indexing...");

      // Poll for completion
      const checkStatus = async (): Promise<void> => {
        // Stop polling if workspace changed
        if (currentProjectIdRef.current !== originalWorkspaceId) return;
        try {
          const updated = await getResource(originalWorkspaceId, resource.id);
          // Check again after the async call
          if (currentProjectIdRef.current !== originalWorkspaceId) return;
          onRefresh();

          if (isReadyStatus(updated.status)) {
            const duration = updated.indexing_duration_ms ? ` in ${formatDuration(updated.indexing_duration_ms)}` : "";
            toast.success(`Indexed "${resourceName}"${duration}`);
          } else if (isPartialStatus(updated.status)) {
            toast.success(`Added "${resourceName}" (partial - enrichment skipped)`);
          } else if (isFailedStatus(updated.status)) {
            toast.error(`Failed to index "${resourceName}"`);
          } else if (isProcessingStatus(updated.status)) {
            setTimeout(checkStatus, 2000);
          }
        } catch (error) {
          console.error("Failed to check index status:", error);
        }
      };
      setTimeout(checkStatus, 2000);
    } catch (error) {
      console.error("Failed to add URL:", error);
      setUrlError("Failed to add URL. Please try again.");
      toast.error("Failed to add website. Please try again.");
    } finally {
      setIsAddingUrl(false);
    }
  };

  const handleAddGit = async () => {
    if (!gitUrlInput.trim()) return;

    // Basic URL validation
    try {
      new URL(gitUrlInput.trim());
    } catch {
      setGitError("Please enter a valid repository URL");
      return;
    }

    setIsAddingGit(true);
    setGitError(null);
    try {
      const resource = await addGitResource(
        projectId,
        gitUrlInput.trim(),
        gitBranchInput.trim() || undefined
      );
      const resourceName = resource.filename || resource.source;
      const originalWorkspaceId = projectId;
      onRefresh();
      setGitUrlInput("");
      setGitBranchInput("");
      setAddDialogOpen(false);
      toast.success("Repository added, cloning and indexing...");

      // Poll for completion
      const checkStatus = async (): Promise<void> => {
        // Stop polling if workspace changed
        if (currentProjectIdRef.current !== originalWorkspaceId) return;
        try {
          const updated = await getResource(originalWorkspaceId, resource.id);
          // Check again after the async call
          if (currentProjectIdRef.current !== originalWorkspaceId) return;
          onRefresh();

          if (isReadyStatus(updated.status)) {
            const duration = updated.indexing_duration_ms ? ` in ${formatDuration(updated.indexing_duration_ms)}` : "";
            toast.success(`Indexed "${resourceName}"${duration}`);
          } else if (isPartialStatus(updated.status)) {
            toast.success(`Added "${resourceName}" (partial - enrichment skipped)`);
          } else if (isFailedStatus(updated.status)) {
            toast.error(`Failed to index "${resourceName}": ${updated.error_message || "Unknown error"}`);
          } else if (isProcessingStatus(updated.status)) {
            setTimeout(checkStatus, 3000); // Git repos take longer, poll less frequently
          }
        } catch (error) {
          console.error("Failed to check index status:", error);
        }
      };
      setTimeout(checkStatus, 3000);
    } catch (error) {
      console.error("Failed to add git repository:", error);
      setGitError("Failed to add repository. Please try again.");
      toast.error("Failed to add repository. Please try again.");
    } finally {
      setIsAddingGit(false);
    }
  };

  // Load library resources when the dialog opens
  const loadLibraryResources = async () => {
    setIsLoadingLibrary(true);
    try {
      const resources = await listGlobalResources(0, 100, "ready");
      setLibraryResources(resources);
    } catch (error) {
      console.error("Failed to load library resources:", error);
      toast.error("Failed to load resource library");
    } finally {
      setIsLoadingLibrary(false);
    }
  };

  // Link a library resource to the current project
  const handleLinkResource = async (resourceId: string) => {
    setLinkingResourceId(resourceId);
    try {
      await linkResourceToProject(projectId, resourceId);
      onRefresh();
      setAddDialogOpen(false);
      toast.success("Resource added to project");
    } catch (error) {
      console.error("Failed to link resource:", error);
      if (error instanceof Error && error.message.includes("already linked")) {
        toast.error("Resource is already in this project");
      } else {
        toast.error("Failed to add resource to project");
      }
    } finally {
      setLinkingResourceId(null);
    }
  };

  // Check if a resource is already in the current project
  const isResourceInProject = (resourceId: string) => {
    return resources.some(r => r.id === resourceId);
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    handleFiles(e.dataTransfer.files);
  }, [projectId]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
  }, []);

  const handleDelete = async (resourceId: string) => {
    if (!confirm("Remove this resource from the project?")) return;
    try {
      await deleteResource(projectId, resourceId);
      onRefresh();
      toast.success("Resource removed from project");
    } catch (error) {
      console.error("Failed to remove:", error);
      toast.error("Failed to remove resource");
    }
  };

  const handleReindex = async (resourceId: string) => {
    try {
      const resource = await reindexResource(projectId, resourceId);
      const resourceName = resource.filename || resource.source;
      const originalWorkspaceId = projectId;
      onRefresh();

      // Poll for completion using the API
      const checkStatus = async (): Promise<void> => {
        // Stop polling if workspace changed
        if (currentProjectIdRef.current !== originalWorkspaceId) return;
        try {
          const updated = await getResource(originalWorkspaceId, resourceId);
          // Check again after the async call
          if (currentProjectIdRef.current !== originalWorkspaceId) return;
          onRefresh();

          if (isReadyStatus(updated.status)) {
            const duration = updated.indexing_duration_ms ? ` in ${formatDuration(updated.indexing_duration_ms)}` : "";
            toast.success(`Reindexed "${resourceName}"${duration}`);
          } else if (isPartialStatus(updated.status)) {
            toast.success(`Reprocessed "${resourceName}" (partial - enrichment skipped)`);
          } else if (isFailedStatus(updated.status)) {
            toast.error(`Failed to reindex "${resourceName}"`);
          } else if (isProcessingStatus(updated.status)) {
            // Still processing, check again in 2 seconds
            setTimeout(checkStatus, 2000);
          }
        } catch (error) {
          console.error("Failed to check reindex status:", error);
        }
      };
      // Start polling after a short delay
      setTimeout(checkStatus, 2000);
    } catch (error) {
      console.error("Failed to reindex:", error);
      toast.error("Failed to start reindex. Please try again.");
    }
  };

  const handleOpenResource = (resource: Resource) => {
    if (resource.type === "website") {
      // Open website URL in new tab
      window.open(resource.source, "_blank", "noopener,noreferrer");
    } else if (resource.type === "document" || resource.type === "data_file" || resource.type === "image") {
      // Open viewer dialog for documents, data files, and images
      setViewingResource(resource);
    } else if (resource.type === "git_repository") {
      // Open git URL in new tab
      window.open(resource.source, "_blank", "noopener,noreferrer");
    }
  };

  const getFileExtension = (filename: string | null): string => {
    if (!filename) return "";
    return filename.split(".").pop()?.toLowerCase() || "";
  };

  const isPdf = (resource: Resource): boolean => {
    return getFileExtension(resource.filename) === "pdf";
  };

  const handleAddResourceClick = () => {
    setAddDialogOpen(true);
  };

  const handleDialogClose = (open: boolean) => {
    setAddDialogOpen(open);
    if (!open) {
      // Reset state when closing
      setUrlInput("");
      setUrlError(null);
      setGitUrlInput("");
      setGitBranchInput("");
      setGitError(null);
    }
  };

  return (
    <>
      <div
        className={`h-full flex flex-col transition-colors rounded-lg ${
          dragActive ? "bg-primary/10 ring-2 ring-primary ring-inset" : ""
        }`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {/* Resource list */}
        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="space-y-1.5">
            {resources.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-4">
                {dragActive ? "Drop files here" : "No resources yet"}
              </p>
            )}
            {resources.map((resource) => {
                const isExpanded = expandedResources.has(resource.id);
                const canReindex = isReadyStatus(resource.status) || isFailedStatus(resource.status) || isPartialStatus(resource.status);
                const isProcessing = isProcessingStatus(resource.status);
                const isReady = isReadyStatus(resource.status) || isPartialStatus(resource.status);

                return (
                  <div key={resource.id} className="rounded-md bg-muted/50 overflow-hidden">
                    {/* Main row - always visible */}
                    <div
                      className="flex items-center p-2 text-xs cursor-pointer hover:bg-muted/80"
                      onClick={() => toggleExpanded(resource.id)}
                    >
                      <ChevronIcon
                        className="w-3 h-3 flex-shrink-0 mr-1.5 text-muted-foreground"
                        expanded={isExpanded}
                      />
                      {isProcessing ? (
                        <Spinner className="w-3 h-3 flex-shrink-0 mr-2 text-blue-500" />
                      ) : (
                        <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 mr-2 ${getStatusColor(resource.status)}`} />
                      )}
                      {/* Resource type icon */}
                      <ResourceTypeIcon type={resource.type} className="w-3.5 h-3.5 flex-shrink-0 mr-1.5 text-muted-foreground" />
                      <div className="flex-1 min-w-0 flex items-center gap-2">
                        <span
                          className={`truncate ${isReady ? "hover:underline cursor-pointer" : ""}`}
                          onClick={(e) => {
                            if (isReady) {
                              e.stopPropagation();
                              handleOpenResource(resource);
                            }
                          }}
                        >
                          {resource.filename || resource.source}
                        </span>
                        {/* Inline metadata badges */}
                        {resource.type === "data_file" && resource.data_metadata?.row_count && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-500 whitespace-nowrap">
                            {formatRowCount(resource.data_metadata.row_count)} rows
                          </span>
                        )}
                        {resource.type === "image" && resource.image_metadata?.width && resource.image_metadata?.height && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-500 whitespace-nowrap">
                            {resource.image_metadata.width}×{resource.image_metadata.height}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Expanded content */}
                    {isExpanded && (
                      <div className="px-3 pb-3 pt-1 border-t border-border/50">
                        {/* Summary / Description */}
                        {(resource.summary || resource.data_metadata?.content_description || resource.image_metadata?.vision_description) && (
                          <p className="text-xs text-muted-foreground mb-2 line-clamp-3">
                            {resource.summary || resource.data_metadata?.content_description || resource.image_metadata?.vision_description}
                          </p>
                        )}

                        {/* Data file metadata - columns */}
                        {resource.type === "data_file" && resource.data_metadata?.columns && resource.data_metadata.columns.length > 0 && (
                          <div className="mb-2">
                            <span className="text-xs text-muted-foreground">Columns: </span>
                            <span className="text-xs font-mono">
                              {resource.data_metadata.columns.slice(0, 6).map(c => c.name).join(", ")}
                              {resource.data_metadata.columns.length > 6 && ` +${resource.data_metadata.columns.length - 6} more`}
                            </span>
                          </div>
                        )}

                        {/* Image metadata - format */}
                        {resource.type === "image" && resource.image_metadata?.format && (
                          <div className="mb-2">
                            <span className="text-xs text-muted-foreground">Format: </span>
                            <span className="text-xs font-mono uppercase">{resource.image_metadata.format}</span>
                          </div>
                        )}

                        {/* Stats row */}
                        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground mb-3">
                          {resource.indexed_at && (
                            <span>Indexed {formatRelativeTime(resource.indexed_at)}</span>
                          )}
                          {resource.indexing_duration_ms && (
                            <span>Took {formatDuration(resource.indexing_duration_ms)}</span>
                          )}
                          {resource.file_size_bytes && (
                            <span>{formatFileSize(resource.file_size_bytes)}</span>
                          )}
                          {resource.commit_hash && (
                            <span className="font-mono">@{resource.commit_hash}</span>
                          )}
                          {/* Data file specific stats */}
                          {resource.type === "data_file" && resource.data_metadata?.row_count && (
                            <span>{formatRowCount(resource.data_metadata.row_count)} rows</span>
                          )}
                          {resource.type === "data_file" && resource.data_metadata?.column_count && (
                            <span>{resource.data_metadata.column_count} columns</span>
                          )}
                          {/* Image specific stats */}
                          {resource.type === "image" && resource.image_metadata?.width && resource.image_metadata?.height && (
                            <span>{resource.image_metadata.width}×{resource.image_metadata.height}px</span>
                          )}
                        </div>

                        {/* Error message */}
                        {resource.error_message && (
                          <p className="text-xs text-destructive mb-3">
                            Error: {resource.error_message}
                          </p>
                        )}

                        {/* Action buttons */}
                        <div className="flex items-center gap-1">
                          {/* Reindex button */}
                          {canReindex && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 w-6 p-0"
                              title="Reindex"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleReindex(resource.id);
                              }}
                            >
                              <RefreshIcon className="w-3.5 h-3.5" />
                            </Button>
                          )}

                          {/* Remove button */}
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 p-0 text-destructive hover:text-destructive"
                            title="Remove from project"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDelete(resource.id);
                            }}
                          >
                            <TrashIcon className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}

            {/* Add Resource button */}
            <Button
              variant="outline"
              size="sm"
              className="w-full mt-2"
              onClick={handleAddResourceClick}
              disabled={isUploading}
            >
              {isUploading ? "Uploading..." : "Add Resource"}
            </Button>
          </div>
        </div>
      </div>

      {/* Resource viewer dialog */}
      <Dialog open={!!viewingResource} onOpenChange={() => setViewingResource(null)}>
        <DialogContent className="w-[95vw] !max-w-[95vw] h-[95vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {viewingResource && <ResourceTypeIcon type={viewingResource.type} className="w-4 h-4" />}
              {viewingResource?.filename}
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-hidden">
            {viewingResource && (
              isPdf(viewingResource) ? (
                <PdfViewer
                  url={getResourceFileUrl(projectId, viewingResource.id)}
                />
              ) : viewingResource.type === "image" ? (
                // Image preview
                <div className="h-full flex flex-col items-center justify-center gap-4 p-4">
                  <div className="flex-1 flex items-center justify-center overflow-auto">
                    <AuthenticatedImage
                      src={getResourceFileUrl(projectId, viewingResource.id)}
                      alt={viewingResource.filename || "Image"}
                      className="max-w-full max-h-full object-contain"
                    />
                  </div>
                  {viewingResource.image_metadata?.vision_description && (
                    <div className="w-full max-w-2xl text-sm text-muted-foreground border-t pt-4">
                      <span className="font-medium text-foreground">AI Description: </span>
                      {viewingResource.image_metadata.vision_description}
                    </div>
                  )}
                </div>
              ) : viewingResource.type === "data_file" ? (
                // Data file preview - show metadata and download option
                <div className="h-full flex flex-col items-center justify-center gap-4 p-4">
                  <TableIcon className="w-16 h-16 text-muted-foreground" />
                  {viewingResource.data_metadata && (
                    <div className="text-center space-y-2">
                      {viewingResource.data_metadata.row_count && (
                        <p className="text-lg font-medium">
                          {formatRowCount(viewingResource.data_metadata.row_count)} rows × {viewingResource.data_metadata.column_count} columns
                        </p>
                      )}
                      {viewingResource.data_metadata.content_description && (
                        <p className="text-sm text-muted-foreground max-w-lg">
                          {viewingResource.data_metadata.content_description}
                        </p>
                      )}
                      {viewingResource.data_metadata.columns && viewingResource.data_metadata.columns.length > 0 && (
                        <div className="mt-4 text-left max-w-lg mx-auto">
                          <p className="text-sm font-medium mb-2">Columns:</p>
                          <div className="flex flex-wrap gap-2">
                            {viewingResource.data_metadata.columns.map((col) => (
                              <span
                                key={col.name}
                                className="text-xs px-2 py-1 rounded bg-muted font-mono"
                                title={`Type: ${col.dtype}`}
                              >
                                {col.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                  <Button asChild className="mt-4">
                    <a
                      href={getResourceFileUrl(projectId, viewingResource.id)}
                      download={viewingResource.filename}
                    >
                      Download File
                    </a>
                  </Button>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center h-full gap-4">
                  <p className="text-muted-foreground">
                    Preview not available for this file type
                  </p>
                  <Button asChild>
                    <a
                      href={getResourceFileUrl(projectId, viewingResource.id)}
                      download={viewingResource.filename}
                    >
                      Download File
                    </a>
                  </Button>
                </div>
              )
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Add Resource dialog */}
      <Dialog open={addDialogOpen} onOpenChange={handleDialogClose}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add Resource</DialogTitle>
          </DialogHeader>
          <Tabs defaultValue="library" className="w-full" onValueChange={(value) => {
            if (value === "library") {
              loadLibraryResources();
            }
          }}>
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="library" className="flex items-center gap-1.5 text-xs" onClick={() => loadLibraryResources()}>
                <LibraryIcon className="h-3.5 w-3.5" />
                <span>Library</span>
              </TabsTrigger>
              <TabsTrigger value="upload" className="flex items-center gap-1.5 text-xs">
                <ComputerIcon className="h-3.5 w-3.5" />
                <span>File</span>
              </TabsTrigger>
              <TabsTrigger value="url" className="flex items-center gap-1.5 text-xs">
                <GlobeIcon className="h-3.5 w-3.5" />
                <span>Website</span>
              </TabsTrigger>
              <TabsTrigger value="git" className="flex items-center gap-1.5 text-xs">
                <GitBranchIcon className="h-3.5 w-3.5" />
                <span>Git Repo</span>
              </TabsTrigger>
            </TabsList>

            {/* Library Tab */}
            <TabsContent value="library" className="mt-4">
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {isLoadingLibrary ? (
                  <div className="flex items-center justify-center py-8">
                    <Spinner className="h-6 w-6 text-muted-foreground" />
                  </div>
                ) : libraryResources.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-8">
                    No resources in library yet. Upload a file, add a website, or add a git repository to get started.
                  </p>
                ) : (
                  libraryResources.map((resource) => {
                    const inProject = isResourceInProject(resource.id);
                    return (
                      <div
                        key={resource.id}
                        className="flex items-center justify-between p-3 rounded-md bg-muted/50 hover:bg-muted/80"
                      >
                        <div className="flex-1 min-w-0 mr-3">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium truncate">
                              {resource.filename || resource.source}
                            </span>
                            {resource.is_shared && (
                              <span className="text-xs px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-500">
                                Shared
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-xs text-muted-foreground capitalize">
                              {resource.type.replace("_", " ")}
                            </span>
                            {resource.project_count > 1 && (
                              <span className="text-xs text-muted-foreground">
                                Used in {resource.project_count} projects
                              </span>
                            )}
                          </div>
                        </div>
                        {inProject ? (
                          <span className="flex items-center gap-1 text-xs text-green-500">
                            <CheckIcon className="h-3.5 w-3.5" />
                            Added
                          </span>
                        ) : (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => handleLinkResource(resource.id)}
                            disabled={linkingResourceId === resource.id}
                          >
                            {linkingResourceId === resource.id ? (
                              <Spinner className="h-3.5 w-3.5" />
                            ) : (
                              <>
                                <PlusIcon className="h-3.5 w-3.5 mr-1" />
                                Add
                              </>
                            )}
                          </Button>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
              <p className="text-xs text-muted-foreground text-center mt-4">
                Add existing resources from your library without re-indexing
              </p>
            </TabsContent>

            {/* File Upload Tab */}
            <TabsContent value="upload" className="mt-4">
              <div
                className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
                  dragActive
                    ? "border-primary bg-primary/5"
                    : "border-muted-foreground/25 hover:border-muted-foreground/50"
                }`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragActive(true);
                }}
                onDragLeave={(e) => {
                  e.preventDefault();
                  setDragActive(false);
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragActive(false);
                  handleFiles(e.dataTransfer.files, true);
                }}
              >
                <UploadIcon className="h-10 w-10 mx-auto mb-4 text-muted-foreground" />
                <p className="text-sm text-muted-foreground mb-2">
                  Drag and drop files here, or
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isUploading}
                >
                  {isUploading ? "Uploading..." : "Browse Files"}
                </Button>
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  multiple
                  accept=".pdf,.docx,.md,.txt,.markdown,.html,.csv,.xlsx,.xls,.json,.parquet,.tsv,.png,.jpg,.jpeg,.gif,.webp,.svg,.bmp,.tiff"
                  onChange={(e) => {
                    handleFiles(e.target.files, true);
                    // Reset the input so the same file can be selected again
                    e.target.value = "";
                  }}
                />
                <p className="text-xs text-muted-foreground mt-4">
                  Documents: PDF, DOCX, MD, TXT | Data: CSV, Excel, JSON | Images: PNG, JPG, GIF
                </p>
              </div>
            </TabsContent>

            {/* URL Tab */}
            <TabsContent value="url" className="mt-4">
              <div className="space-y-4">
                <div className="space-y-2">
                  <Input
                    placeholder="https://example.com/page"
                    value={urlInput}
                    onChange={(e) => {
                      setUrlInput(e.target.value);
                      setUrlError(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        handleAddUrl();
                      }
                    }}
                    disabled={isAddingUrl}
                  />
                  {urlError && (
                    <p className="text-sm text-destructive">{urlError}</p>
                  )}
                </div>
                <Button
                  className="w-full"
                  onClick={handleAddUrl}
                  disabled={isAddingUrl || !urlInput.trim()}
                >
                  {isAddingUrl ? (
                    <>
                      <Spinner className="h-4 w-4 mr-2" />
                      Adding...
                    </>
                  ) : (
                    "Add Website"
                  )}
                </Button>
                <p className="text-xs text-muted-foreground text-center">
                  The website content will be fetched and indexed for search
                </p>
              </div>
            </TabsContent>

            {/* Git Repository Tab */}
            <TabsContent value="git" className="mt-4">
              <div className="space-y-4">
                <div className="space-y-2">
                  <Input
                    placeholder="https://github.com/user/repo"
                    value={gitUrlInput}
                    onChange={(e) => {
                      setGitUrlInput(e.target.value);
                      setGitError(null);
                    }}
                    disabled={isAddingGit}
                  />
                  <Input
                    placeholder="Branch (optional, uses default)"
                    value={gitBranchInput}
                    onChange={(e) => setGitBranchInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        handleAddGit();
                      }
                    }}
                    disabled={isAddingGit}
                  />
                  {gitError && (
                    <p className="text-sm text-destructive">{gitError}</p>
                  )}
                </div>
                <Button
                  className="w-full"
                  onClick={handleAddGit}
                  disabled={isAddingGit || !gitUrlInput.trim()}
                >
                  {isAddingGit ? (
                    <>
                      <Spinner className="h-4 w-4 mr-2" />
                      Adding...
                    </>
                  ) : (
                    "Add Repository"
                  )}
                </Button>
                <p className="text-xs text-muted-foreground text-center">
                  Public repositories only. All text files will be indexed.
                </p>
              </div>
            </TabsContent>
          </Tabs>
        </DialogContent>
      </Dialog>
    </>
  );
}
