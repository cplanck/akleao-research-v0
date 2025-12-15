"use client";

interface LoadingSpinnerProps {
  /** Optional text to show below the animation */
  text?: string;
  /** Size variant */
  size?: "sm" | "md" | "lg";
  /** Whether to show the full-screen centered layout */
  fullScreen?: boolean;
}

export function LoadingSpinner({
  text,
  size = "md",
  fullScreen = false
}: LoadingSpinnerProps) {
  const dotSizes = {
    sm: "w-1.5 h-1.5",
    md: "w-2 h-2",
    lg: "w-3 h-3",
  };

  const gapSizes = {
    sm: "gap-1",
    md: "gap-1.5",
    lg: "gap-2",
  };

  const textSizes = {
    sm: "text-xs",
    md: "text-sm",
    lg: "text-base",
  };

  const content = (
    <div className="flex flex-col items-center gap-3">
      <div className={`flex items-center ${gapSizes[size]}`}>
        <div className={`claude-loading-dot ${dotSizes[size]}`} />
        <div className={`claude-loading-dot ${dotSizes[size]}`} />
        <div className={`claude-loading-dot ${dotSizes[size]}`} />
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
