"use client";

import { useEffect, useRef, useState } from "react";

const CHARS_PER_FRAME = 6;
const LAG_THRESHOLD = 80;

export function useStreamingDisplay(content: string | null, charsPerFrame = CHARS_PER_FRAME): string {
  const [displayed, setDisplayed] = useState("");
  const rafRef = useRef<number>();
  const contentRef = useRef(content);

  contentRef.current = content;

  useEffect(() => {
    if (content === null) {
      setDisplayed("");
      return;
    }

    const loop = () => {
      setDisplayed((prev) => {
        const target = contentRef.current ?? "";
        const diff = target.length - prev.length;
        if (diff <= 0) return prev;
        const step = diff > LAG_THRESHOLD ? diff : Math.min(charsPerFrame, diff);
        const next = target.slice(0, prev.length + step);
        if (next.length < target.length) {
          rafRef.current = requestAnimationFrame(loop);
        }
        return next;
      });
    };

    rafRef.current = requestAnimationFrame(loop);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [content, charsPerFrame]);

  return content === null ? "" : displayed;
}
