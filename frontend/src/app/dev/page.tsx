"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuth } from "@/contexts/auth-context";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Project {
  id: string;
  name: string;
}

interface TestResult {
  success: boolean;
  durationMs: number;
  formattedContent: string;
  rawResponse: unknown;
  error?: string;
}

interface DevResource {
  id: string;
  filename: string;
  type: string;
  source: string;
  status: string;
  summary?: string;
  error_message?: string;
  chunk_count?: number;
  indexed_at?: string;
  indexing_duration_ms?: number;
  file_size_bytes?: number;
}

type AddResourceMode = "file" | "url" | "git" | "text";

const TERMINAL_STATES = ["indexed", "analyzed", "described", "ready", "failed", "partial"];
const TEST_RUN_TERMINAL_STATES = ["success", "failed", "partial"];

// Test Suite interfaces
interface TestResource {
  id: string;
  name: string;
  description?: string;
  type: string;
  filename?: string;
  storage_path: string;
  file_size_bytes?: number;
  content_hash?: string;
  created_at: string;
  source_url?: string;
  git_branch?: string;
  last_run?: TestRun;
}

interface TestRun {
  id: string;
  test_resource_id: string;
  started_at: string;
  completed_at?: string;
  status: string;
  error_message?: string;
  extraction_duration_ms?: number;
  indexing_duration_ms?: number;
  total_duration_ms?: number;
  chunk_count?: number;
  summary?: string;
  raw_metadata?: Record<string, unknown>;
}

