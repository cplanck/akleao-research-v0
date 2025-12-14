"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Finding, listFindings, deleteFinding, summarizeFindings, emailFindings } from "@/lib/api";
import { toast } from "sonner";

interface FindingsPanelProps {
  projectId: string;
  refreshTrigger?: number;
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

function SparklesIcon({ className }: { className?: string }) {
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
      <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
      <path d="M5 3v4" />
      <path d="M19 17v4" />
      <path d="M3 5h4" />
      <path d="M17 19h4" />
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

function ShareIcon({ className }: { className?: string }) {
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
      <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
      <polyline points="16 6 12 2 8 6" />
      <line x1="12" x2="12" y1="2" y2="15" />
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

function formatFindingsAsText(findings: Finding[]): string {
  return findings.map((f, i) =>
    `${i + 1}. "${f.content}"${f.note ? `\n   Note: ${f.note}` : ""}\n   Saved: ${new Date(f.created_at).toLocaleString()}`
  ).join("\n\n");
}

export function FindingsPanel({ projectId, refreshTrigger }: FindingsPanelProps) {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [exportDialogOpen, setExportDialogOpen] = useState(false);
  const [exportContent, setExportContent] = useState("");
  const [isSummarizing, setIsSummarizing] = useState(false);
  const [hasSummarized, setHasSummarized] = useState(false);
  const [emailAddress, setEmailAddress] = useState(() => {
    // Load saved email from localStorage on init
    if (typeof window !== "undefined") {
      return localStorage.getItem("findings_email") || "";
    }
    return "";
  });
  const [isEmailing, setIsEmailing] = useState(false);

  const loadFindings = async () => {
    try {
      const data = await listFindings(projectId);
      setFindings(data);
    } catch (error) {
      console.error("Failed to load findings:", error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadFindings();
  }, [projectId, refreshTrigger]);

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

  const handleOpenExport = () => {
    setExportContent(formatFindingsAsText(findings));
    setHasSummarized(false);
    setEmailAddress("");
    setExportDialogOpen(true);
  };

  const handleSummarize = async () => {
    setIsSummarizing(true);
    try {
      const result = await summarizeFindings(projectId);
      setExportContent(result.summary);
      setHasSummarized(true);
      toast.success("Summary generated");
    } catch (error) {
      console.error("Failed to summarize:", error);
      toast.error("Failed to summarize findings");
    } finally {
      setIsSummarizing(false);
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(exportContent);
    toast.success("Copied to clipboard");
  };

  const handleDownload = () => {
    const blob = new Blob([exportContent], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `findings-${new Date().toISOString().split("T")[0]}.txt`;
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
      // Pass exportContent if user has summarized or edited the content
      await emailFindings(projectId, trimmedEmail, exportContent || undefined);
      // Save email to localStorage for next time
      localStorage.setItem("findings_email", trimmedEmail);
      toast.success(`Sent to ${trimmedEmail}`);
    } catch (error) {
      console.error("Failed to send email:", error);
      toast.error("Failed to send email");
    } finally {
      setIsEmailing(false);
    }
  };

  if (isLoading) {
    return (
      <div className="text-xs text-muted-foreground text-center py-4">
        Loading...
      </div>
    );
  }

  if (findings.length === 0) {
    return (
      <p className="text-xs text-muted-foreground text-center py-2">
        Key findings will appear here
      </p>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-muted/30 p-3 space-y-3">
      {/* Findings list */}
      <div className="space-y-1.5">
        {findings.map((finding) => (
          <div
            key={finding.id}
            className="group relative rounded-md bg-background/60 border border-border p-2 text-xs hover:border-foreground/20 transition-colors"
          >
            <div className="flex items-start gap-2">
              <BookmarkIcon className="w-3 h-3 flex-shrink-0 mt-0.5 text-muted-foreground" />
              <div className="flex-1 min-w-0">
                <p className="line-clamp-2 text-foreground/80 leading-snug text-[11px]">
                  "{finding.content}"
                </p>
                {finding.note && (
                  <p className="mt-1 text-muted-foreground/70 italic line-clamp-1 text-[10px]">
                    {finding.note}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-1">
                <span className="text-[9px] text-muted-foreground/50">
                  {formatRelativeTime(finding.created_at)}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-4 w-4 p-0 opacity-0 group-hover:opacity-100 transition-opacity text-destructive/70 hover:text-destructive hover:bg-destructive/10"
                  title="Delete finding"
                  onClick={() => handleDelete(finding.id)}
                >
                  <TrashIcon className="w-2.5 h-2.5" />
                </Button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Export Button */}
      <Button
        size="sm"
        className="w-full h-9 text-xs font-medium bg-white hover:bg-gray-100 text-gray-900 border border-gray-200"
        onClick={handleOpenExport}
      >
        <ShareIcon className="w-3.5 h-3.5 mr-1.5" />
        Export {findings.length} Finding{findings.length !== 1 ? "s" : ""}
      </Button>

      {/* Export Dialog */}
      <Dialog open={exportDialogOpen} onOpenChange={setExportDialogOpen}>
        <DialogContent className="sm:max-w-4xl max-h-[85vh] flex flex-col">
          <DialogHeader className="flex flex-row items-center justify-between">
            <DialogTitle className="flex items-center gap-2">
              <BookmarkIcon className="w-5 h-5 text-muted-foreground" />
              Export Findings
              <span className="text-sm font-normal text-muted-foreground ml-1">
                ({findings.length} item{findings.length !== 1 ? "s" : ""})
              </span>
            </DialogTitle>
            <div className="flex items-center gap-1">
              <Button
                variant={hasSummarized ? "secondary" : "default"}
                size="sm"
                onClick={handleSummarize}
                disabled={isSummarizing}
                className="h-8 px-3"
                title="Summarize with AI"
              >
                {isSummarizing ? (
                  <div className="animate-spin rounded-full h-3.5 w-3.5 border-b-2 border-current" />
                ) : (
                  <SparklesIcon className="w-3.5 h-3.5" />
                )}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCopy}
                className="h-8 w-8 p-0"
                title="Copy to clipboard"
              >
                <CopyIcon className="w-4 h-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleDownload}
                className="h-8 w-8 p-0"
                title="Download as file"
              >
                <DownloadIcon className="w-4 h-4" />
              </Button>
            </div>
          </DialogHeader>

          <div className="flex-1 flex flex-col gap-4 overflow-hidden">
            {/* Show raw findings link when summarized */}
            {hasSummarized && (
              <button
                className="text-xs text-muted-foreground hover:text-foreground transition-colors self-start"
                onClick={() => {
                  setExportContent(formatFindingsAsText(findings));
                  setHasSummarized(false);
                }}
              >
                Show raw findings
              </button>
            )}

            {/* Editable Content */}
            <Textarea
              value={exportContent}
              onChange={(e) => setExportContent(e.target.value)}
              className="flex-1 min-h-[200px] text-sm font-mono resize-none"
              placeholder="Your findings will appear here..."
            />

            {/* Email Section */}
            <div className="flex items-center gap-2 border-t pt-4">
              <Input
                type="email"
                placeholder="email@example.com"
                value={emailAddress}
                onChange={(e) => setEmailAddress(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleEmail()}
                className="h-10 flex-1 text-sm"
              />
              <Button
                onClick={handleEmail}
                disabled={isEmailing || !emailAddress.trim()}
                className="h-10 px-6"
              >
                <MailIcon className="w-4 h-4 mr-2" />
                {isEmailing ? "Sending..." : "Send Email"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
