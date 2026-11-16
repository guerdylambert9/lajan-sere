import { useEffect, useState } from "react";

export type Route =
  | { view: "desk"; book: string | null }
  | { view: "learn" }
  | { view: "lesson"; id: string }
  | { view: "quiz"; id: string }
  | { view: "glossary" };

export function parseHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] !== "learn") return { view: "desk", book: parts[0] ?? null };
  if (!parts[1]) return { view: "learn" };
  if (parts[1] === "glossary") return { view: "glossary" };
  if (parts[1] === "quiz" && parts[2]) return { view: "quiz", id: parts[2] };
  return { view: "lesson", id: parts[1] };
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parseHash(window.location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
