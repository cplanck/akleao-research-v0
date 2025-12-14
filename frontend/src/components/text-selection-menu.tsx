"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { Button } from "@/components/ui/button";
import { MessageSquarePlus, Bookmark } from "lucide-react";

interface TextSelectionMenuProps {
  onDiveDeeper: (text: string) => void;
  onSaveAsFinding: (text: string) => void;
  containerRef?: React.RefObject<HTMLElement | null>;
  minSelectionLength?: number;
}

interface MenuPosition {
  x: number;
  y: number;
}

export function TextSelectionMenu({
  onDiveDeeper,
  onSaveAsFinding,
  containerRef,
  minSelectionLength = 10,
}: TextSelectionMenuProps) {
  const [position, setPosition] = useState<MenuPosition | null>(null);
  const [selectedText, setSelectedText] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);

  const hideMenu = useCallback(() => {
    setPosition(null);
    setSelectedText("");
  }, []);

  // Shared logic to check selection and show menu
  const checkSelectionAndShowMenu = useCallback(() => {
    const selection = window.getSelection();
    const text = selection?.toString().trim();

    if (!text || text.length < minSelectionLength) {
      hideMenu();
      return;
    }

    // Check if selection is within our container (if specified)
    if (containerRef?.current && selection?.anchorNode) {
      const container = containerRef.current;
      if (!container.contains(selection.anchorNode)) {
        hideMenu();
        return;
      }
    }

    // Get selection rectangle
    const range = selection?.getRangeAt(0);
    const rect = range?.getBoundingClientRect();

    if (rect && rect.width > 0) {
      // Position above the selection, centered
      setPosition({
        x: rect.left + rect.width / 2,
        y: rect.top - 8,
      });
      setSelectedText(text);
    }
  }, [containerRef, minSelectionLength, hideMenu]);

  const handleMouseUp = useCallback(() => {
    // Small delay to let selection finalize
    setTimeout(checkSelectionAndShowMenu, 10);
  }, [checkSelectionAndShowMenu]);

  const handleMouseDown = useCallback(
    (event: MouseEvent) => {
      // Hide menu if clicking outside of it
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        hideMenu();
      }
    },
    [hideMenu]
  );

  // Handle touch events for iOS
  const handleTouchEnd = useCallback(() => {
    // Longer delay for iOS to let selection handles settle
    setTimeout(checkSelectionAndShowMenu, 300);
  }, [checkSelectionAndShowMenu]);

  const handleTouchStart = useCallback(
    (event: TouchEvent) => {
      // Hide menu if touching outside of it
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        hideMenu();
      }
    },
    [hideMenu]
  );

  // Handle selection change (works on iOS when user adjusts selection handles)
  const handleSelectionChange = useCallback(() => {
    const selection = window.getSelection();
    const text = selection?.toString().trim();

    // If selection is cleared, hide menu
    if (!text) {
      hideMenu();
      return;
    }

    // If we have a significant selection, update position (with debounce via the existing menu)
    if (text.length >= minSelectionLength && position) {
      // Update position if selection changed
      const range = selection?.getRangeAt(0);
      const rect = range?.getBoundingClientRect();
      if (rect && rect.width > 0) {
        setPosition({
          x: rect.left + rect.width / 2,
          y: rect.top - 8,
        });
        setSelectedText(text);
      }
    }
  }, [hideMenu, minSelectionLength, position]);

  const handleScroll = useCallback(() => {
    hideMenu();
  }, [hideMenu]);

  useEffect(() => {
    // Mouse events (desktop)
    document.addEventListener("mouseup", handleMouseUp);
    document.addEventListener("mousedown", handleMouseDown);

    // Touch events (iOS/mobile)
    document.addEventListener("touchend", handleTouchEnd);
    document.addEventListener("touchstart", handleTouchStart);

    // Selection change (helps with iOS selection handles)
    document.addEventListener("selectionchange", handleSelectionChange);

    // Scroll
    window.addEventListener("scroll", handleScroll, true);

    return () => {
      document.removeEventListener("mouseup", handleMouseUp);
      document.removeEventListener("mousedown", handleMouseDown);
      document.removeEventListener("touchend", handleTouchEnd);
      document.removeEventListener("touchstart", handleTouchStart);
      document.removeEventListener("selectionchange", handleSelectionChange);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [handleMouseUp, handleMouseDown, handleTouchEnd, handleTouchStart, handleSelectionChange, handleScroll]);

  const handleDiveDeeper = useCallback(() => {
    if (selectedText) {
      onDiveDeeper(selectedText);
      hideMenu();
      window.getSelection()?.removeAllRanges();
    }
  }, [selectedText, onDiveDeeper, hideMenu]);

  const handleSaveFinding = useCallback(() => {
    if (selectedText) {
      onSaveAsFinding(selectedText);
      hideMenu();
      window.getSelection()?.removeAllRanges();
    }
  }, [selectedText, onSaveAsFinding, hideMenu]);

  if (!position) return null;

  return (
    <div
      ref={menuRef}
      className="fixed z-50 bg-popover border rounded-lg shadow-lg p-1 flex gap-1 animate-in fade-in-0 zoom-in-95 duration-100"
      style={{
        left: position.x,
        top: position.y,
        transform: "translate(-50%, -100%)",
      }}
    >
      <Button
        size="sm"
        variant="ghost"
        onClick={handleDiveDeeper}
        className="h-8 px-2 text-xs"
      >
        <MessageSquarePlus className="h-4 w-4 mr-1" />
        Dive Deeper
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={handleSaveFinding}
        className="h-8 px-2 text-xs"
      >
        <Bookmark className="h-4 w-4 mr-1" />
        Save Finding
      </Button>
    </div>
  );
}
