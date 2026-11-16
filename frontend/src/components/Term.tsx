import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { GLOSSARY } from "../learn/course";

/** A word on the dashboard that opens a short definition, with a link to its lesson. */
export function Term({ id, children }: { id: string; children: ReactNode }) {
  const entry = GLOSSARY[id];
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLSpanElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (wrap.current && !wrap.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!entry) return <>{children}</>;
  return (
    <span className="term" ref={wrap}>
      <button
        type="button"
        className="term-word"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        {children}
      </button>
      {open && (
        <span className="term-card" id={panelId} role="note">
          <strong>{entry.term}</strong> {entry.definition}{" "}
          {entry.lesson && <a href={`#/learn/${entry.lesson}`}>Read the lesson</a>}
        </span>
      )}
    </span>
  );
}
