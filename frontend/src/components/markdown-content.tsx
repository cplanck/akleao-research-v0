"use client";

import { useState, useMemo, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
// Custom GitHub Light theme (matching modern GitHub)
const githubLight: { [key: string]: React.CSSProperties } = {
  'code[class*="language-"]': {
    color: "#24292f",
    background: "none",
    fontFamily: "ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace",
    textAlign: "left",
    whiteSpace: "pre",
    wordSpacing: "normal",
    wordBreak: "normal",
    wordWrap: "normal",
    lineHeight: "1.5",
    tabSize: 4,
    hyphens: "none",
  },
  'pre[class*="language-"]': {
    color: "#24292f",
    background: "#f6f8fa",
    fontFamily: "ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace",
    textAlign: "left",
    whiteSpace: "pre",
    wordSpacing: "normal",
    wordBreak: "normal",
    wordWrap: "normal",
    lineHeight: "1.5",
    tabSize: 4,
    hyphens: "none",
    padding: "1em",
    margin: "0",
    overflow: "auto",
  },
  comment: { color: "#6e7781" },
  prolog: { color: "#6e7781" },
  doctype: { color: "#6e7781" },
  cdata: { color: "#6e7781" },
  punctuation: { color: "#24292f" },
  namespace: { opacity: 0.7 },
  property: { color: "#0550ae" },
  tag: { color: "#116329" },
  boolean: { color: "#0550ae" },
  number: { color: "#0550ae" },
  constant: { color: "#0550ae" },
  symbol: { color: "#0550ae" },
  deleted: { color: "#82071e" },
  selector: { color: "#116329" },
  "attr-name": { color: "#0550ae" },
  string: { color: "#0a3069" },
  char: { color: "#0a3069" },
  builtin: { color: "#953800" },
  inserted: { color: "#116329" },
  operator: { color: "#cf222e" },
  entity: { color: "#8250df", cursor: "help" },
  url: { color: "#0a3069" },
  ".language-css .token.string": { color: "#0a3069" },
  ".style .token.string": { color: "#0a3069" },
  atrule: { color: "#0550ae" },
  "attr-value": { color: "#0a3069" },
  keyword: { color: "#cf222e" },
  function: { color: "#8250df" },
  "class-name": { color: "#953800" },
  regex: { color: "#0a3069" },
  important: { color: "#cf222e", fontWeight: "bold" },
  variable: { color: "#953800" },
  bold: { fontWeight: "bold" },
  italic: { fontStyle: "italic" },
};

// Custom GitHub Dark theme
const githubDark: { [key: string]: React.CSSProperties } = {
  'code[class*="language-"]': {
    color: "#e6edf3",
    background: "none",
    fontFamily: "ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace",
    textAlign: "left",
    whiteSpace: "pre",
    wordSpacing: "normal",
    wordBreak: "normal",
    wordWrap: "normal",
    lineHeight: "1.5",
    tabSize: 4,
    hyphens: "none",
  },
  'pre[class*="language-"]': {
    color: "#e6edf3",
    background: "#0d1117",
    fontFamily: "ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace",
    textAlign: "left",
    whiteSpace: "pre",
    wordSpacing: "normal",
    wordBreak: "normal",
    wordWrap: "normal",
    lineHeight: "1.5",
    tabSize: 4,
    hyphens: "none",
    padding: "1em",
    margin: "0",
    overflow: "auto",
  },
  comment: { color: "#8b949e" },
  prolog: { color: "#8b949e" },
  doctype: { color: "#8b949e" },
  cdata: { color: "#8b949e" },
  punctuation: { color: "#e6edf3" },
  namespace: { opacity: 0.7 },
  property: { color: "#79c0ff" },
  tag: { color: "#7ee787" },
  boolean: { color: "#79c0ff" },
  number: { color: "#79c0ff" },
  constant: { color: "#79c0ff" },
  symbol: { color: "#79c0ff" },
  deleted: { color: "#ffa198" },
  selector: { color: "#7ee787" },
  "attr-name": { color: "#79c0ff" },
  string: { color: "#a5d6ff" },
  char: { color: "#a5d6ff" },
  builtin: { color: "#ffa657" },
  inserted: { color: "#7ee787" },
  operator: { color: "#ff7b72" },
  entity: { color: "#d2a8ff", cursor: "help" },
  url: { color: "#a5d6ff" },
  ".language-css .token.string": { color: "#a5d6ff" },
  ".style .token.string": { color: "#a5d6ff" },
  atrule: { color: "#79c0ff" },
  "attr-value": { color: "#a5d6ff" },
  keyword: { color: "#ff7b72" },
  function: { color: "#d2a8ff" },
  "class-name": { color: "#ffa657" },
  regex: { color: "#a5d6ff" },
  important: { color: "#ff7b72", fontWeight: "bold" },
  variable: { color: "#ffa657" },
  bold: { fontWeight: "bold" },
  italic: { fontStyle: "italic" },
};
import type { Components } from "react-markdown";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { useTheme } from "next-themes";

interface MarkdownContentProps {
  content: string;
  workspaceId?: string;
  onAddUrl?: (url: string) => Promise<void>;
  isStreaming?: boolean;  // Whether content is still being streamed
}

/**
 * Result of processing streaming content for incomplete markdown.
 */
interface ProcessedStreamingContent {
  content: string;
  incompleteCodeBlock: {
    language: string;
    code: string;
  } | null;
}

/**
 * Processes streaming content to handle incomplete markdown constructs.
 * - Links/images: trimmed (prevents showing raw syntax)
 * - Code blocks: extracted separately so they can be rendered with streaming indicator
 */
function processStreamingContent(content: string): ProcessedStreamingContent {
  let processedContent = content;
  let incompleteCodeBlock: ProcessedStreamingContent['incompleteCodeBlock'] = null;

  // Check for incomplete code block FIRST: ``` without closing
  const codeBlockMatches = processedContent.match(/```/g);
  if (codeBlockMatches && codeBlockMatches.length % 2 === 1) {
    // Odd number of ``` means unclosed code block - extract it
    const lastCodeBlockStart = processedContent.lastIndexOf('```');
    const codeBlockContent = processedContent.slice(lastCodeBlockStart + 3);

    // Parse language (first line) and code (rest)
    const firstNewline = codeBlockContent.indexOf('\n');
    if (firstNewline !== -1) {
      const language = codeBlockContent.slice(0, firstNewline).trim() || 'text';
      const code = codeBlockContent.slice(firstNewline + 1);
      incompleteCodeBlock = { language, code };
    } else {
      // Just has language, no code yet
      incompleteCodeBlock = { language: codeBlockContent.trim() || 'text', code: '' };
    }

    // Remove the incomplete code block from content
    processedContent = processedContent.slice(0, lastCodeBlockStart);
  }

  // Check for incomplete link: [text](url or [text]( or [text
  const linkMatch = processedContent.match(/\[[^\]]*$|\[[^\]]*\]\([^)]*$/);
  if (linkMatch) {
    processedContent = processedContent.slice(0, linkMatch.index);
  }

  // Check for incomplete image: ![alt](url or ![alt]( or ![alt
  const imageMatch = processedContent.match(/!\[[^\]]*$|!\[[^\]]*\]\([^)]*$/);
  if (imageMatch) {
    processedContent = processedContent.slice(0, imageMatch.index);
  }

  // Check for incomplete inline code: `code without closing backtick
  const lines = processedContent.split('\n');
  const lastLine = lines[lines.length - 1];
  const backtickCount = (lastLine.match(/`/g) || []).length;
  if (backtickCount % 2 === 1) {
    const lastBacktick = lastLine.lastIndexOf('`');
    lines[lines.length - 1] = lastLine.slice(0, lastBacktick);
    processedContent = lines.join('\n');
  }

  // Check for incomplete bold/italic at end: **text or *text or __text or _text
  const emphasisMatch = processedContent.match(/(\*\*|\*|__|_)[^*_\n]*$/);
  if (emphasisMatch) {
    const match = emphasisMatch[0];
    const marker = emphasisMatch[1];
    const rest = match.slice(marker.length);
    if (!rest.includes(marker)) {
      processedContent = processedContent.slice(0, emphasisMatch.index);
    }
  }

  return { content: processedContent, incompleteCodeBlock };
}

