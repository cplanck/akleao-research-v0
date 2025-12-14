"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Command } from "cmdk";
import {
  Project,
  ProjectDetail,
  Thread,
  Resource,
  Finding,
  listProjects,
  getProject,
  listFindings,
} from "@/lib/api";

type CommandMode = "all" | "projects" | "docs" | "findings" | "threads";

interface SlashCommand {
  name: string;
  mode: CommandMode;
  description: string;
}

const SLASH_COMMANDS: SlashCommand[] = [
  { name: "/projects", mode: "projects", description: "Search projects" },
  { name: "/docs", mode: "docs", description: "Search documents" },
  { name: "/findings", mode: "findings", description: "Search findings" },
  { name: "/threads", mode: "threads", description: "Search threads" },
];

function FolderIcon({ className }: { className?: string }) {
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
      <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
    </svg>
  );
}

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

function MessageIcon({ className }: { className?: string }) {
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
      <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" />
    </svg>
  );
}

function BookmarkIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="currentColor"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z" />
    </svg>
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

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState<CommandMode>("all");
  const router = useRouter();
  const pathname = usePathname();

  // Data state
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProject, setCurrentProject] = useState<ProjectDetail | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  // Extract current project ID from URL
  const currentProjectId = useMemo(() => {
    const match = pathname.match(/\/projects\/([^/]+)/);
    return match ? match[1] : null;
  }, [pathname]);

  // Keyboard shortcut to open
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  // Fetch data when opened
  useEffect(() => {
    if (!open) return;

    const fetchData = async () => {
      setIsLoading(true);
      try {
        const projectsData = await listProjects();
        setProjects(projectsData);

        // If we're in a project context, fetch that project's details
        if (currentProjectId) {
          const projectDetail = await getProject(currentProjectId);
          setCurrentProject(projectDetail);
          const findingsData = await listFindings(currentProjectId);
          setFindings(findingsData);
        } else {
          setCurrentProject(null);
          setFindings([]);
        }
      } catch (error) {
        console.error("Failed to fetch command palette data:", error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, [open, currentProjectId]);

  // Reset state when closed
  useEffect(() => {
    if (!open) {
      setSearch("");
      setMode("all");
    }
  }, [open]);

  // Parse slash commands from input
  useEffect(() => {
    const trimmed = search.trim().toLowerCase();
    if (trimmed.startsWith("/projects")) {
      setMode("projects");
    } else if (trimmed.startsWith("/docs")) {
      setMode("docs");
    } else if (trimmed.startsWith("/findings")) {
      setMode("findings");
    } else if (trimmed.startsWith("/threads")) {
      setMode("threads");
    } else if (!trimmed.startsWith("/")) {
      setMode("all");
    }
  }, [search]);

  // Get search query without slash command prefix
  const getSearchQuery = useCallback(() => {
    const trimmed = search.trim();
    for (const cmd of SLASH_COMMANDS) {
      if (trimmed.toLowerCase().startsWith(cmd.name)) {
        return trimmed.slice(cmd.name.length).trim();
      }
    }
    return trimmed;
  }, [search]);

  const searchQuery = getSearchQuery();

  // Filter helper
  const matchesSearch = (text: string) => {
    if (!searchQuery) return true;
    return text.toLowerCase().includes(searchQuery.toLowerCase());
  };

  // Navigation handlers
  const handleSelectProject = (project: Project) => {
    setOpen(false);
    router.push(`/projects/${project.id}`);
  };

  const handleSelectThread = (thread: Thread, projectId: string) => {
    setOpen(false);
    router.push(`/projects/${projectId}/threads/${thread.id}`);
  };

  const handleSelectResource = (resource: Resource, projectId: string) => {
    setOpen(false);
    router.push(`/projects/${projectId}`);
  };

  const handleSelectFinding = (finding: Finding) => {
    setOpen(false);
    router.push(`/projects/${finding.project_id}`);
  };

  const handleSelectSlashCommand = (cmd: SlashCommand) => {
    setSearch(cmd.name + " ");
  };

  // Filtered results
  const filteredProjects = useMemo(() => {
    if (mode !== "all" && mode !== "projects") return [];
    return projects.filter((p) => matchesSearch(p.name));
  }, [projects, mode, searchQuery]);

  const filteredThreads = useMemo(() => {
    if (mode !== "all" && mode !== "threads") return [];
    if (!currentProject) return [];
    return currentProject.threads.filter((t) => matchesSearch(t.title));
  }, [currentProject, mode, searchQuery]);

  const filteredResources = useMemo(() => {
    if (mode !== "all" && mode !== "docs") return [];
    if (!currentProject) return [];
    return currentProject.resources.filter(
      (r) =>
        r.status === "ready" &&
        (matchesSearch(r.filename || "") || matchesSearch(r.source))
    );
  }, [currentProject, mode, searchQuery]);

  const filteredFindings = useMemo(() => {
    if (mode !== "all" && mode !== "findings") return [];
    return findings.filter((f) => matchesSearch(f.content));
  }, [findings, mode, searchQuery]);

  // Show slash commands when typing "/"
  const showSlashCommands =
    search.startsWith("/") &&
    !SLASH_COMMANDS.some((cmd) =>
      search.toLowerCase().startsWith(cmd.name + " ")
    );

  const filteredSlashCommands = showSlashCommands
    ? SLASH_COMMANDS.filter((cmd) =>
        cmd.name.toLowerCase().startsWith(search.toLowerCase())
      )
    : [];

  const hasNoResults =
    !isLoading &&
    filteredProjects.length === 0 &&
    filteredThreads.length === 0 &&
    filteredResources.length === 0 &&
    filteredFindings.length === 0 &&
    filteredSlashCommands.length === 0;

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 max-w-xl w-full bg-popover rounded-lg border shadow-lg overflow-hidden z-50 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group]:not([hidden])_~[cmdk-group]]:pt-0 [&_[cmdk-item]]:px-3 [&_[cmdk-item]]:py-2.5 [&_[cmdk-item]]:rounded-sm [&_[cmdk-item][data-selected=true]]:bg-accent [&_[cmdk-item][data-selected=true]]:text-accent-foreground"
    >
      <div className="flex items-center border-b px-3">
        <SearchIcon className="mr-2 h-4 w-4 shrink-0 opacity-50" />
        <Command.Input
          autoFocus
          value={search}
          onValueChange={setSearch}
          placeholder={
            mode === "all"
              ? "Search or type / for commands..."
              : `Search ${mode}...`
          }
          className="flex h-11 w-full rounded-md bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
        />
        {mode !== "all" && (
          <span className="text-xs bg-muted px-2 py-1 rounded text-muted-foreground">
            {mode}
          </span>
        )}
      </div>
      <Command.List className="max-h-[400px] overflow-y-auto overflow-x-hidden p-1">
            {isLoading && (
              <Command.Loading>
                <div className="py-6 text-center text-sm text-muted-foreground">
                  Loading...
                </div>
              </Command.Loading>
            )}

            {hasNoResults && searchQuery && (
              <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
                No results found.
              </Command.Empty>
            )}

            {/* Slash commands */}
            {filteredSlashCommands.length > 0 && (
              <Command.Group heading="Commands">
                {filteredSlashCommands.map((cmd) => (
                  <Command.Item
                    key={cmd.name}
                    value={cmd.name}
                    onSelect={() => handleSelectSlashCommand(cmd)}
                    className="flex items-center cursor-pointer"
                  >
                    <span className="font-mono text-primary">{cmd.name}</span>
                    <span className="ml-2 text-muted-foreground">
                      {cmd.description}
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {/* Projects */}
            {filteredProjects.length > 0 && (
              <Command.Group heading="Projects">
                {filteredProjects.slice(0, 10).map((project) => (
                  <Command.Item
                    key={project.id}
                    value={`project-${project.id}-${project.name}`}
                    onSelect={() => handleSelectProject(project)}
                    className="flex items-center cursor-pointer"
                  >
                    <FolderIcon className="mr-2 h-4 w-4 shrink-0 text-primary" />
                    <span className="flex-1 truncate">{project.name}</span>
                    <span className="ml-2 text-xs text-muted-foreground shrink-0">
                      {project.resource_count} docs, {project.thread_count} threads
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {/* Threads (project-scoped) */}
            {filteredThreads.length > 0 && currentProject && (
              <Command.Group heading={`Threads in ${currentProject.name}`}>
                {filteredThreads.slice(0, 10).map((thread) => (
                  <Command.Item
                    key={thread.id}
                    value={`thread-${thread.id}-${thread.title}`}
                    onSelect={() =>
                      handleSelectThread(thread, currentProject.id)
                    }
                    className="flex items-center cursor-pointer"
                  >
                    <MessageIcon className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="flex-1 truncate">{thread.title}</span>
                    {thread.parent_thread_id && (
                      <span className="ml-2 text-xs text-muted-foreground shrink-0">
                        (subthread)
                      </span>
                    )}
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {/* Resources/Docs (project-scoped) */}
            {filteredResources.length > 0 && currentProject && (
              <Command.Group heading={`Docs in ${currentProject.name}`}>
                {filteredResources.slice(0, 10).map((resource) => (
                  <Command.Item
                    key={resource.id}
                    value={`resource-${resource.id}-${resource.filename || resource.source}`}
                    onSelect={() =>
                      handleSelectResource(resource, currentProject.id)
                    }
                    className="flex items-center cursor-pointer"
                  >
                    <FileIcon className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="flex-1 truncate">
                      {resource.filename || resource.source}
                    </span>
                    <span className="ml-2 text-xs text-muted-foreground shrink-0 capitalize">
                      {resource.type}
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {/* Findings (project-scoped) */}
            {filteredFindings.length > 0 && (
              <Command.Group heading="Findings">
                {filteredFindings.slice(0, 10).map((finding) => (
                  <Command.Item
                    key={finding.id}
                    value={`finding-${finding.id}-${finding.content}`}
                    onSelect={() => handleSelectFinding(finding)}
                    className="flex items-center cursor-pointer"
                  >
                    <BookmarkIcon className="mr-2 h-4 w-4 shrink-0 text-amber-500" />
                    <span className="flex-1 truncate">
                      {finding.content}
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {/* Empty state hints */}
            {!isLoading && !searchQuery && !showSlashCommands && (
              <div className="py-6 px-4 text-center text-sm text-muted-foreground">
                <p className="mb-2">
                  Type to search or use slash commands:
                </p>
                <div className="flex flex-wrap justify-center gap-2">
                  {SLASH_COMMANDS.map((cmd) => (
                    <button
                      key={cmd.name}
                      onClick={() => handleSelectSlashCommand(cmd)}
                      className="font-mono text-xs bg-muted px-2 py-1 rounded hover:bg-accent transition-colors"
                    >
                      {cmd.name}
                    </button>
                  ))}
                </div>
                {!currentProject && (
                  <p className="mt-3 text-xs">
                    Open a project to search threads, docs, and findings
                  </p>
                )}
              </div>
            )}
          </Command.List>
      <div className="flex items-center justify-between border-t px-3 py-2 text-xs text-muted-foreground">
        <div className="flex items-center gap-4">
          <span>
            <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium">
              <span className="text-xs">ESC</span>
            </kbd>{" "}
            to close
          </span>
        </div>
        <span>
          <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium">
            <span className="text-xs">CMD</span>
            <span className="text-xs">K</span>
          </kbd>{" "}
          to toggle
        </span>
      </div>
    </Command.Dialog>
  );
}
