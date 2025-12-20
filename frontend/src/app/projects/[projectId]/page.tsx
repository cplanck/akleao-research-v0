"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { ResourcePanel } from "@/components/resource-panel";
import { FindingsDialog } from "@/components/findings-dialog";
import { ChatInterface } from "@/components/chat-interface";
import { UserAvatar } from "@/components/user-avatar";
import { Menu, Plus, Folder, Home, Library, ListChecks, Lightbulb, ChevronRight, CornerDownRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import Image from "next/image";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import Link from "next/link";
import { useProject } from "@/contexts/project-context";
import { Thread } from "@/lib/api";
import { NotificationBell } from "@/components/notification-bell";
import { LoadingSpinner } from "@/components/ui/loading-spinner";

// Custom hook to detect mobile screens
function useIsMobile(breakpoint: number = 768) {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < breakpoint);
    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, [breakpoint]);

  return isMobile;
}


// Typewriter title component for animated thread titles
function TypewriterTitle({
  text,
  isAnimating,
  onAnimationComplete
}: {
  text: string;
  isAnimating: boolean;
  onAnimationComplete?: () => void;
}) {
  const [displayedText, setDisplayedText] = useState(text);
  const animationRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (isAnimating && text !== "New Thread") {
      setDisplayedText("");
      let currentIndex = 0;

      const typeNextChar = () => {
        if (currentIndex < text.length) {
          setDisplayedText(text.slice(0, currentIndex + 1));
          currentIndex++;
          animationRef.current = setTimeout(typeNextChar, 30);
        } else {
          onAnimationComplete?.();
        }
      };

      animationRef.current = setTimeout(typeNextChar, 100);

      return () => {
        if (animationRef.current) {
          clearTimeout(animationRef.current);
        }
      };
    } else {
      setDisplayedText(text);
    }
  }, [text, isAnimating, onAnimationComplete]);

  return <span className="truncate">{displayedText}</span>;
}


// Recursive thread item component
function ThreadItem({
  thread,
  allThreads,
  selectedThreadId,
  onSelect,
  onDelete,
  onPrefetch,
  animatingThreadId,
  onAnimationComplete,
  depth = 0,
  maxDepth = 5,
  expandedThreads,
  onToggleExpand,
  activeThreadIds,
}: {
  thread: Thread;
  allThreads: Thread[];
  selectedThreadId?: string | null;
  onSelect: (threadId: string) => void;
  onDelete: (threadId: string) => void;
  onPrefetch?: (threadId: string) => void;
  animatingThreadId?: string | null;
  onAnimationComplete?: () => void;
  depth?: number;
  maxDepth?: number;
  expandedThreads: Set<string>;
  onToggleExpand: (threadId: string) => void;
  activeThreadIds: Set<string>;
}) {
  const children = allThreads.filter(t => t.parent_thread_id === thread.id);
  const hasChildren = thread.child_count > 0 || children.length > 0;
  const isExpanded = expandedThreads.has(thread.id);
  const isChild = depth > 0;
  const isSelected = selectedThreadId === thread.id;
  const indentLevel = Math.min(depth, maxDepth);
  const hasActiveJob = activeThreadIds.has(thread.id);

  return (
    <>
      <div
        className={`group flex items-center justify-between px-2 py-2 md:py-1.5 rounded text-sm cursor-pointer transition-colors ${
          isSelected ? "bg-accent" : "hover:bg-accent/50"
        }`}
        style={{ marginLeft: `${indentLevel * 16}px` }}
        onClick={() => onSelect(thread.id)}
        onMouseEnter={() => onPrefetch?.(thread.id)}
      >
        <div className="flex items-center gap-1 min-w-0 flex-1">
          {hasChildren ? (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onToggleExpand(thread.id);
              }}
              className="p-0.5 hover:bg-accent rounded shrink-0"
            >
              <ChevronRight className={`h-3 w-3 text-muted-foreground transition-transform duration-200 ${isExpanded ? "rotate-90" : ""}`} />
            </button>
          ) : (
            <span className="w-4 shrink-0" />
          )}
          {isChild && <CornerDownRight className="h-3 w-3 text-muted-foreground shrink-0 mr-1" />}
          <span className={`min-w-0 truncate ${hasActiveJob ? "shimmer-text" : ""}`}>
            <TypewriterTitle
              text={thread.title}
              isAnimating={animatingThreadId === thread.id}
              onAnimationComplete={onAnimationComplete}
            />
          </span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 md:h-5 md:w-5 p-0 opacity-50 md:opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            onDelete(thread.id);
          }}
        >
          ×
        </Button>
      </div>

      {hasChildren && isExpanded && (
        <div className="space-y-0.5">
          {children.map((child) => (
            <ThreadItem
              key={child.id}
              thread={child}
              allThreads={allThreads}
              selectedThreadId={selectedThreadId}
              onSelect={onSelect}
              onDelete={onDelete}
              onPrefetch={onPrefetch}
              animatingThreadId={animatingThreadId}
              onAnimationComplete={onAnimationComplete}
              depth={depth + 1}
              maxDepth={maxDepth}
              expandedThreads={expandedThreads}
              onToggleExpand={onToggleExpand}
              activeThreadIds={activeThreadIds}
            />
          ))}
        </div>
      )}
    </>
  );
}

