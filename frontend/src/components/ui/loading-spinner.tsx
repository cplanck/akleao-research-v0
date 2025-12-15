"use client";

interface LoadingSpinnerProps {
  /** Optional text to show below the animation */
  text?: string;
  /** Size variant */
  size?: "sm" | "md" | "lg";
  /** Whether to show the full-screen centered layout */
  fullScreen?: boolean;
}

// Claude-style sparkle/star SVG
function SparkleIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
    >
      {/* 4-pointed star/sparkle shape */}
      <path d="M12 0L14.59 9.41L24 12L14.59 14.59L12 24L9.41 14.59L0 12L9.41 9.41L12 0Z" />
    </svg>
  );
}

export function LoadingSpinner({
  text,
  size = "md",
  fullScreen = false
}: LoadingSpinnerProps) {
  const iconSizes = {
    sm: "w-5 h-5",
    md: "w-8 h-8",
    lg: "w-12 h-12",
  };

  const textSizes = {
    sm: "text-xs",
    md: "text-sm",
    lg: "text-base",
  };

  const content = (
    <div className="flex flex-col items-center gap-3">
      <div className="claude-sparkle text-violet-500 dark:text-violet-400">
        <SparkleIcon className={iconSizes[size]} />
      </div>
      {text && (
        <p className={`text-muted-foreground ${textSizes[size]}`}>
          {text}
        </p>
      )}
    </div>
  );

  if (fullScreen) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        {content}
      </div>
    );
  }

  return content;
}
