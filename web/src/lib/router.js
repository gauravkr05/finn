import { useEffect, useState } from "react";

const parse = () => (window.location.hash.replace(/^#\/?/, "") || "today").split("/").map(decodeURIComponent);

export function useRoute() {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => {
      setRoute(parse());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export const go = (path) => {
  window.location.hash = "/" + path;
};