// Thread list component
function ThreadList({
  threads,
  selectedThread,
  onSelectThread,
  onDeleteThread,
  onCreateClick,
  onPrefetchThread,
  animatingThreadId,
  onAnimationComplete,
  activeThreadIds,
}: {
  threads: Thread[];
  selectedThread: Thread | null;
  onSelectThread: (id: string) => void;
  onDeleteThread: (id: string) => void;
  onCreateClick: () => void;
  onPrefetchThread?: (threadId: string) => void;
  animatingThreadId?: string | null;
  onAnimationComplete?: () => void;
  activeThreadIds: Set<string>;
}) {
  const [expandedThreads, setExpandedThreads] = useState<Set<string>>(new Set());

  const getAncestorIds = useCallback((threadId: string): string[] => {
    const ancestors: string[] = [];
    let current = threads.find(t => t.id === threadId);
    while (current?.parent_thread_id) {
      ancestors.push(current.parent_thread_id);
      current = threads.find(t => t.id === current!.parent_thread_id);
    }
    return ancestors;
  }, [threads]);

  useEffect(() => {
    const parentIds = new Set<string>();
    threads.forEach(t => {
      if (t.child_count > 0) {
        parentIds.add(t.id);
      }
      if (t.parent_thread_id) {
        parentIds.add(t.parent_thread_id);
      }
    });

    if (parentIds.size > 0) {
      setExpandedThreads(prev => {
        const next = new Set(prev);
        parentIds.forEach(id => next.add(id));
        return next;
      });
    }
  }, [threads]);

  useEffect(() => {
    if (selectedThread) {
      const ancestors = getAncestorIds(selectedThread.id);
      if (ancestors.length > 0) {
        setExpandedThreads(prev => {
          const next = new Set(prev);
          ancestors.forEach(id => next.add(id));
          return next;
        });
      }
    }
  }, [selectedThread, getAncestorIds]);

  const rootThreads = threads.filter(t => !t.parent_thread_id);

  const toggleExpand = (threadId: string) => {
    setExpandedThreads(prev => {
      const next = new Set(prev);
      if (next.has(threadId)) {
        next.delete(threadId);
      } else {
        next.add(threadId);
      }
      return next;
    });
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto overflow-x-hidden p-2">
        {threads.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-4">
            No threads yet
          </p>
        ) : (
          <div className="space-y-0.5">
            {rootThreads.map((thread) => (
              <ThreadItem
                key={thread.id}
                thread={thread}
                allThreads={threads}
                selectedThreadId={selectedThread?.id}
                onSelect={onSelectThread}
                onDelete={onDeleteThread}
                onPrefetch={onPrefetchThread}
                animatingThreadId={animatingThreadId}
                onAnimationComplete={onAnimationComplete}
                depth={0}
                expandedThreads={expandedThreads}
                onToggleExpand={toggleExpand}
                activeThreadIds={activeThreadIds}
              />
            ))}
          </div>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start text-muted-foreground hover:text-foreground mt-1"
          onClick={onCreateClick}
        >
          + New Thread
        </Button>
      </div>
    </div>
  );
}

export default function ProjectPage() {
  const router = useRouter();
  const {
    projects,
    projectsLoading,
    projectDetailLoading,
    selectedProject,
    selectedThread,
    fetchProjects,
    fetchProjectDetail,
    selectThread,
    handleCreateProject,
    handleDeleteProject,
    handleCreateThread,
    handleDeleteThread,
    handleNavigateToThread,
    handleThreadTitleGenerated,
    handleRulesChange,
    animatingThreadId,
    setAnimatingThreadId,
    findingsRefreshTrigger,
    triggerFindingsRefresh,
    buildAncestorChain,
    parseRules,
    activeThreadIds,  // Get from context - updated via unified WebSocket
    prefetchMessages,
  } = useProject();

  const [newProjectName, setNewProjectName] = useState("");
  const [isProjectDialogOpen, setIsProjectDialogOpen] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [threadSheetOpen, setThreadSheetOpen] = useState(false);
  const [resourceSheetOpen, setResourceSheetOpen] = useState(false);
  const [isRulesDialogOpen, setIsRulesDialogOpen] = useState(false);
  const [isFindingsDialogOpen, setIsFindingsDialogOpen] = useState(false);
  const isMobile = useIsMobile();

  // Navigate to thread URL when selecting a thread
  const handleSelectThread = (threadId: string) => {
    if (!selectedProject) return;
    selectThread(threadId);
    router.push(`/projects/${selectedProject.id}/threads/${threadId}`);
    setThreadSheetOpen(false);
  };

  // Navigate when selecting a project
  const handleSelectProject = async (id: string) => {
    router.push(`/projects/${id}`);
  };

  // Create thread and navigate
  const handleCreateThreadAndNavigate = async () => {
    const thread = await handleCreateThread();
    if (thread && selectedProject) {
      router.push(`/projects/${selectedProject.id}/threads/${thread.id}`);
      setThreadSheetOpen(false); // Close sidebar on mobile
    }
  };

  // Delete thread handler
  const handleDeleteThreadWithConfirm = async (threadId: string) => {
    if (!confirm("Delete this thread and all its messages?")) return;
    await handleDeleteThread(threadId);
  };

  // Create project and navigate to its first thread
  const handleCreateProjectAndNavigate = async () => {
    if (!newProjectName.trim()) return;
    setIsCreating(true);
    try {
      const result = await handleCreateProject(newProjectName.trim());
      setNewProjectName("");
      setIsProjectDialogOpen(false);
      if (result) {
        router.push(`/projects/${result.project.id}/threads/${result.thread.id}`);
      }
    } finally {
      setIsCreating(false);
    }
  };

  // Handle navigation callback from ChatInterface (for subthreads)
  const handleNavigateToThreadWithUrl = (thread: Thread) => {
    handleNavigateToThread(thread);
    if (selectedProject) {
      router.push(`/projects/${selectedProject.id}/threads/${thread.id}`);
    }
  };

  const handleTitleAnimationComplete = () => {
    setAnimatingThreadId(null);
  };

  // Prefetch messages when hovering over a thread
  const handlePrefetchThread = useCallback((threadId: string) => {
    if (selectedProject) {
      prefetchMessages(selectedProject.id, threadId);
    }
  }, [selectedProject, prefetchMessages]);

  // Show loading until both projects list and specific project are loaded
  if (projectsLoading || projectDetailLoading) {
    return <LoadingSpinner fullScreen size="lg" />;
  }

  // Mobile layout
  if (isMobile) {
    return (
      <div className="h-dvh bg-background flex flex-col overflow-hidden">
        {/* Mobile header */}
        <div className="flex-shrink-0 border-b px-3 py-2 flex items-center justify-between bg-background relative">
          <Sheet open={threadSheetOpen} onOpenChange={setThreadSheetOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                <Menu className="h-[18px] w-[18px]" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-[280px] p-0">
              <SheetHeader className="p-3 border-b">
                <SheetTitle className="text-sm">
                  <div className="flex items-center gap-1">
                    <Link href="/">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0"
                        title="All Projects"
                      >
                        <Home className="h-4 w-4" />
                      </Button>
                    </Link>
                    <Select
                      value={selectedProject?.id || ""}
                      onValueChange={(id) => {
                        handleSelectProject(id);
                        setThreadSheetOpen(false);
                      }}
                    >
                      <SelectTrigger className="flex-1">
                        <SelectValue placeholder="Select project" />
                      </SelectTrigger>
                      <SelectContent>
                        {projects.map((p) => (
                          <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </SheetTitle>
              </SheetHeader>
              {selectedProject && (
                <ThreadList
                  threads={selectedProject.threads}
                  selectedThread={selectedThread}
                  onSelectThread={handleSelectThread}
                  onDeleteThread={handleDeleteThreadWithConfirm}
                  onCreateClick={handleCreateThreadAndNavigate}
                  onPrefetchThread={handlePrefetchThread}
                  animatingThreadId={animatingThreadId}
                  onAnimationComplete={handleTitleAnimationComplete}
                  activeThreadIds={activeThreadIds}
                />
              )}
            </SheetContent>
          </Sheet>

          <span className="absolute left-1/2 -translate-x-1/2 font-semibold text-sm truncate max-w-[200px]">
            {selectedThread?.title || selectedProject?.name || "Select Project"}
          </span>

          <div className="flex items-center gap-1">
            {selectedProject && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={handleCreateThreadAndNavigate}
                title="New Thread"
              >
                <Plus className="h-[18px] w-[18px]" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0 mr-3 relative"
              onClick={() => setResourceSheetOpen(true)}
              title="Resources"
            >
              <Folder className="h-[18px] w-[18px]" />
              {selectedProject && selectedProject.resources.length > 0 && (
                <span className="absolute -top-0.5 -right-0.5 bg-primary text-primary-foreground text-[10px] rounded-full h-4 w-4 flex items-center justify-center">
                  {selectedProject.resources.length}
                </span>
              )}
            </Button>
            <UserAvatar size="sm" />
          </div>

          <Sheet open={resourceSheetOpen} onOpenChange={setResourceSheetOpen}>
            <SheetContent side="right" className="w-[300px] p-0">
                <SheetHeader className="px-3 py-2 border-b">
                  <SheetTitle className="flex items-center justify-end gap-1">
                    <Link href="/library">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0"
                        title="Resource Library"
                      >
                        <Library className="h-4 w-4" />
                      </Button>
                    </Link>
                    {selectedProject && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0 relative"
                        title="Rules"
                        onClick={() => {
                          setResourceSheetOpen(false);
                          setIsRulesDialogOpen(true);
                        }}
                      >
                        <ListChecks className="h-4 w-4" />
                        {parseRules(selectedProject.system_instructions).length > 0 && (
                          <span className="absolute -top-0.5 -right-0.5 bg-primary text-primary-foreground text-[10px] rounded-full h-4 w-4 flex items-center justify-center">
                            {parseRules(selectedProject.system_instructions).length}
                          </span>
                        )}
                      </Button>
                    )}
                    {selectedProject && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0"
                        title="Findings"
                        onClick={() => {
                          setResourceSheetOpen(false);
                          setIsFindingsDialogOpen(true);
                        }}
                      >
                        <Lightbulb className="h-4 w-4" />
                      </Button>
                    )}
                    {selectedProject && (
                      <NotificationBell
                        projectId={selectedProject.id}
                        onNavigateToThread={(threadId) => {
                          setResourceSheetOpen(false);
                          const thread = selectedProject.threads.find(t => t.id === threadId);
                          if (thread) {
                            handleNavigateToThreadWithUrl(thread);
                          } else {
                            router.push(`/projects/${selectedProject.id}/threads/${threadId}`);
                          }
                        }}
                      />
                    )}
                  </SheetTitle>
                </SheetHeader>
                <div className="p-3 h-[calc(100%-45px)]">
                  {selectedProject ? (
                    <ResourcePanel
                      projectId={selectedProject.id}
                      resources={selectedProject.resources}
                      onRefresh={() => fetchProjectDetail(selectedProject.id, false)}
                    />
                  ) : (
                    <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                      Select a project
                    </div>
                  )}
                </div>
              </SheetContent>
          </Sheet>
        </div>

        {/* Mobile chat area */}
        <div className="flex-1 overflow-hidden">
          {selectedProject && selectedThread ? (
            <ChatInterface
              key={selectedThread.id}
              projectId={selectedProject.id}
              threadId={selectedThread.id}
              threadTitle={selectedThread.title}
              parentThreadId={selectedThread.parent_thread_id}
              contextText={selectedThread.context_text}
              ancestorThreads={buildAncestorChain(selectedThread)}
              onResourceAdded={() => fetchProjectDetail(selectedProject.id, false)}
              onThreadTitleGenerated={handleThreadTitleGenerated}
              onNavigateToThread={handleNavigateToThreadWithUrl}
              resources={selectedProject.resources}
              rules={parseRules(selectedProject.system_instructions)}
              onRulesChange={handleRulesChange}
              isRulesDialogOpen={isRulesDialogOpen}
              onRulesDialogOpenChange={setIsRulesDialogOpen}
              onFindingSaved={triggerFindingsRefresh}
            />
          ) : selectedProject ? (
            <div className="flex-1 flex items-center justify-center text-muted-foreground h-full">
              <div className="text-center px-4">
                <p>No thread selected</p>
                <Button variant="outline" size="sm" className="mt-2" onClick={handleCreateThreadAndNavigate}>
                  Create Thread
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-muted-foreground h-full">
              <p className="text-center px-4">
                Tap the menu to select or create a project
              </p>
            </div>
          )}
        </div>

        {/* New project dialog */}
        <Dialog open={isProjectDialogOpen} onOpenChange={setIsProjectDialogOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>New Project</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 pt-4">
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input
                  id="name"
                  placeholder="My Project"
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleCreateProjectAndNavigate()}
                />
              </div>
              <Button
                onClick={handleCreateProjectAndNavigate}
                disabled={isCreating}
                className="w-full"
              >
                {isCreating ? "Creating..." : "Create"}
              </Button>
            </div>
          </DialogContent>
        </Dialog>

        {/* Findings Dialog - Mobile */}
        {selectedProject && (
          <FindingsDialog
            projectId={selectedProject.id}
            projectName={selectedProject.name}
            existingSummary={selectedProject.findings_summary}
            summaryUpdatedAt={selectedProject.findings_summary_updated_at}
            open={isFindingsDialogOpen}
            onOpenChange={setIsFindingsDialogOpen}
            onSummaryUpdated={() => fetchProjectDetail(selectedProject.id, false)}
          />
        )}
      </div>
    );
  }

  // Desktop layout
  return (
    <div className="h-dvh bg-background overflow-hidden">
      <ResizablePanelGroup direction="horizontal" className="h-full" autoSaveId="project-layout">
        {/* Left sidebar - Project selector and Threads */}
        <ResizablePanel defaultSize={15} minSize={25} maxSize={25}>
          <div className="h-full border-r flex flex-col bg-background">
            {/* Project selector */}
            <div className="px-3 py-2 border-b">
              <div className="flex items-center gap-1">
                <Link href="/">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 w-8 p-0"
                    title="Home -- view projects"
                    asChild={true}
                  >
                    <>
                    <Image src="/logos/logo-emblem-light.png" alt="Akleao" width={30} height={30} className="hidden dark:block"/>
                    <Image src="/logos/logo-emblem-dark.png" alt="Akleao" width={30} height={30} className="block dark:hidden" />
                    </>
                  </Button>
                </Link>
              </div>
            </div>

            {/* Thread list */}
            {selectedProject ? (
              <ThreadList
                threads={selectedProject.threads}
                selectedThread={selectedThread}
                onSelectThread={handleSelectThread}
                onDeleteThread={handleDeleteThreadWithConfirm}
                onCreateClick={handleCreateThreadAndNavigate}
                onPrefetchThread={handlePrefetchThread}
                animatingThreadId={animatingThreadId}
                onAnimationComplete={handleTitleAnimationComplete}
                activeThreadIds={activeThreadIds}
              />
            ) : (
              <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm p-4">
                Select a project
              </div>
            )}

            {/* New project dialog */}
            <Dialog open={isProjectDialogOpen} onOpenChange={setIsProjectDialogOpen}>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>New Project</DialogTitle>
                </DialogHeader>
                <div className="space-y-4 pt-4">
                  <div className="space-y-2">
                    <Label htmlFor="name">Name</Label>
                    <Input
                      id="name"
                      placeholder="My Project"
                      value={newProjectName}
                      onChange={(e) => setNewProjectName(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleCreateProjectAndNavigate()}
                    />
                  </div>
                  <Button
                    onClick={handleCreateProjectAndNavigate}
                    disabled={isCreating}
                    className="w-full"
                  >
                    {isCreating ? "Creating..." : "Create"}
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* Main chat area */}
        <ResizablePanel defaultSize={60} minSize={40}>
          <div className="h-full flex flex-col">
            {selectedProject && selectedThread ? (
              <ChatInterface
                key={selectedThread.id}
                projectId={selectedProject.id}
                threadId={selectedThread.id}
                threadTitle={selectedThread.title}
                parentThreadId={selectedThread.parent_thread_id}
                contextText={selectedThread.context_text}
                ancestorThreads={buildAncestorChain(selectedThread)}
                onResourceAdded={() => fetchProjectDetail(selectedProject.id, false)}
                onThreadTitleGenerated={handleThreadTitleGenerated}
                onNavigateToThread={handleNavigateToThreadWithUrl}
                resources={selectedProject.resources}
                rules={parseRules(selectedProject.system_instructions)}
                onRulesChange={handleRulesChange}
                isRulesDialogOpen={isRulesDialogOpen}
                onRulesDialogOpenChange={setIsRulesDialogOpen}
                onFindingSaved={triggerFindingsRefresh}
              />
            ) : selectedProject ? (
              <div className="flex-1 flex items-center justify-center text-muted-foreground">
                <div className="text-center">
                  <p>No thread selected</p>
                  <Button variant="outline" size="sm" className="mt-2" onClick={handleCreateThreadAndNavigate}>
                    Create Thread
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center text-muted-foreground">
                <p>Select or create a project to get started</p>
              </div>
            )}
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* Right sidebar - Resources */}
        <ResizablePanel defaultSize={18} minSize={15} maxSize={40}>
          <div className="h-full border-l flex flex-col bg-background">
            <div className="flex-1 flex flex-col overflow-hidden">
              {selectedProject ? (
                <>
                  <div className="px-3 py-2 border-b flex items-center justify-between">
                    <h3 className="text-sm font-semibold">Resources</h3>
                    <Link href="/library">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0"
                        title="View Resource Library"
                      >
                        <Library className="h-4 w-4" />
                      </Button>
                    </Link>
                  </div>
                  <div className="flex-1 p-3 overflow-auto min-h-0">
                    <ResourcePanel
                      projectId={selectedProject.id}
                      resources={selectedProject.resources}
                      onRefresh={() => fetchProjectDetail(selectedProject.id, false)}
                    />
                  </div>
                  <div className="border-t p-2 flex items-center justify-between">
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        onClick={() => setIsRulesDialogOpen(true)}
                      >
                        Rules
                        {parseRules(selectedProject.system_instructions).length > 0 && (
                          <span className="ml-1 bg-primary/10 text-primary rounded px-1">
                            {parseRules(selectedProject.system_instructions).length}
                          </span>
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        onClick={() => setIsFindingsDialogOpen(true)}
                      >
                        Findings
                      </Button>
                    </div>
                    <div className="flex items-center gap-1">
                      <NotificationBell
                        projectId={selectedProject.id}
                        onNavigateToThread={(threadId) => {
                          const thread = selectedProject.threads.find(t => t.id === threadId);
                          if (thread) {
                            handleNavigateToThreadWithUrl(thread);
                          } else {
                            router.push(`/projects/${selectedProject.id}/threads/${threadId}`);
                          }
                        }}
                      />
                      <UserAvatar size="sm" />
                    </div>
                  </div>
                </>
              ) : (
                <div className="flex items-center justify-center h-full text-muted-foreground text-sm p-3">
                  Select a project
                </div>
              )}
            </div>
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>

      {/* Findings Dialog */}
      {selectedProject && (
        <FindingsDialog
          projectId={selectedProject.id}
          projectName={selectedProject.name}
          existingSummary={selectedProject.findings_summary}
          summaryUpdatedAt={selectedProject.findings_summary_updated_at}
          open={isFindingsDialogOpen}
          onOpenChange={setIsFindingsDialogOpen}
          onSummaryUpdated={() => fetchProjectDetail(selectedProject.id, false)}
        />
      )}
    </div>
  );
}
