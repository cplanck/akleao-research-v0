"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Finding, listFindings, deleteFinding, summarizeFindings, emailFindings } from "@/lib/api";
import { toast } from "sonner";
import { MarkdownContent } from "@/components/markdown-content";

interface FindingsDialogProps {
  projectId: string;
  projectName: string;
  existingSummary: string | null;
  summaryUpdatedAt: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSummaryUpdated?: (summary: string) => void;
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

function DownloadIcon({ className }: { className?: string }) {
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
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" x2="12" y1="15" y2="3" />
    </svg>
  );
}

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
      <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
      <path d="M21 3v5h-5" />
    </svg>
  );
}

function MailIcon({ className }: { className?: string }) {
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
      <rect width="20" height="16" x="2" y="4" rx="2" />
      <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
    </svg>
  );
}

function CopyIcon({ className }: { className?: string }) {
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
      <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
      <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
    </svg>
  );
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

export function FindingsDialog({
  projectId,
  projectName,
  existingSummary,
  summaryUpdatedAt,
  open,
  onOpenChange,
  onSummaryUpdated,
}: FindingsDialogProps) {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [summary, setSummary] = useState(existingSummary || "");
  const [isSummarizing, setIsSummarizing] = useState(false);
  const [emailAddress, setEmailAddress] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("findings_email") || "";
    }
    return "";
  });
  const [isEmailing, setIsEmailing] = useState(false);

  // Load findings when dialog opens
  useEffect(() => {
    if (open) {
      loadFindings();
      setSummary(existingSummary || "");
    }
  }, [open, projectId, existingSummary]);

  // Auto-generate summary if we have findings but no summary
  useEffect(() => {
    if (open && findings.length > 0 && !summary && !isSummarizing) {
      handleGenerateSummary();
    }
  }, [open, findings.length, summary]);

  const loadFindings = async () => {
    setIsLoading(true);
    try {
      const data = await listFindings(projectId);
      setFindings(data);
    } catch (error) {
      console.error("Failed to load findings:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (findingId: string) => {
    if (!confirm("Delete this finding?")) return;
    try {
      await deleteFinding(projectId, findingId);
      setFindings(findings.filter((f) => f.id !== findingId));
      toast.success("Finding deleted");
    } catch (error) {
      console.error("Failed to delete finding:", error);
      toast.error("Failed to delete finding");
    }
  };

  const handleGenerateSummary = async () => {
    if (findings.length === 0) return;
    setIsSummarizing(true);
    try {
      const result = await summarizeFindings(projectId);
      setSummary(result.summary);
      onSummaryUpdated?.(result.summary);
      toast.success("Summary generated");
    } catch (error) {
      console.error("Failed to summarize:", error);
      toast.error("Failed to generate summary");
    } finally {
      setIsSummarizing(false);
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(summary);
    toast.success("Copied to clipboard");
  };

  const handleDownload = () => {
    const blob = new Blob([summary], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${projectName}-findings-${new Date().toISOString().split("T")[0]}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Downloaded");
  };

  const handleEmail = async () => {
    if (!emailAddress.trim()) {
      toast.error("Please enter an email address");
      return;
    }
    setIsEmailing(true);
    try {
      const trimmedEmail = emailAddress.trim();
      await emailFindings(projectId, trimmedEmail, summary || undefined);
      localStorage.setItem("findings_email", trimmedEmail);
      toast.success(`Sent to ${trimmedEmail}`);
    } catch (error) {
      console.error("Failed to send email:", error);
      toast.error("Failed to send email");
    } finally {
      setIsEmailing(false);
    }
  };

  // State for mobile tab view
  const [activeTab, setActiveTab] = useState<"findings" | "summary">("summary");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[95vw] max-w-4xl h-[85vh] sm:h-[70vh] flex flex-col p-0">
        <DialogHeader className="px-4 sm:px-6 py-3 sm:py-4 border-b flex-shrink-0">
          <DialogTitle className="flex items-center gap-2">
            <BookmarkIcon className="w-5 h-5 text-muted-foreground" />
            Key Findings
            {findings.length > 0 && (
              <span className="text-sm font-normal text-muted-foreground">
                ({findings.length})
              </span>
            )}
          </DialogTitle>
        </DialogHeader>

        {/* Mobile tabs */}
        <div className="sm:hidden flex border-b flex-shrink-0">
          <button
            onClick={() => setActiveTab("summary")}
            className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === "summary"
                ? "border-b-2 border-primary text-foreground"
                : "text-muted-foreground"
            }`}
          >
            Summary
          </button>
          <button
            onClick={() => setActiveTab("findings")}
            className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === "findings"
                ? "border-b-2 border-primary text-foreground"
                : "text-muted-foreground"
            }`}
          >
            Findings ({findings.length})
          </button>
        </div>

        <div className="flex-1 flex overflow-hidden">
          {/* Left pane - Findings list (hidden on mobile unless tab selected) */}
          <div className={`${activeTab === "findings" ? "flex" : "hidden"} sm:flex w-full sm:w-1/3 border-r flex-col`}>
            <div className="flex-1 overflow-y-auto p-2">
              {isLoading ? (
                <div className="text-xs text-muted-foreground text-center py-4">
                  Loading...
                </div>
              ) : findings.length === 0 ? (
                <div className="text-xs text-muted-foreground text-center py-8">
                  <p>No findings yet</p>
                  <p className="mt-1 text-[10px]">
                    Select text in a response and click "Save as Finding"
                  </p>
                </div>
              ) : (
                <div className="space-y-1.5">
                  {findings.map((finding) => (
                    <div
                      key={finding.id}
                      className="group relative rounded-md bg-background border border-border p-2 text-xs hover:border-foreground/20 transition-colors"
                    >
                      <div className="flex items-start gap-2">
                        <BookmarkIcon className="w-3 h-3 flex-shrink-0 mt-0.5 text-muted-foreground" />
                        <div className="flex-1 min-w-0">
                          <p className="line-clamp-3 text-foreground/80 leading-snug text-[11px]">
                            "{finding.content}"
                          </p>
                          {finding.note && (
                            <p className="mt-1 text-muted-foreground/70 italic line-clamp-1 text-[10px]">
                              {finding.note}
                            </p>
                          )}
                          <p className="mt-1 text-[9px] text-muted-foreground/50">
                            {formatRelativeTime(finding.created_at)}
                          </p>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-5 w-5 p-0 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity text-destructive/70 hover:text-destructive hover:bg-destructive/10"
                          title="Delete finding"
                          onClick={() => handleDelete(finding.id)}
                        >
                          <TrashIcon className="w-3 h-3" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right pane - Summary (hidden on mobile unless tab selected) */}
          <div className={`${activeTab === "summary" ? "flex" : "hidden"} sm:flex flex-1 flex-col`}>
            <div className="flex-1 overflow-y-auto p-4 relative">
              {findings.length > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="absolute top-2 right-2 h-7 px-2 text-xs"
                  onClick={handleGenerateSummary}
                  disabled={isSummarizing}
                  title="Regenerate summary"
                >
                  <RefreshIcon className={`w-3.5 h-3.5 mr-1 ${isSummarizing ? "animate-spin" : ""}`} />
                  {isSummarizing ? "Generating..." : "Regenerate"}
                </Button>
              )}
              {isSummarizing ? (
                <div className="flex items-center justify-center h-full">
                  <div className="text-center">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto mb-3" />
                    <p className="text-sm text-muted-foreground">Generating summary...</p>
                  </div>
                </div>
              ) : summary ? (
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  <MarkdownContent content={summary} />
                </div>
              ) : findings.length === 0 ? (
                <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                  Add findings to generate a summary
                </div>
              ) : (
                <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                  Click "Regenerate" to create a summary
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer - Export options */}
        {summary && (
          <div className="border-t p-3 sm:p-4 bg-muted/30 flex-shrink-0">
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleCopy}
                  className="h-9 flex-1 sm:flex-none"
                  title="Copy to clipboard"
                >
                  <CopyIcon className="w-4 h-4 mr-1.5" />
                  Copy
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleDownload}
                  className="h-9 flex-1 sm:flex-none"
                  title="Download as file"
                >
                  <DownloadIcon className="w-4 h-4 mr-1.5" />
                  Download
                </Button>
              </div>
              <div className="hidden sm:block flex-1" />
              <div className="flex items-center gap-2">
                <Input
                  type="email"
                  placeholder="email@example.com"
                  value={emailAddress}
                  onChange={(e) => setEmailAddress(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleEmail()}
                  className="h-9 flex-1 sm:w-56 text-sm"
                />
                <Button
                  onClick={handleEmail}
                  disabled={isEmailing || !emailAddress.trim()}
                  className="h-9"
                >
                  <MailIcon className="w-4 h-4 sm:mr-1.5" />
                  <span className="hidden sm:inline">{isEmailing ? "Sending..." : "Email"}</span>
                </Button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
