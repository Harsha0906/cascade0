"use client";

import { useCallback, useEffect, useState } from "react";
import { callApi } from "./api";

export interface ApiData<T> {
  data: T | null;
  error: string;
  status: number;
  loading: boolean;
  reload: () => Promise<void>;
}

/** GET a path once (and on reload()). A 404 is reported through `status`, not hidden. */
export function useApiData<T = any>(path: string | null): ApiData<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState(0);
  const [loading, setLoading] = useState(Boolean(path));

  const reload = useCallback(async () => {
    if (!path) return;
    const r = await callApi<T>(path);
    setStatus(r.status);
    setError(r.error);
    if (r.ok) setData(r.data);
    setLoading(false);
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, status, loading, reload };
}
