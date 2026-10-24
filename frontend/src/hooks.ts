import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorText } from "./api";

export function useRemote<T>(path: string | null, interval?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!!path);
  const [version, setVersion] = useState(0);
  const latest = useRef(0);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);
  useEffect(() => {
    if (!path) return;
    window.addEventListener("online", refresh);
    window.addEventListener("app-resumed", refresh);
    const visible = () => {
      if (!document.hidden) refresh();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.removeEventListener("online", refresh);
      window.removeEventListener("app-resumed", refresh);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [path, refresh]);
  useEffect(() => {
    setData(null);
    setError("");
    setLoading(!!path);
  }, [path]);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    const request = ++latest.current;
    api<T>(path, { signal: controller.signal })
      .then((value) => {
        if (request === latest.current) {
          setData(value);
          setError("");
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted && request === latest.current)
          setError(errorText(e));
      })
      .finally(() => {
        if (!controller.signal.aborted && request === latest.current)
          setLoading(false);
      });
    return () => controller.abort();
  }, [path, version]);
  useEffect(() => {
    if (!interval || !path) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) refresh();
    }, interval);
    return () => window.clearInterval(timer);
  }, [path, interval, refresh]);
  return { data, error, loading, refresh };
}

export function usePath() {
  const [route, setRoute] = useState(() => ({
    path: location.pathname,
    search: location.search,
  }));
  useEffect(() => {
    const update = () =>
      setRoute({ path: location.pathname, search: location.search });
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  const navigate = useCallback((target: string) => {
    history.pushState({}, "", target);
    setRoute({ path: location.pathname, search: location.search });
    window.scrollTo({ top: 0 });
  }, []);
  return { ...route, navigate };
}