/**
 * Legacy function for non-streaming content - just returns trimmed content.
 */
function trimIncompleteMarkdown(content: string): string {
  return processStreamingContent(content).content;
}

// Code block with copy button, language header, and theme support
function CodeBlock({
  language,
  children,
  isStreaming = false,
}: {
  language: string;
  children: string;
  isStreaming?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const { resolvedTheme } = useTheme();

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(children);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [children]);

  // Format language name for display
  const displayLanguage = language === "text" ? "plaintext" : language;

  // Use GitHub theme colors for consistency
  const isDark = resolvedTheme === "dark";
  const codeStyle = isDark ? githubDark : githubLight;
  // GitHub Dark: #0d1117, GitHub Light: #f6f8fa
  const bgColor = isDark ? "#0d1117" : "#f6f8fa";
  const headerBgColor = isDark ? "#161b22" : "#f0f3f6";
  const textColor = isDark ? "#e6edf3" : "#24292f";

  return (
    <div
      className="relative group my-3 rounded-lg border border-border overflow-hidden"
      style={{ backgroundColor: bgColor }}
    >
      {/* Header bar */}
      <div
        className="flex items-center justify-between px-4 py-2 border-b border-border/50"
        style={{ backgroundColor: headerBgColor }}
      >
        <div className="flex items-center gap-2">
          <span
            className="text-xs font-medium uppercase tracking-wide"
            style={{ color: textColor, opacity: 0.7 }}
          >
            {displayLanguage}
          </span>
          {isStreaming && (
            <span className="flex items-center gap-1.5 text-xs text-violet-500">
              <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" />
              generating
            </span>
          )}
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 text-xs transition-colors"
          style={{ color: textColor, opacity: copied ? 1 : 0.7 }}
          aria-label={copied ? "Copied!" : "Copy code"}
        >
          {copied ? (
            <>
              <svg
                className="w-4 h-4 text-green-500"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M5 13l4 4L19 7"
                />
              </svg>
              <span className="text-green-500">Copied!</span>
            </>
          ) : (
            <>
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                />
              </svg>
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      {/* Code content */}
      <SyntaxHighlighter
        style={codeStyle}
        language={language}
        PreTag="div"
        customStyle={{
          margin: 0,
          borderRadius: 0,
          padding: "1rem",
          fontSize: "0.875rem",
          lineHeight: "1.5",
        }}
        codeTagProps={{
          style: {
            fontSize: "0.875rem",
            fontFamily: "ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace",
            lineHeight: "1.5",
          }
        }}
      >
        {children}
      </SyntaxHighlighter>
    </div>
  );
}

// Link with popover for adding to workspace
function LinkWithPopover({
  href,
  children,
  onAddUrl,
}: {
  href?: string;
  children: React.ReactNode;
  onAddUrl?: (url: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState(false);

  const handleAdd = async () => {
    if (!href || !onAddUrl) return;
    setAdding(true);
    try {
      await onAddUrl(href);
      setAdded(true);
      setTimeout(() => setOpen(false), 1000);
    } catch (err) {
      console.error("Failed to add URL:", err);
    } finally {
      setAdding(false);
    }
  };

  // Only show popover for external URLs when onAddUrl is provided
  const isExternal = href?.startsWith("http");
  if (!isExternal || !onAddUrl) {
    return (
      <a href={href} className="text-primary underline" target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <a
          href={href}
          className="text-primary underline cursor-pointer"
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => {
            // Right-click or ctrl/cmd+click opens normally
            if (e.ctrlKey || e.metaKey || e.button === 2) return;
            e.preventDefault();
            setOpen(true);
          }}
        >
          {children}
        </a>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-2" side="top">
        <div className="flex flex-col gap-2">
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-muted-foreground hover:text-foreground truncate max-w-[200px]"
          >
            {href}
          </a>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                window.open(href, "_blank");
                setOpen(false);
              }}
            >
              Open
            </Button>
            <Button
              size="sm"
              onClick={handleAdd}
              disabled={adding || added}
            >
              {added ? "Added!" : adding ? "Adding..." : "Add to workspace"}
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export function MarkdownContent({ content, onAddUrl, isStreaming = false }: MarkdownContentProps) {
  // When streaming, process content to extract incomplete code blocks
  const { displayContent, incompleteCodeBlock } = useMemo(() => {
    if (isStreaming) {
      const processed = processStreamingContent(content);
      return { displayContent: processed.content, incompleteCodeBlock: processed.incompleteCodeBlock };
    }
    return { displayContent: content, incompleteCodeBlock: null };
  }, [content, isStreaming]);

  const components: Components = {
    code({ node, className, children, ...props }) {
      const match = /language-(\w+)/.exec(className || "");
      const isInline = !match && !String(children).includes("\n");

      if (isInline) {
        return (
          <code
            className="bg-muted px-1.5 py-0.5 rounded text-sm font-mono"
            {...props}
          >
            {children}
          </code>
        );
      }

      return (
        <CodeBlock language={match ? match[1] : "text"}>
          {String(children).replace(/\n$/, "")}
        </CodeBlock>
      );
    },
    p({ children }) {
      return <p className="mb-3 last:mb-0">{children}</p>;
    },
    ul({ children }) {
      return <ul className="list-disc pl-4 mb-2">{children}</ul>;
    },
    ol({ children }) {
      return <ol className="list-decimal pl-4 mb-2">{children}</ol>;
    },
    li({ children }) {
      return <li className="mb-1">{children}</li>;
    },
    h1({ children }) {
      return <h1 className="text-lg font-bold mb-2">{children}</h1>;
    },
    h2({ children }) {
      return <h2 className="text-base font-bold mb-2">{children}</h2>;
    },
    h3({ children }) {
      return <h3 className="text-sm font-bold mb-1">{children}</h3>;
    },
    a({ href, children }) {
      return (
        <LinkWithPopover href={href} onAddUrl={onAddUrl}>
          {children}
        </LinkWithPopover>
      );
    },
    blockquote({ children }) {
      return (
        <blockquote className="border-l-2 border-muted-foreground/30 pl-3 italic my-2">
          {children}
        </blockquote>
      );
    },
    table({ children }) {
      return (
        <div className="overflow-x-auto my-2">
          <table className="min-w-full border-collapse text-sm">{children}</table>
        </div>
      );
    },
    th({ children }) {
      return <th className="border border-border px-2 py-1 bg-muted font-medium">{children}</th>;
    },
    td({ children }) {
      return <td className="border border-border px-2 py-1">{children}</td>;
    },
  };

  return (
    <div className="prose prose-sm dark:prose-invert max-w-none leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={components}>
        {displayContent}
      </ReactMarkdown>
      {/* Render incomplete code block separately with streaming indicator */}
      {incompleteCodeBlock && (
        <CodeBlock language={incompleteCodeBlock.language} isStreaming>
          {incompleteCodeBlock.code}
        </CodeBlock>
      )}
    </div>
  );
}
