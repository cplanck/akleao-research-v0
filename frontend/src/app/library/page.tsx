"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";
import { UserAvatar } from "@/components/user-avatar";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  GlobalResource,
  Project,
  ResourceChunk,
  ResourceChunksResponse,
  listGlobalResources,
  listProjects,
  deleteGlobalResource,
  linkResourceToProject,
  unlinkResourceFromProject,
  getResourceFileUrl,
  getResourceChunks,
} from "@/lib/api";
import { toast } from "sonner";

// Icon components
function ArrowLeftIcon({ className }: { className?: string }) {
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
      <path d="m12 19-7-7 7-7" />
      <path d="M19 12H5" />
    </svg>
  );
}

function FileTextIcon({ className }: { className?: string }) {
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
      <path d="M10 9H8" />
      <path d="M16 13H8" />
      <path d="M16 17H8" />
    </svg>
  );
}

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

function formatFileSize(bytes: number | null): string {
  if (!bytes) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function getResourceIcon(type: string) {
  switch (type) {
    case "document":
      return <FileTextIcon className="h-4 w-4" />;
    case "website":
      return <GlobeIcon className="h-4 w-4" />;
    case "git_repository":
      return <GitBranchIcon className="h-4 w-4" />;
    default:
      return <FileTextIcon className="h-4 w-4" />;
  }
}

function getStatusBadge(status: string) {
  const colors: Record<string, string> = {
    ready: "bg-green-500/10 text-green-600 dark:text-green-400",
    pending: "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400",
    indexing: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
    failed: "bg-red-500/10 text-red-600 dark:text-red-400",
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || "bg-gray-500/10 text-gray-600"}`}>
      {status}
    </span>
  );
}

function SearchIcon({ className }: { className?: string }) {
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
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}

export default function LibraryPage() {
  const [resources, setResources] = useState<GlobalResource[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedResource, setSelectedResource] = useState<GlobalResource | null>(null);
  const [isDetailOpen, setIsDetailOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [chunks, setChunks] = useState<ResourceChunk[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunksError, setChunksError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("details");

  const fetchData = async () => {
    try {
      const [resourcesData, projectsData] = await Promise.all([
        listGlobalResources(),
        listProjects(),
      ]);
      setResources(resourcesData);
      setProjects(projectsData);
    } catch (error) {
      console.error("Failed to fetch data:", error);
      toast.error("Failed to load resources");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleDelete = async (resource: GlobalResource) => {
    if (resource.projects.length > 0) {
      toast.error("Cannot delete: resource is still linked to projects");
      return;
    }
    if (!confirm("Permanently delete this resource from the library?")) return;

    setIsDeleting(true);
    try {
      await deleteGlobalResource(resource.id);
      toast.success("Resource deleted");
      setIsDetailOpen(false);
      fetchData();
    } catch (error) {
      console.error("Failed to delete resource:", error);
      toast.error("Failed to delete resource");
    } finally {
      setIsDeleting(false);
    }
  };

  const handleToggleProject = async (resource: GlobalResource, projectId: string) => {
    const isLinked = resource.projects.includes(projectId);
    try {
      if (isLinked) {
        await unlinkResourceFromProject(projectId, resource.id);
        toast.success("Resource unlinked from project");
      } else {
        await linkResourceToProject(projectId, resource.id);
        toast.success("Resource linked to project");
      }
      fetchData();
      // Update selected resource
      const updated = await listGlobalResources();
      const updatedResource = updated.find(r => r.id === resource.id);
      if (updatedResource) setSelectedResource(updatedResource);
    } catch (error) {
      console.error("Failed to toggle project link:", error);
      toast.error(isLinked ? "Failed to unlink resource" : "Failed to link resource");
    }
  };

  const getProjectName = (projectId: string): string => {
    const project = projects.find(p => p.id === projectId);
    return project?.name || projectId.slice(0, 8);
  };

  const loadChunks = async (resourceId: string) => {
    setChunksLoading(true);
    setChunksError(null);
    try {
      const response = await getResourceChunks(resourceId);
      setChunks(response.chunks);
    } catch (error) {
      console.error("Failed to load chunks:", error);
      setChunksError(error instanceof Error ? error.message : "Failed to load chunks");
      setChunks([]);
    } finally {
      setChunksLoading(false);
    }
  };

  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    if (tab === "chunks" && selectedResource && chunks.length === 0 && !chunksLoading) {
      loadChunks(selectedResource.id);
    }
  };

  // Filter resources based on search query
  const filteredResources = resources.filter((resource) => {
    if (!searchQuery.trim()) return true;
    const query = searchQuery.toLowerCase();
    const name = (resource.filename || resource.source || "").toLowerCase();
    const summary = (resource.summary || "").toLowerCase();
    const type = resource.type.toLowerCase();
    const projectNames = resource.projects
      .map(getProjectName)
      .join(" ")
      .toLowerCase();
    return (
      name.includes(query) ||
      summary.includes(query) ||
      type.includes(query) ||
      projectNames.includes(query)
    );
  });

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b">
        <div className="w-full px-4 sm:px-6 py-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div className="flex items-center gap-2 sm:gap-4 flex-wrap">
            <Link href="/">
              <Button variant="ghost" size="sm" className="gap-2">
                <ArrowLeftIcon className="h-4 w-4" />
                <span className="hidden sm:inline">Back to Chat</span>
                <span className="sm:hidden">Back</span>
              </Button>
            </Link>
            <h1 className="text-lg sm:text-xl font-semibold">Resource Library</h1>
            <span className="text-muted-foreground text-xs sm:text-sm">
              {filteredResources.length === resources.length
                ? `${resources.length} resource${resources.length !== 1 ? "s" : ""}`
                : `${filteredResources.length} of ${resources.length} resources`}
            </span>
          </div>
          <div className="flex items-center gap-2 sm:gap-4">
            {/* Search input */}
            <div className="relative flex-1 sm:flex-none">
              <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search resources..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-9 w-full sm:w-64 rounded-md border border-input bg-background pl-9 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
              />
            </div>
            <ThemeToggle />
            <UserAvatar />
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="w-full px-4 sm:px-6 py-4 sm:py-6">
        {resources.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-muted-foreground">No resources in the library yet.</p>
            <p className="text-sm text-muted-foreground mt-2">
              Upload documents, add URLs, or connect git repositories from a project.
            </p>
          </div>
        ) : filteredResources.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-muted-foreground">No resources match &quot;{searchQuery}&quot;</p>
            <Button
              variant="ghost"
              size="sm"
              className="mt-2"
              onClick={() => setSearchQuery("")}
            >
              Clear search
            </Button>
          </div>
        ) : (
          <>
            {/* Mobile card view */}
            <div className="sm:hidden space-y-3">
              {filteredResources.map((resource) => (
                <div
                  key={resource.id}
                  className="border rounded-lg p-4 cursor-pointer hover:bg-accent/50 active:bg-accent"
                  onClick={() => {
                    setSelectedResource(resource);
                    setIsDetailOpen(true);
                  }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3 min-w-0 flex-1">
                      <div className="mt-0.5 shrink-0">
                        {getResourceIcon(resource.type)}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="font-medium text-sm truncate">
                          {resource.filename || resource.source}
                        </div>
                        {resource.summary && (
                          <div className="text-xs text-muted-foreground truncate mt-0.5">
                            {resource.summary}
                          </div>
                        )}
                        <div className="flex items-center gap-2 mt-2 flex-wrap">
                          {getStatusBadge(resource.status)}
                          <span className="text-xs text-muted-foreground">
                            {formatFileSize(resource.file_size_bytes)}
                          </span>
                          {resource.projects.length > 0 && (
                            <span className="text-xs text-muted-foreground">
                              {resource.projects.length} project{resource.projects.length !== 1 ? "s" : ""}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive shrink-0"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(resource);
                      }}
                      disabled={resource.projects.length > 0}
                    >
                      <TrashIcon className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>

            {/* Desktop table view */}
            <div className="hidden sm:block border rounded-lg overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[40px]">Type</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="hidden md:table-cell">Size</TableHead>
                    <TableHead className="hidden lg:table-cell">Projects</TableHead>
                    <TableHead className="hidden md:table-cell">Added</TableHead>
                    <TableHead className="w-[80px]">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredResources.map((resource) => (
                    <TableRow
                      key={resource.id}
                      className="cursor-pointer hover:bg-accent/50"
                      onClick={() => {
                        setSelectedResource(resource);
                        setIsDetailOpen(true);
                      }}
                    >
                      <TableCell>{getResourceIcon(resource.type)}</TableCell>
                      <TableCell className="font-medium">
                        <div className="flex flex-col">
                          <span className="truncate max-w-[300px]">
                            {resource.filename || resource.source}
                          </span>
                          {resource.summary && (
                            <span className="text-xs text-muted-foreground truncate max-w-[300px]">
                              {resource.summary}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>{getStatusBadge(resource.status)}</TableCell>
                      <TableCell className="text-muted-foreground hidden md:table-cell">
                        {formatFileSize(resource.file_size_bytes)}
                      </TableCell>
                      <TableCell className="hidden lg:table-cell">
                        {resource.projects.length === 0 ? (
                          <span className="text-muted-foreground text-sm">None</span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {resource.projects.slice(0, 2).map((projectId) => (
                              <span
                                key={projectId}
                                className="bg-primary/10 text-primary text-xs px-2 py-0.5 rounded"
                              >
                                {getProjectName(projectId)}
                              </span>
                            ))}
                            {resource.projects.length > 2 && (
                              <span className="text-muted-foreground text-xs">
                                +{resource.projects.length - 2}
                              </span>
                            )}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="text-muted-foreground hidden md:table-cell">
                        {formatDate(resource.created_at)}
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDelete(resource);
                          }}
                          disabled={resource.projects.length > 0}
                          title={resource.projects.length > 0 ? "Unlink from all projects first" : "Delete resource"}
                        >
                          <TrashIcon className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </main>

      {/* Resource detail dialog */}
      <Dialog open={isDetailOpen} onOpenChange={setIsDetailOpen}>
        <DialogContent className="!max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-start sm:items-center gap-2 flex-col sm:flex-row">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                {selectedResource && getResourceIcon(selectedResource.type)}
                <span className="truncate">
                  {selectedResource?.filename || selectedResource?.source}
                </span>
              </div>
              {selectedResource && (
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2 shrink-0 w-full sm:w-auto"
                  onClick={() => {
                    // For websites and git repos, open source URL directly
                    // For documents, use the file endpoint with first linked project
                    if (selectedResource.type === "website" || selectedResource.type === "git_repository") {
                      window.open(selectedResource.source, "_blank");
                    } else if (selectedResource.projects.length > 0) {
                      // Use first linked project to view the document
                      const url = getResourceFileUrl(selectedResource.projects[0], selectedResource.id);
                      window.open(url, "_blank");
                    } else {
                      toast.error("Link resource to a project to view the file");
                    }
                  }}
                >
                  <ExternalLinkIcon className="h-4 w-4" />
                  View
                </Button>
              )}
            </DialogTitle>
            {selectedResource?.summary && (
              <DialogDescription className="text-left">
                {selectedResource.summary}
              </DialogDescription>
            )}
          </DialogHeader>

          {selectedResource && (
            <Tabs value={activeTab} onValueChange={handleTabChange} className="w-full">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="details">Details</TabsTrigger>
                <TabsTrigger value="projects">
                  Projects ({selectedResource.projects.length})
                </TabsTrigger>
                <TabsTrigger value="chunks" disabled={selectedResource.status !== "ready"}>
                  Chunks
                </TabsTrigger>
              </TabsList>

              <TabsContent value="details" className="space-y-4 mt-4">
                {/* Resource info */}
                <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                  <div className="text-muted-foreground">Status</div>
                  <div>{getStatusBadge(selectedResource.status)}</div>

                  <div className="text-muted-foreground">Type</div>
                  <div className="capitalize">{selectedResource.type.replace("_", " ")}</div>

                  <div className="text-muted-foreground">Size</div>
                  <div>{formatFileSize(selectedResource.file_size_bytes)}</div>

                  <div className="text-muted-foreground">Added</div>
                  <div>{formatDate(selectedResource.created_at)}</div>

                  {selectedResource.indexed_at && (
                    <>
                      <div className="text-muted-foreground">Indexed</div>
                      <div>{formatDate(selectedResource.indexed_at)}</div>
                    </>
                  )}

                  {selectedResource.content_hash && (
                    <>
                      <div className="text-muted-foreground">Content Hash</div>
                      <div className="font-mono text-xs truncate">
                        {selectedResource.content_hash.slice(0, 24)}...
                      </div>
                    </>
                  )}
                </div>

                {/* Source URL */}
                <div className="text-sm">
                  <div className="text-muted-foreground mb-1">Source</div>
                  <div className="font-mono text-xs bg-muted p-3 rounded break-all">
                    {selectedResource.source}
                  </div>
                </div>

                {/* Delete button */}
                {selectedResource.projects.length === 0 && (
                  <Button
                    variant="destructive"
                    className="w-full"
                    onClick={() => handleDelete(selectedResource)}
                    disabled={isDeleting}
                  >
                    {isDeleting ? "Deleting..." : "Delete from Library"}
                  </Button>
                )}
              </TabsContent>

              <TabsContent value="projects" className="mt-4">
                <div className="space-y-2">
                  {projects.length === 0 ? (
                    <p className="text-muted-foreground text-sm text-center py-4">
                      No projects available
                    </p>
                  ) : (
                    projects.map((project) => {
                      const isLinked = selectedResource.projects.includes(project.id);
                      return (
                        <div
                          key={project.id}
                          className="flex items-center justify-between p-3 rounded border"
                        >
                          <div className="flex flex-col">
                            <span className="font-medium">{project.name}</span>
                            <span className="text-xs text-muted-foreground">
                              {project.resource_count} resource{project.resource_count !== 1 ? "s" : ""}
                            </span>
                          </div>
                          <Button
                            variant={isLinked ? "secondary" : "outline"}
                            size="sm"
                            onClick={() => handleToggleProject(selectedResource, project.id)}
                          >
                            {isLinked ? "Linked" : "Link"}
                          </Button>
                        </div>
                      );
                    })
                  )}
                </div>

                {selectedResource.projects.length === 0 && (
                  <p className="text-muted-foreground text-sm text-center mt-4">
                    This resource is not linked to any projects yet.
                  </p>
                )}
              </TabsContent>

              <TabsContent value="chunks" className="mt-4">
                {chunksLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <p className="text-muted-foreground">Loading chunks...</p>
                  </div>
                ) : chunksError ? (
                  <div className="text-center py-8">
                    <p className="text-destructive">{chunksError}</p>
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-4"
                      onClick={() => loadChunks(selectedResource.id)}
                    >
                      Retry
                    </Button>
                  </div>
                ) : chunks.length === 0 ? (
                  <div className="text-center py-8">
                    <p className="text-muted-foreground">No chunks found for this resource.</p>
                    <p className="text-xs text-muted-foreground mt-2">
                      This may indicate the resource was indexed with an older namespace scheme.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="text-sm text-muted-foreground">
                      {chunks.length} chunk{chunks.length !== 1 ? "s" : ""} from RAG indexing
                    </div>
                    <div className="space-y-3 max-h-[400px] overflow-y-auto">
                      {chunks.map((chunk, index) => (
                        <div
                          key={chunk.id}
                          className="border rounded-lg p-3 text-sm space-y-2"
                        >
                          <div className="flex items-center justify-between text-xs text-muted-foreground">
                            <span className="font-medium">Chunk {chunk.chunk_index}</span>
                            <div className="flex items-center gap-2">
                              {chunk.metadata.page_numbers && (
                                <span>Pages: {chunk.metadata.page_numbers}</span>
                              )}
                              {chunk.metadata.line_start !== undefined && (
                                <span>
                                  Lines {chunk.metadata.line_start}-{chunk.metadata.line_end}
                                </span>
                              )}
                              {chunk.metadata.char_count && (
                                <span>{chunk.metadata.char_count} chars</span>
                              )}
                            </div>
                          </div>
                          <div className="font-mono text-xs bg-muted p-2 rounded max-h-[200px] overflow-y-auto whitespace-pre-wrap break-all">
                            {chunk.content}
                          </div>
                          {chunk.metadata.file_path && (
                            <div className="text-xs text-muted-foreground truncate">
                              {chunk.metadata.file_path}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </TabsContent>
            </Tabs>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
