"use client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Safe-by-default Markdown renderer for AI-generated briefs.
 * - GFM (tables, strikethrough, task lists) on
 * - links open in a new tab with rel=noreferrer
 * - styling lives in globals.css under .brief-prose
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="brief-prose">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer" />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