// Tool testing functions
async function testSearchDocuments(
  projectId: string,
  query: string
): Promise<TestResult> {
  const start = performance.now();
  try {
    const res = await fetch(`${API_BASE}/projects/${projectId}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ query, top_k: 10 }),
    });

    const durationMs = Math.round(performance.now() - start);

    if (!res.ok) {
      return {
        success: false,
        durationMs,
        formattedContent: `Error: ${res.status} ${res.statusText}`,
        rawResponse: null,
        error: `HTTP ${res.status}`,
      };
    }

    const data = await res.json();
    const results = data.results || [];

    let formattedContent: string;
    if (results.length === 0) {
      formattedContent = `No results found for "${query}"`;
    } else {
      const formatted = results
        .map(
          (r: { source: string; snippet: string; score: number }, i: number) =>
            `[${i + 1}] ${r.source}\n${r.snippet}\n(Score: ${(r.score * 100).toFixed(0)}%)`
        )
        .join("\n\n");
      formattedContent = `Found ${results.length} results for "${query}":\n\n${formatted}`;
    }

    return {
      success: true,
      durationMs,
      formattedContent,
      rawResponse: data,
    };
  } catch (error) {
    return {
      success: false,
      durationMs: Math.round(performance.now() - start),
      formattedContent: `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
      rawResponse: null,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
}

async function testSearchWeb(query: string): Promise<TestResult> {
  const start = performance.now();
  try {
    const res = await fetch("/api/dev/search-web", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ query }),
    });

    const durationMs = Math.round(performance.now() - start);

    if (!res.ok) {
      return {
        success: false,
        durationMs,
        formattedContent: `Error: ${res.status} ${res.statusText}`,
        rawResponse: null,
        error: `HTTP ${res.status}`,
      };
    }

    const data = await res.json();
    return {
      success: data.success,
      durationMs,
      formattedContent: data.formattedContent,
      rawResponse: data.rawResponse,
      error: data.error,
    };
  } catch (error) {
    return {
      success: false,
      durationMs: Math.round(performance.now() - start),
      formattedContent: `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
      rawResponse: null,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
}

async function testListResources(
  projectId: string,
  typeFilter?: string
): Promise<TestResult> {
  const start = performance.now();
  try {
    const res = await fetch(`${API_BASE}/projects/${projectId}/resources`, {
      credentials: "include",
    });

    const durationMs = Math.round(performance.now() - start);

    if (!res.ok) {
      return {
        success: false,
        durationMs,
        formattedContent: `Error: ${res.status} ${res.statusText}`,
        rawResponse: null,
        error: `HTTP ${res.status}`,
      };
    }

    const resources = await res.json();
    const filtered = typeFilter
      ? resources.filter((r: { type: string }) => r.type === typeFilter)
      : resources;

    let formattedContent: string;
    if (filtered.length === 0) {
      formattedContent = "No resources found.";
    } else {
      const formatted = filtered
        .map(
          (r: { filename: string; type: string; status: string }) =>
            `- ${r.filename} (${r.type}, ${r.status})`
        )
        .join("\n");
      formattedContent = `Found ${filtered.length} resources:\n${formatted}`;
    }

    return {
      success: true,
      durationMs,
      formattedContent,
      rawResponse: resources,
    };
  } catch (error) {
    return {
      success: false,
      durationMs: Math.round(performance.now() - start),
      formattedContent: `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
      rawResponse: null,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
}

async function testGetResourceInfo(
  projectId: string,
  resourceName: string
): Promise<TestResult> {
  const start = performance.now();
  try {
    const res = await fetch(`${API_BASE}/projects/${projectId}/resources`, {
      credentials: "include",
    });

    const durationMs = Math.round(performance.now() - start);

    if (!res.ok) {
      return {
        success: false,
        durationMs,
        formattedContent: `Error: ${res.status} ${res.statusText}`,
        rawResponse: null,
        error: `HTTP ${res.status}`,
      };
    }

    const resources = await res.json();
    const resource = resources.find(
      (r: { filename: string }) =>
        r.filename.toLowerCase() === resourceName.toLowerCase()
    );

    if (!resource) {
      return {
        success: false,
        durationMs,
        formattedContent: `Resource "${resourceName}" not found. Use list_resources to see available files.`,
        rawResponse: { searched: resourceName, available: resources.map((r: { filename: string }) => r.filename) },
      };
    }

    let info = `**${resource.filename}**\n`;
    info += `- Type: ${resource.type}\n`;
    info += `- Status: ${resource.status}\n`;
    if (resource.summary) {
      info += `\n**Summary:**\n${resource.summary}\n`;
    }
    if (resource.type === "document") {
      info += `\n*To search within this document, use search_documents with relevant keywords.*`;
    }

    return {
      success: true,
      durationMs,
      formattedContent: info,
      rawResponse: resource,
    };
  } catch (error) {
    return {
      success: false,
      durationMs: Math.round(performance.now() - start),
      formattedContent: `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
      rawResponse: null,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
}

// Status indicator component
function StatusBadge({ status }: { status: string }) {
  const isProcessing = !TERMINAL_STATES.includes(status);
  const isSuccess = ["indexed", "analyzed", "described", "ready"].includes(status);
  const isError = ["failed", "partial"].includes(status);

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${
        isSuccess
          ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
          : isError
          ? "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
          : "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
      }`}
    >
      {isProcessing && (
        <span className="inline-block w-2 h-2 rounded-full bg-current animate-pulse" />
      )}
      {status}
    </span>
  );
}

export default function DevPage() {
  const { isAuthenticated, loading } = useAuth();

  // Main page tab
  const [mainTab, setMainTab] = useState<"tools" | "rag" | "test-suite">("tools");

  // Tool Testing state
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [activeToolTab, setActiveToolTab] = useState("search_documents");
  const [isExecuting, setIsExecuting] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [showRawJson, setShowRawJson] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [webQuery, setWebQuery] = useState("");
  const [resourceTypeFilter, setResourceTypeFilter] = useState<string>("all");
  const [resourceName, setResourceName] = useState("");

  // RAG Pipeline state
  const [testProjectId, setTestProjectId] = useState<string | null>(null);
  const [testProjectLoading, setTestProjectLoading] = useState(true);
  const [addMode, setAddMode] = useState<AddResourceMode>("file");
  const [resources, setResources] = useState<DevResource[]>([]);
  const [isAdding, setIsAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [ragQuery, setRagQuery] = useState("");
  const [ragResult, setRagResult] = useState<TestResult | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [showRagRawJson, setShowRagRawJson] = useState(false);
  const [isClearingAll, setIsClearingAll] = useState(false);

  // Add resource form state
  const [urlInput, setUrlInput] = useState("");
  const [gitUrl, setGitUrl] = useState("");
  const [gitBranch, setGitBranch] = useState("");
  const [textTitle, setTextTitle] = useState("");
  const [textContent, setTextContent] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [expandedResourceId, setExpandedResourceId] = useState<string | null>(null);
  const [resourceChunks, setResourceChunks] = useState<Record<string, unknown[] | null>>({});
  const [loadingChunks, setLoadingChunks] = useState<string | null>(null);

  // Test Suite state
  const [testResources, setTestResources] = useState<TestResource[]>([]);
  const [testResourcesLoading, setTestResourcesLoading] = useState(true);
  const [selectedTestResourceId, setSelectedTestResourceId] = useState<string | null>(null);
  const [selectedTestRun, setSelectedTestRun] = useState<TestRun | null>(null);
  const [testRuns, setTestRuns] = useState<TestRun[]>([]);
  const [testRunsLoading, setTestRunsLoading] = useState(false);
  const [isAddingTestResource, setIsAddingTestResource] = useState(false);
  const [isRunningTest, setIsRunningTest] = useState(false);
  const [isRunningAll, setIsRunningAll] = useState(false);
  const [testAddError, setTestAddError] = useState<string | null>(null);
  const [testResourceName, setTestResourceName] = useState("");
  const [testResourceDescription, setTestResourceDescription] = useState("");
  const [testResourceUrl, setTestResourceUrl] = useState("");
  const [testResourceGitBranch, setTestResourceGitBranch] = useState("");
  const [testAddMode, setTestAddMode] = useState<"file" | "url" | "git">("file");
  const testFileInputRef = useRef<HTMLInputElement>(null);

  // Test Query state
  const [testQuery, setTestQuery] = useState("");
  const [testQueryResult, setTestQueryResult] = useState<{
    answer: string;
    sources: Array<{ content: string; source: string; score: number }>;
    namespace: string;
  } | null>(null);
  const [isQuerying, setIsQuerying] = useState(false);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [testSystemPrompt, setTestSystemPrompt] = useState("");
  const [showSystemPrompt, setShowSystemPrompt] = useState(false);

  // Chunks viewer state
  const [testRunChunks, setTestRunChunks] = useState<Array<{
    id: string;
    content: string;
    source: string;
    metadata: Record<string, unknown>;
  }> | null>(null);
  const [isLoadingChunks, setIsLoadingChunks] = useState(false);
  const [showChunks, setShowChunks] = useState(false);

  // Fetch projects on mount
  useEffect(() => {
    async function fetchProjects() {
      try {
        const res = await fetch(`${API_BASE}/projects`, {
          credentials: "include",
        });
        if (res.ok) {
          const data = await res.json();
          setProjects(data);
          if (data.length > 0) {
            setSelectedProjectId(data[0].id);
          }
        }
      } catch (err) {
        console.error("Failed to fetch projects:", err);
      }
    }
    if (isAuthenticated) {
      fetchProjects();
    }
  }, [isAuthenticated]);

  // Find or create test project
  useEffect(() => {
    async function findOrCreateTestProject() {
      if (!isAuthenticated) return;

      setTestProjectLoading(true);
      try {
        const res = await fetch(`${API_BASE}/projects`, {
          credentials: "include",
        });
        if (!res.ok) throw new Error("Failed to fetch projects");

        const allProjects: Project[] = await res.json();
        const existing = allProjects.find(p => p.name === "Dev Testing");

        if (existing) {
          setTestProjectId(existing.id);
        } else {
          // Create the test project
          const createRes = await fetch(`${API_BASE}/projects`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ name: "Dev Testing" }),
          });
          if (!createRes.ok) throw new Error("Failed to create test project");
          const newProject = await createRes.json();
          setTestProjectId(newProject.id);
        }
      } catch (err) {
        console.error("Failed to find/create test project:", err);
      } finally {
        setTestProjectLoading(false);
      }
    }
    findOrCreateTestProject();
  }, [isAuthenticated]);

  // Fetch resources for test project
  const fetchResources = useCallback(async () => {
    if (!testProjectId) return;
    try {
      const res = await fetch(`${API_BASE}/projects/${testProjectId}/resources`, {
        credentials: "include",
      });
      if (res.ok) {
        const data = await res.json();
        setResources(data);
      }
    } catch (err) {
      console.error("Failed to fetch resources:", err);
    }
  }, [testProjectId]);

  useEffect(() => {
    if (testProjectId) {
      fetchResources();
    }
  }, [testProjectId, fetchResources]);

  // Poll for resource status updates
  useEffect(() => {
    const hasProcessing = resources.some(r => !TERMINAL_STATES.includes(r.status));
    if (hasProcessing && testProjectId) {
      const interval = setInterval(fetchResources, 3000);
      return () => clearInterval(interval);
    }
  }, [resources, testProjectId, fetchResources]);

  const handleExecute = async () => {
    setIsExecuting(true);
    setResult(null);

    let testResult: TestResult;

    switch (activeToolTab) {
      case "search_documents":
        testResult = await testSearchDocuments(selectedProjectId, searchQuery);
        break;
      case "search_web":
        testResult = await testSearchWeb(webQuery);
        break;
      case "list_resources":
        testResult = await testListResources(
          selectedProjectId,
          resourceTypeFilter && resourceTypeFilter !== "all" ? resourceTypeFilter : undefined
        );
        break;
      case "get_resource_info":
        testResult = await testGetResourceInfo(selectedProjectId, resourceName);
        break;
      default:
        testResult = {
          success: false,
          durationMs: 0,
          formattedContent: "Unknown tool",
          rawResponse: null,
        };
    }

    setResult(testResult);
    setIsExecuting(false);
  };

  // Add resource handlers
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !testProjectId) return;

    setIsAdding(true);
    setAddError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`${API_BASE}/projects/${testProjectId}/resources`, {
        method: "POST",
        credentials: "include",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err || `HTTP ${res.status}`);
      }

      await fetchResources();
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsAdding(false);
    }
  };

  const handleAddUrl = async () => {
    if (!urlInput.trim() || !testProjectId) return;

    setIsAdding(true);
    setAddError(null);
    try {
      const res = await fetch(`${API_BASE}/projects/${testProjectId}/resources/url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ url: urlInput.trim() }),
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err || `HTTP ${res.status}`);
      }

      await fetchResources();
      setUrlInput("");
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to add URL");
    } finally {
      setIsAdding(false);
    }
  };

  const handleAddGit = async () => {
    if (!gitUrl.trim() || !testProjectId) return;

    setIsAdding(true);
    setAddError(null);
    try {
      const res = await fetch(`${API_BASE}/projects/${testProjectId}/resources/git`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          url: gitUrl.trim(),
          branch: gitBranch.trim() || undefined,
        }),
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err || `HTTP ${res.status}`);
      }

      await fetchResources();
      setGitUrl("");
      setGitBranch("");
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to add git repo");
    } finally {
      setIsAdding(false);
    }
  };

  const handleAddText = async () => {
    if (!textTitle.trim() || !textContent.trim() || !testProjectId) return;

    setIsAdding(true);
    setAddError(null);
    try {
      const res = await fetch(`${API_BASE}/projects/${testProjectId}/resources/text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          title: textTitle.trim(),
          content: textContent.trim(),
        }),
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err || `HTTP ${res.status}`);
      }

      await fetchResources();
      setTextTitle("");
      setTextContent("");
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to add text");
    } finally {
      setIsAdding(false);
    }
  };

  const handleDeleteResource = async (resourceId: string) => {
    if (!testProjectId) return;
    try {
      const res = await fetch(`${API_BASE}/projects/${testProjectId}/resources/${resourceId}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (res.ok) {
        await fetchResources();
      }
    } catch (err) {
      console.error("Failed to delete resource:", err);
    }
  };

  const handleClearAll = async () => {
    if (!testProjectId || resources.length === 0) return;
    if (!confirm("Delete all test resources? This cannot be undone.")) return;

    setIsClearingAll(true);
    try {
      const res = await fetch("/api/dev/clear-resources", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ projectId: testProjectId }),
      });
      if (res.ok) {
        await fetchResources();
      }
    } catch (err) {
      console.error("Failed to clear resources:", err);
    } finally {
      setIsClearingAll(false);
    }
  };

  const handleRagSearch = async () => {
    if (!ragQuery.trim() || !testProjectId) return;

    setIsSearching(true);
    setRagResult(null);
    const searchResult = await testSearchDocuments(testProjectId, ragQuery);
    setRagResult(searchResult);
    setIsSearching(false);
  };

  const handleViewChunks = async (resourceId: string) => {
    if (resourceChunks[resourceId] !== undefined) {
      // Already loaded, just toggle
      setResourceChunks(prev => ({ ...prev, [resourceId]: prev[resourceId] ? null : prev[resourceId] }));
      return;
    }

    setLoadingChunks(resourceId);
    try {
      const res = await fetch(`${API_BASE}/resources/${resourceId}/chunks`, {
        credentials: "include",
      });
      if (res.ok) {
        const data = await res.json();
        setResourceChunks(prev => ({ ...prev, [resourceId]: data }));
      } else {
        setResourceChunks(prev => ({ ...prev, [resourceId]: [] }));
      }
    } catch (err) {
      console.error("Failed to fetch chunks:", err);
      setResourceChunks(prev => ({ ...prev, [resourceId]: [] }));
    } finally {
      setLoadingChunks(null);
    }
  };

  // ===== Test Suite Handlers =====

  // Fetch test resources
  const fetchTestResources = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/test-resources`, {
        credentials: "include",
      });
      if (res.ok) {
        const data = await res.json();
        setTestResources(data);
      }
    } catch (err) {
      console.error("Failed to fetch test resources:", err);
    } finally {
      setTestResourcesLoading(false);
    }
  }, []);

  // Fetch runs for selected test resource
  const fetchTestRuns = useCallback(async (resourceId: string) => {
    setTestRunsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/test-resources/${resourceId}/runs`, {
        credentials: "include",
      });
      if (res.ok) {
        const data = await res.json();
        setTestRuns(data);
      }
    } catch (err) {
      console.error("Failed to fetch test runs:", err);
    } finally {
      setTestRunsLoading(false);
    }
  }, []);

  // Load test resources on mount
  useEffect(() => {
    if (isAuthenticated && mainTab === "test-suite") {
      fetchTestResources();
    }
  }, [isAuthenticated, mainTab, fetchTestResources]);

  // Load runs when resource selected
  useEffect(() => {
    if (selectedTestResourceId) {
      fetchTestRuns(selectedTestResourceId);
      setSelectedTestRun(null);
    } else {
      setTestRuns([]);
      setSelectedTestRun(null);
    }
  }, [selectedTestResourceId, fetchTestRuns]);

  // Poll for in-progress test runs
  useEffect(() => {
    const hasProcessing = testRuns.some(r => !TEST_RUN_TERMINAL_STATES.includes(r.status));
    if (hasProcessing && selectedTestResourceId) {
      const interval = setInterval(() => {
        fetchTestRuns(selectedTestResourceId);
        fetchTestResources(); // Also refresh resources to update last_run
      }, 3000);
      return () => clearInterval(interval);
    }
  }, [testRuns, selectedTestResourceId, fetchTestRuns, fetchTestResources]);

  const handleAddTestResourceFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsAddingTestResource(true);
    setTestAddError(null);
    try {
      const formData = new FormData();
      formData.append("name", testResourceName || file.name);
      formData.append("description", testResourceDescription);
      formData.append("file", file);

      const res = await fetch(`${API_BASE}/test-resources`, {
        method: "POST",
        credentials: "include",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err || `HTTP ${res.status}`);
      }

      await fetchTestResources();
      setTestResourceName("");
      setTestResourceDescription("");
      if (testFileInputRef.current) testFileInputRef.current.value = "";
    } catch (err) {
      setTestAddError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsAddingTestResource(false);
    }
  };

  const handleAddTestResourceUrl = async () => {
    if (!testResourceUrl.trim()) return;

    setIsAddingTestResource(true);
    setTestAddError(null);
    try {
      const res = await fetch(`${API_BASE}/test-resources/url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          name: testResourceName || testResourceUrl,
          description: testResourceDescription,
          url: testResourceUrl.trim(),
        }),
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err || `HTTP ${res.status}`);
      }

      await fetchTestResources();
      setTestResourceName("");
      setTestResourceDescription("");
      setTestResourceUrl("");
    } catch (err) {
      setTestAddError(err instanceof Error ? err.message : "Failed to add URL");
    } finally {
      setIsAddingTestResource(false);
    }
  };

  const handleAddTestResourceGit = async () => {
    if (!testResourceUrl.trim()) return;

    setIsAddingTestResource(true);
    setTestAddError(null);
    try {
      const res = await fetch(`${API_BASE}/test-resources/git`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          name: testResourceName || testResourceUrl,
          description: testResourceDescription,
          url: testResourceUrl.trim(),
          branch: testResourceGitBranch.trim() || undefined,
        }),
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err || `HTTP ${res.status}`);
      }

      await fetchTestResources();
      setTestResourceName("");
      setTestResourceDescription("");
      setTestResourceUrl("");
      setTestResourceGitBranch("");
    } catch (err) {
      setTestAddError(err instanceof Error ? err.message : "Failed to add git repo");
    } finally {
      setIsAddingTestResource(false);
    }
  };

  const handleDeleteTestResource = async (resourceId: string) => {
    if (!confirm("Delete this test resource and all its runs?")) return;
    try {
      const res = await fetch(`${API_BASE}/test-resources/${resourceId}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (res.ok) {
        if (selectedTestResourceId === resourceId) {
          setSelectedTestResourceId(null);
        }
        await fetchTestResources();
      }
    } catch (err) {
      console.error("Failed to delete test resource:", err);
    }
  };

  const handleRunTest = async (resourceId: string) => {
    setIsRunningTest(true);
    try {
      const res = await fetch(`${API_BASE}/test-resources/${resourceId}/run`, {
        method: "POST",
        credentials: "include",
      });
      if (res.ok) {
        // Select this resource to show the new run
        setSelectedTestResourceId(resourceId);
        await fetchTestRuns(resourceId);
        await fetchTestResources();
      }
    } catch (err) {
      console.error("Failed to run test:", err);
    } finally {
      setIsRunningTest(false);
    }
  };

  const handleRunAllTests = async () => {
    if (!confirm("Run tests for all resources? This may take a while.")) return;
    setIsRunningAll(true);
    try {
      const res = await fetch(`${API_BASE}/test-resources/run-all`, {
        method: "POST",
        credentials: "include",
      });
      if (res.ok) {
        await fetchTestResources();
        // If a resource is selected, refresh its runs
        if (selectedTestResourceId) {
          await fetchTestRuns(selectedTestResourceId);
        }
      }
    } catch (err) {
      console.error("Failed to run all tests:", err);
    } finally {
      setIsRunningAll(false);
    }
  };

  const handleTestQuery = async () => {
    if (!testQuery.trim() || !selectedTestRun) return;

    setIsQuerying(true);
    setQueryError(null);
    setTestQueryResult(null);

    try {
      const res = await fetch(`${API_BASE}/test-resources/runs/${selectedTestRun.id}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          question: testQuery,
          top_k: 5,
          system_prompt: testSystemPrompt.trim() || null
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      setTestQueryResult(data);
    } catch (err) {
      setQueryError(err instanceof Error ? err.message : "Query failed");
    } finally {
      setIsQuerying(false);
    }
  };

  // Clear query and chunks when selecting different run
  useEffect(() => {
    setTestQuery("");
    setTestQueryResult(null);
    setQueryError(null);
    setTestRunChunks(null);
    setShowChunks(false);
  }, [selectedTestRun?.id]);

  const handleLoadChunks = async () => {
    if (!selectedTestRun) return;

    setIsLoadingChunks(true);
    try {
      const res = await fetch(`${API_BASE}/test-resources/runs/${selectedTestRun.id}/chunks`, {
        credentials: "include",
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      setTestRunChunks(data.chunks);
      setShowChunks(true);
    } catch (err) {
      console.error("Failed to load chunks:", err);
    } finally {
      setIsLoadingChunks(false);
    }
  };

  // Get selected test resource
  const selectedTestResource = testResources.find(r => r.id === selectedTestResourceId);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="flex items-center justify-center h-screen">
        <p className="text-red-500">Not authenticated. Please log in first.</p>
      </div>
    );
  }

  return (
    <div className={`mx-auto p-6 ${mainTab === "test-suite" ? "w-full" : "container max-w-5xl"}`}>
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Dev Tools</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Test and debug RAG pipeline components
        </p>
      </div>

      {/* Main Tabs */}
      <Tabs value={mainTab} onValueChange={(v) => setMainTab(v as "tools" | "rag" | "test-suite")} className="space-y-6">
        <TabsList className="grid w-full grid-cols-3 max-w-lg">
          <TabsTrigger value="tools">Tool Testing</TabsTrigger>
          <TabsTrigger value="rag">RAG Pipeline</TabsTrigger>
          <TabsTrigger value="test-suite">Test Suite</TabsTrigger>
        </TabsList>

        {/* Tool Testing Tab */}
        <TabsContent value="tools" className="space-y-6">
          {/* Project selector */}
          <div className="flex items-center gap-2">
            <Label htmlFor="project" className="text-sm text-muted-foreground">
              Project:
            </Label>
            <Select value={selectedProjectId} onValueChange={setSelectedProjectId}>
              <SelectTrigger className="w-[280px]">
                <SelectValue placeholder="Select project" />
              </SelectTrigger>
              <SelectContent>
                {projects.map((project) => (
                  <SelectItem key={project.id} value={project.id}>
                    {project.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Tool Tabs */}
          <Tabs value={activeToolTab} onValueChange={setActiveToolTab} className="space-y-4">
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="search_documents">search_documents</TabsTrigger>
              <TabsTrigger value="search_web">search_web</TabsTrigger>
              <TabsTrigger value="list_resources">list_resources</TabsTrigger>
              <TabsTrigger value="get_resource_info">get_resource_info</TabsTrigger>
            </TabsList>

            <TabsContent value="search_documents" className="space-y-4">
              <div className="flex gap-2">
                <Input
                  placeholder="Enter search query..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleExecute()}
                  className="flex-1"
                />
                <Button onClick={handleExecute} disabled={isExecuting || !searchQuery}>
                  {isExecuting ? "Executing..." : "Execute"}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Calls POST /projects/{"{projectId}"}/search with top_k=10
              </p>
            </TabsContent>

            <TabsContent value="search_web" className="space-y-4">
              <div className="flex gap-2">
                <Input
                  placeholder="Enter web search query..."
                  value={webQuery}
                  onChange={(e) => setWebQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleExecute()}
                  className="flex-1"
                />
                <Button onClick={handleExecute} disabled={isExecuting || !webQuery}>
                  {isExecuting ? "Executing..." : "Execute"}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Calls Tavily API with search_depth=basic, max_results=5
              </p>
            </TabsContent>

            <TabsContent value="list_resources" className="space-y-4">
              <div className="flex gap-2">
                <Select value={resourceTypeFilter} onValueChange={setResourceTypeFilter}>
                  <SelectTrigger className="w-[200px]">
                    <SelectValue placeholder="All types" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All types</SelectItem>
                    <SelectItem value="document">document</SelectItem>
                    <SelectItem value="data_file">data_file</SelectItem>
                    <SelectItem value="image">image</SelectItem>
                    <SelectItem value="website">website</SelectItem>
                    <SelectItem value="git_repository">git_repository</SelectItem>
                  </SelectContent>
                </Select>
                <Button onClick={handleExecute} disabled={isExecuting} className="flex-1">
                  {isExecuting ? "Executing..." : "Execute"}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Calls GET /projects/{"{projectId}"}/resources
              </p>
            </TabsContent>

            <TabsContent value="get_resource_info" className="space-y-4">
              <div className="flex gap-2">
                <Input
                  placeholder="Enter resource filename..."
                  value={resourceName}
                  onChange={(e) => setResourceName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleExecute()}
                  className="flex-1"
                />
                <Button onClick={handleExecute} disabled={isExecuting || !resourceName}>
                  {isExecuting ? "Executing..." : "Execute"}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Fetches resources and finds by filename (case-insensitive)
              </p>
            </TabsContent>
          </Tabs>

          {/* Results */}
          {result && (
            <div className="mt-6 space-y-4">
              <div className="flex items-center gap-2">
                <span
                  className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    result.success
                      ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                      : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
                  }`}
                >
                  {result.success ? "Success" : "Error"}
                </span>
                <span className="text-sm text-muted-foreground">
                  {result.durationMs}ms
                </span>
              </div>

              <div>
                <h3 className="text-sm font-medium mb-2">Formatted Result</h3>
                <pre className="bg-muted p-4 rounded-lg text-sm whitespace-pre-wrap overflow-x-auto max-h-[300px] overflow-y-auto">
                  {result.formattedContent}
                </pre>
              </div>

              <div>
                <button
                  onClick={() => setShowRawJson(!showRawJson)}
                  className="text-sm font-medium flex items-center gap-1 hover:underline"
                >
                  <span>{showRawJson ? "▼" : "▶"}</span>
                  Raw JSON Response
                </button>
                {showRawJson && (
                  <pre className="bg-muted p-4 rounded-lg text-xs mt-2 overflow-x-auto max-h-[400px] overflow-y-auto">
                    {JSON.stringify(result.rawResponse, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          )}
        </TabsContent>

        {/* RAG Pipeline Tab */}
        <TabsContent value="rag" className="space-y-6">
          {testProjectLoading ? (
            <div className="text-center py-8 text-muted-foreground">
              Setting up test project...
            </div>
          ) : (
            <>
              {/* Add Resources Section */}
              <div className="border rounded-lg p-4 space-y-4">
                <h2 className="font-semibold">Add Resources</h2>

                {/* Mode buttons */}
                <div className="flex gap-2">
                  {(["file", "url", "git", "text"] as AddResourceMode[]).map((mode) => (
                    <Button
                      key={mode}
                      variant={addMode === mode ? "default" : "outline"}
                      size="sm"
                      onClick={() => setAddMode(mode)}
                    >
                      {mode === "file" ? "Upload File" :
                       mode === "url" ? "Add URL" :
                       mode === "git" ? "Add Git Repo" : "Paste Text"}
                    </Button>
                  ))}
                </div>

                {/* Dynamic input area */}
                <div className="space-y-3">
                  {addMode === "file" && (
                    <div>
                      <Input
                        ref={fileInputRef}
                        type="file"
                        onChange={handleFileUpload}
                        disabled={isAdding}
                        className="cursor-pointer"
                      />
                      <p className="text-xs text-muted-foreground mt-1">
                        Supports PDF, DOCX, TXT, MD, CSV, Excel, JSON, images
                      </p>
                    </div>
                  )}

                  {addMode === "url" && (
                    <div className="flex gap-2">
                      <Input
                        placeholder="https://example.com/page"
                        value={urlInput}
                        onChange={(e) => setUrlInput(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleAddUrl()}
                        className="flex-1"
                      />
                      <Button onClick={handleAddUrl} disabled={isAdding || !urlInput.trim()}>
                        {isAdding ? "Adding..." : "Add"}
                      </Button>
                    </div>
                  )}

                  {addMode === "git" && (
                    <div className="space-y-2">
                      <div className="flex gap-2">
                        <Input
                          placeholder="https://github.com/user/repo"
                          value={gitUrl}
                          onChange={(e) => setGitUrl(e.target.value)}
                          className="flex-1"
                        />
                        <Input
                          placeholder="Branch (optional)"
                          value={gitBranch}
                          onChange={(e) => setGitBranch(e.target.value)}
                          className="w-40"
                        />
                        <Button onClick={handleAddGit} disabled={isAdding || !gitUrl.trim()}>
                          {isAdding ? "Adding..." : "Add"}
                        </Button>
                      </div>
                    </div>
                  )}

                  {addMode === "text" && (
                    <div className="space-y-2">
                      <Input
                        placeholder="Title"
                        value={textTitle}
                        onChange={(e) => setTextTitle(e.target.value)}
                      />
                      <Textarea
                        placeholder="Paste your text content here..."
                        value={textContent}
                        onChange={(e) => setTextContent(e.target.value)}
                        rows={4}
                      />
                      <Button
                        onClick={handleAddText}
                        disabled={isAdding || !textTitle.trim() || !textContent.trim()}
                      >
                        {isAdding ? "Adding..." : "Add Text"}
                      </Button>
                    </div>
                  )}

                  {addError && (
                    <p className="text-sm text-red-500">{addError}</p>
                  )}
                </div>
              </div>

              {/* Resources List */}
              <div className="border rounded-lg p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="font-semibold">
                    Resources ({resources.length})
                  </h2>
                  <div className="flex items-center gap-2">
                    {resources.some(r => !TERMINAL_STATES.includes(r.status)) && (
                      <span className="text-xs text-muted-foreground">
                        Auto-refreshing...
                      </span>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleClearAll}
                      disabled={isClearingAll || resources.length === 0}
                    >
                      {isClearingAll ? "Clearing..." : "Clear All"}
                    </Button>
                  </div>
                </div>

                {resources.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    No resources yet. Add some above to test the RAG pipeline.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {resources.map((resource) => {
                      const isExpanded = expandedResourceId === resource.id;
                      return (
                        <div
                          key={resource.id}
                          className="border rounded p-3 space-y-2"
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="font-medium truncate" title={resource.filename}>
                                  {resource.filename}
                                </span>
                                <span className="text-xs text-muted-foreground px-1.5 py-0.5 bg-muted rounded">
                                  {resource.type}
                                </span>
                                <StatusBadge status={resource.status} />
                              </div>
                              {resource.summary && (
                                <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                                  {resource.summary}
                                </p>
                              )}
                              {resource.error_message && (
                                <p className="text-sm text-red-500 mt-1">
                                  {resource.error_message}
                                </p>
                              )}
                              <div className="flex gap-3 text-xs text-muted-foreground mt-1">
                                {resource.chunk_count !== undefined && resource.chunk_count > 0 && (
                                  <span>Chunks: {resource.chunk_count}</span>
                                )}
                                {resource.indexing_duration_ms !== undefined && (
                                  <span>Indexed in: {(resource.indexing_duration_ms / 1000).toFixed(1)}s</span>
                                )}
                                {resource.file_size_bytes !== undefined && (
                                  <span>Size: {(resource.file_size_bytes / 1024).toFixed(0)}KB</span>
                                )}
                              </div>
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setExpandedResourceId(isExpanded ? null : resource.id)}
                              >
                                {isExpanded ? "Hide" : "Details"}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleDeleteResource(resource.id)}
                                className="text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
                              >
                                Delete
                              </Button>
                            </div>
                          </div>
                          {isExpanded && (
                            <div className="mt-3 pt-3 border-t space-y-4">
                              <div>
                                <h4 className="text-xs font-medium text-muted-foreground mb-2">
                                  Full Metadata
                                </h4>
                                <pre className="bg-muted p-3 rounded text-xs overflow-x-auto max-h-[300px] overflow-y-auto">
                                  {JSON.stringify(resource, null, 2)}
                                </pre>
                              </div>

                              <div>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => handleViewChunks(resource.id)}
                                  disabled={loadingChunks === resource.id}
                                >
                                  {loadingChunks === resource.id
                                    ? "Loading..."
                                    : resourceChunks[resource.id]
                                    ? "Hide Chunks"
                                    : "View Chunks"}
                                </Button>

                                {resourceChunks[resource.id] && (
                                  <div className="mt-2">
                                    <h4 className="text-xs font-medium text-muted-foreground mb-2">
                                      Chunks ({Array.isArray(resourceChunks[resource.id]) ? resourceChunks[resource.id]!.length : 0})
                                    </h4>
                                    {Array.isArray(resourceChunks[resource.id]) && resourceChunks[resource.id]!.length === 0 ? (
                                      <p className="text-sm text-amber-600 dark:text-amber-400">
                                        No chunks found - this explains why search returns no results!
                                      </p>
                                    ) : (
                                      <pre className="bg-muted p-3 rounded text-xs overflow-x-auto max-h-[400px] overflow-y-auto">
                                        {JSON.stringify(resourceChunks[resource.id], null, 2)}
                                      </pre>
                                    )}
                                  </div>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Query Testing Section */}
              <div className="border rounded-lg p-4 space-y-4">
                <h2 className="font-semibold">Test Query</h2>
                <div className="flex gap-2">
                  <Input
                    placeholder="Enter search query..."
                    value={ragQuery}
                    onChange={(e) => setRagQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleRagSearch()}
                    className="flex-1"
                  />
                  <Button
                    onClick={handleRagSearch}
                    disabled={isSearching || !ragQuery.trim() || resources.length === 0}
                  >
                    {isSearching ? "Searching..." : "Search"}
                  </Button>
                </div>

                {ragResult && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                          ragResult.success
                            ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                            : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
                        }`}
                      >
                        {ragResult.success ? "Success" : "Error"}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {ragResult.durationMs}ms
                      </span>
                    </div>

                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-1">Formatted Result</h4>
                      <pre className="bg-muted p-3 rounded-lg text-sm whitespace-pre-wrap overflow-x-auto max-h-[300px] overflow-y-auto">
                        {ragResult.formattedContent}
                      </pre>
                    </div>

                    <div>
                      <button
                        onClick={() => setShowRagRawJson(!showRagRawJson)}
                        className="text-sm font-medium flex items-center gap-1 hover:underline"
                      >
                        <span>{showRagRawJson ? "▼" : "▶"}</span>
                        Raw JSON Response
                      </button>
                      {showRagRawJson && (
                        <pre className="bg-muted p-3 rounded-lg text-xs mt-2 overflow-x-auto max-h-[400px] overflow-y-auto">
                          {JSON.stringify(ragResult.rawResponse, null, 2)}
                        </pre>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </TabsContent>

        {/* Test Suite Tab - Full Width 3-Column Layout */}
        <TabsContent value="test-suite" className="space-y-0">
          {testResourcesLoading ? (
            <div className="text-center py-8 text-muted-foreground">
              Loading test resources...
            </div>
          ) : (
            <div className="flex gap-4 h-[calc(100vh-200px)] min-h-[500px]">
              {/* Left Panel - Add Resource Form + Resource List */}
              <div className="w-[300px] flex-shrink-0 flex flex-col gap-4 overflow-hidden">
                {/* Add Test Resource Form */}
                <div className="border rounded-lg p-4 space-y-3">
                  <h3 className="font-semibold text-sm">Add Test Resource</h3>

                  <div className="space-y-2">
                    <Input
                      placeholder="Name"
                      value={testResourceName}
                      onChange={(e) => setTestResourceName(e.target.value)}
                      className="text-sm"
                    />
                    <Textarea
                      placeholder="Description (why is this problematic?)"
                      value={testResourceDescription}
                      onChange={(e) => setTestResourceDescription(e.target.value)}
                      rows={2}
                      className="text-sm resize-none"
                    />
                  </div>

                  {/* Type selector */}
                  <div className="flex gap-1">
                    {(["file", "url", "git"] as const).map((mode) => (
                      <Button
                        key={mode}
                        variant={testAddMode === mode ? "default" : "outline"}
                        size="sm"
                        className="text-xs flex-1"
                        onClick={() => setTestAddMode(mode)}
                      >
                        {mode === "file" ? "File" : mode === "url" ? "URL" : "Git"}
                      </Button>
                    ))}
                  </div>

                  {testAddMode === "file" && (
                    <Input
                      ref={testFileInputRef}
                      type="file"
                      onChange={handleAddTestResourceFile}
                      disabled={isAddingTestResource}
                      className="text-xs cursor-pointer"
                    />
                  )}

                  {testAddMode === "url" && (
                    <div className="space-y-2">
                      <Input
                        placeholder="https://example.com"
                        value={testResourceUrl}
                        onChange={(e) => setTestResourceUrl(e.target.value)}
                        className="text-sm"
                      />
                      <Button
                        onClick={handleAddTestResourceUrl}
                        disabled={isAddingTestResource || !testResourceUrl.trim()}
                        size="sm"
                        className="w-full"
                      >
                        {isAddingTestResource ? "Adding..." : "Add URL"}
                      </Button>
                    </div>
                  )}

                  {testAddMode === "git" && (
                    <div className="space-y-2">
                      <Input
                        placeholder="https://github.com/user/repo"
                        value={testResourceUrl}
                        onChange={(e) => setTestResourceUrl(e.target.value)}
                        className="text-sm"
                      />
                      <Input
                        placeholder="Branch (optional)"
                        value={testResourceGitBranch}
                        onChange={(e) => setTestResourceGitBranch(e.target.value)}
                        className="text-sm"
                      />
                      <Button
                        onClick={handleAddTestResourceGit}
                        disabled={isAddingTestResource || !testResourceUrl.trim()}
                        size="sm"
                        className="w-full"
                      >
                        {isAddingTestResource ? "Adding..." : "Add Git Repo"}
                      </Button>
                    </div>
                  )}

                  {testAddError && (
                    <p className="text-xs text-red-500">{testAddError}</p>
                  )}
                </div>

                {/* Test Resources List */}
                <div className="border rounded-lg p-4 flex-1 overflow-hidden flex flex-col">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-semibold text-sm">
                      Test Resources ({testResources.length})
                    </h3>
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-xs"
                      onClick={handleRunAllTests}
                      disabled={isRunningAll || testResources.length === 0}
                    >
                      {isRunningAll ? "Running..." : "Run All"}
                    </Button>
                  </div>

                  <div className="flex-1 overflow-y-auto space-y-2 chat-scrollbar">
                    {testResources.length === 0 ? (
                      <p className="text-xs text-muted-foreground text-center py-4">
                        No test resources yet
                      </p>
                    ) : (
                      testResources.map((resource) => (
                        <div
                          key={resource.id}
                          className={`p-2 rounded border cursor-pointer transition-colors ${
                            selectedTestResourceId === resource.id
                              ? "border-primary bg-primary/5"
                              : "hover:bg-muted/50"
                          }`}
                          onClick={() => setSelectedTestResourceId(resource.id)}
                        >
                          <div className="flex items-start justify-between gap-1">
                            <div className="flex-1 min-w-0">
                              <p className="font-medium text-sm truncate" title={resource.name}>
                                {resource.name}
                              </p>
                              <p className="text-xs text-muted-foreground">
                                {resource.type} {resource.file_size_bytes && `· ${(resource.file_size_bytes / 1024).toFixed(0)}KB`}
                              </p>
                              {resource.last_run && (
                                <p className="text-xs mt-0.5">
                                  <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1 ${
                                    resource.last_run.status === "success" ? "bg-green-500" :
                                    resource.last_run.status === "failed" ? "bg-red-500" :
                                    resource.last_run.status === "partial" ? "bg-amber-500" :
                                    "bg-blue-500 animate-pulse"
                                  }`} />
                                  {resource.last_run.status}
                                  {resource.last_run.chunk_count !== undefined && resource.last_run.chunk_count > 0 && (
                                    <span className="text-muted-foreground"> · {resource.last_run.chunk_count} chunks</span>
                                  )}
                                </p>
                              )}
                            </div>
                            <div className="flex items-center gap-0.5 shrink-0">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 w-6 p-0"
                                onClick={(e) => { e.stopPropagation(); handleRunTest(resource.id); }}
                                disabled={isRunningTest}
                                title="Run test"
                              >
                                <span className="text-xs">▶</span>
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 w-6 p-0 text-red-500 hover:text-red-600"
                                onClick={(e) => { e.stopPropagation(); handleDeleteTestResource(resource.id); }}
                                title="Delete"
                              >
                                <span className="text-xs">×</span>
                              </Button>
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>

              {/* Center Panel - Run History */}
              <div className="flex-1 border rounded-lg p-4 overflow-hidden flex flex-col min-w-0">
                {selectedTestResource ? (
                  <>
                    <div className="mb-4">
                      <h3 className="font-semibold">
                        Run History: {selectedTestResource.name}
                      </h3>
                      {selectedTestResource.description && (
                        <p className="text-sm text-muted-foreground mt-1">
                          {selectedTestResource.description}
                        </p>
                      )}
                    </div>

                    {testRunsLoading ? (
                      <div className="flex-1 flex items-center justify-center text-muted-foreground">
                        Loading runs...
                      </div>
                    ) : testRuns.length === 0 ? (
                      <div className="flex-1 flex items-center justify-center text-muted-foreground">
                        <div className="text-center">
                          <p>No runs yet</p>
                          <Button
                            variant="outline"
                            size="sm"
                            className="mt-2"
                            onClick={() => handleRunTest(selectedTestResource.id)}
                            disabled={isRunningTest}
                          >
                            {isRunningTest ? "Running..." : "Run First Test"}
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex-1 overflow-y-auto space-y-3 chat-scrollbar">
                        {testRuns.map((run, index) => (
                          <div
                            key={run.id}
                            className={`p-3 rounded border cursor-pointer transition-colors ${
                              selectedTestRun?.id === run.id
                                ? "border-primary bg-primary/5"
                                : "hover:bg-muted/50"
                            }`}
                            onClick={() => setSelectedTestRun(run)}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div>
                                <p className="text-sm font-medium">
                                  Run #{testRuns.length - index}
                                </p>
                                <p className="text-xs text-muted-foreground">
                                  {new Date(run.started_at).toLocaleString()}
                                </p>
                              </div>
                              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                                run.status === "success"
                                  ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                                  : run.status === "failed"
                                  ? "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
                                  : run.status === "partial"
                                  ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
                                  : "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200"
                              }`}>
                                {!TEST_RUN_TERMINAL_STATES.includes(run.status) && (
                                  <span className="inline-block w-2 h-2 rounded-full bg-current animate-pulse" />
                                )}
                                {run.status}
                              </span>
                            </div>

                            <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
                              {run.total_duration_ms !== undefined && (
                                <span>Duration: {(run.total_duration_ms / 1000).toFixed(1)}s</span>
                              )}
                              {run.chunk_count !== undefined && (
                                <span>Chunks: {run.chunk_count}</span>
                              )}
                            </div>

                            {run.error_message && (
                              <p className="mt-2 text-xs text-red-500 line-clamp-2">
                                {run.error_message}
                              </p>
                            )}

                            {run.summary && (
                              <p className="mt-2 text-xs text-muted-foreground line-clamp-2">
                                {run.summary}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="flex-1 flex items-center justify-center text-muted-foreground">
                    Select a test resource to view run history
                  </div>
                )}
              </div>

              {/* Right Panel - Run Details */}
              <div className="w-[400px] flex-shrink-0 border rounded-lg p-4 overflow-hidden flex flex-col">
                {selectedTestRun ? (
                  <>
                    <div className="mb-4">
                      <h3 className="font-semibold">
                        Full Metadata - Run #{testRuns.findIndex(r => r.id === selectedTestRun.id) >= 0 ? testRuns.length - testRuns.findIndex(r => r.id === selectedTestRun.id) : "?"}
                      </h3>
                      <p className="text-xs text-muted-foreground">
                        {new Date(selectedTestRun.started_at).toLocaleString()}
                      </p>
                    </div>

                    <div className="flex-1 overflow-y-auto chat-scrollbar">
                      <div className="space-y-4">
                        {/* Status & Timing */}
                        <div className="space-y-1 text-sm">
                          <p><span className="font-medium">Status:</span> {selectedTestRun.status}</p>
                          {selectedTestRun.extraction_duration_ms !== undefined && (
                            <p><span className="font-medium">Extraction:</span> {(selectedTestRun.extraction_duration_ms / 1000).toFixed(2)}s</p>
                          )}
                          {selectedTestRun.indexing_duration_ms !== undefined && (
                            <p><span className="font-medium">Indexing:</span> {(selectedTestRun.indexing_duration_ms / 1000).toFixed(2)}s</p>
                          )}
                          {selectedTestRun.total_duration_ms !== undefined && (
                            <p><span className="font-medium">Total:</span> {(selectedTestRun.total_duration_ms / 1000).toFixed(2)}s</p>
                          )}
                          {selectedTestRun.chunk_count !== undefined && (
                            <p><span className="font-medium">Chunks:</span> {selectedTestRun.chunk_count}</p>
                          )}
                        </div>

                        {/* View Chunks */}
                        {selectedTestRun.status === "success" && (
                          <div>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => {
                                if (testRunChunks) {
                                  setShowChunks(true);
                                } else {
                                  handleLoadChunks();
                                }
                              }}
                              disabled={isLoadingChunks}
                              className="text-xs"
                            >
                              {isLoadingChunks ? "Loading..." : "View Chunks"}
                            </Button>

                            <Dialog open={showChunks} onOpenChange={setShowChunks}>
                              <DialogContent className="max-h-[85vh] flex flex-col" style={{ maxWidth: '90vw', width: '90vw' }}>
                                <DialogHeader>
                                  <DialogTitle>
                                    Indexed Chunks ({testRunChunks?.length || 0})
                                  </DialogTitle>
                                </DialogHeader>
                                <div className="flex-1 overflow-y-auto space-y-3 pr-2">
                                  {testRunChunks?.map((chunk, i) => (
                                    <div key={chunk.id} className="bg-muted/50 p-4 rounded-lg border-l-4 border-primary/30">
                                      <div className="flex justify-between items-start gap-4 mb-2">
                                        <span className="font-semibold text-sm">
                                          Chunk {i + 1}
                                        </span>
                                        <span className="text-xs text-muted-foreground truncate max-w-[300px]" title={chunk.source}>
                                          {chunk.source}
                                        </span>
                                      </div>
                                      <p className="text-sm whitespace-pre-wrap">
                                        {chunk.content}
                                      </p>
                                      {Object.keys(chunk.metadata).length > 0 && (
                                        <div className="mt-2 pt-2 border-t border-border">
                                          <p className="text-xs text-muted-foreground">
                                            {Object.entries(chunk.metadata)
                                              .filter(([k]) => k !== "content")
                                              .map(([k, v]) => `${k}: ${v}`)
                                              .join(" • ")}
                                          </p>
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </DialogContent>
                            </Dialog>
                          </div>
                        )}

                        {/* Error */}
                        {selectedTestRun.error_message && (
                          <div>
                            <h4 className="text-sm font-medium text-red-500 mb-1">Error</h4>
                            <pre className="bg-red-50 dark:bg-red-950 p-2 rounded text-xs text-red-700 dark:text-red-300 whitespace-pre-wrap">
                              {selectedTestRun.error_message}
                            </pre>
                          </div>
                        )}

                        {/* Summary */}
                        {selectedTestRun.summary && (
                          <div>
                            <h4 className="text-sm font-medium mb-1">Summary</h4>
                            <p className="text-sm text-muted-foreground">{selectedTestRun.summary}</p>
                          </div>
                        )}

                        {/* Raw Metadata */}
                        {selectedTestRun.raw_metadata && (
                          <div>
                            <h4 className="text-sm font-medium mb-1">Raw Metadata</h4>
                            <pre className="bg-muted p-2 rounded text-xs overflow-x-auto max-h-[200px] overflow-y-auto">
                              {JSON.stringify(selectedTestRun.raw_metadata, null, 2)}
                            </pre>
                          </div>
                        )}

                        {/* Test Query Section */}
                        {selectedTestRun.status === "success" && (
                          <div className="border-t pt-4 mt-4">
                            <h4 className="text-sm font-medium mb-2">Test Query</h4>
                            <div className="space-y-3">
                              {/* System Prompt Toggle */}
                              <div>
                                <button
                                  onClick={() => setShowSystemPrompt(!showSystemPrompt)}
                                  className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                                >
                                  <span>{showSystemPrompt ? "▼" : "▶"}</span>
                                  System Prompt {testSystemPrompt && "(custom)"}
                                </button>
                                {showSystemPrompt && (
                                  <Textarea
                                    placeholder="Optional: Custom system prompt for the LLM..."
                                    value={testSystemPrompt}
                                    onChange={(e) => setTestSystemPrompt(e.target.value)}
                                    rows={3}
                                    className="mt-2 text-xs"
                                  />
                                )}
                              </div>

                              <div className="flex gap-2">
                                <Input
                                  placeholder="Ask a question about this document..."
                                  value={testQuery}
                                  onChange={(e) => setTestQuery(e.target.value)}
                                  onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleTestQuery()}
                                  className="flex-1 text-sm"
                                />
                                <Button
                                  size="sm"
                                  onClick={handleTestQuery}
                                  disabled={isQuerying || !testQuery.trim()}
                                >
                                  {isQuerying ? "..." : "Ask"}
                                </Button>
                              </div>

                              {queryError && (
                                <p className="text-xs text-red-500">{queryError}</p>
                              )}

                              {testQueryResult && (
                                <div className="space-y-3">
                                  {/* Answer */}
                                  <div>
                                    <h5 className="text-xs font-medium text-muted-foreground mb-1">Answer</h5>
                                    <div className="bg-muted p-3 rounded text-sm whitespace-pre-wrap">
                                      {testQueryResult.answer}
                                    </div>
                                  </div>

                                  {/* Sources */}
                                  {testQueryResult.sources.length > 0 && (
                                    <div>
                                      <h5 className="text-xs font-medium text-muted-foreground mb-1">
                                        Sources ({testQueryResult.sources.length})
                                      </h5>
                                      <div className="space-y-2">
                                        {testQueryResult.sources.map((source, i) => (
                                          <div key={i} className="bg-muted/50 p-2 rounded text-xs border-l-2 border-primary/30">
                                            <div className="flex justify-between items-start gap-2 mb-1">
                                              <span className="font-medium text-muted-foreground truncate flex-1">
                                                {source.source}
                                              </span>
                                              <span className="text-muted-foreground shrink-0">
                                                {(source.score * 100).toFixed(0)}%
                                              </span>
                                            </div>
                                            <p className="text-foreground whitespace-pre-wrap">
                                              {source.content}
                                            </p>
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
                    {selectedTestResource ? "Select a run to view details" : "Select a test resource first"}
                  </div>
                )}
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
