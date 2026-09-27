import { useCallback, useEffect, useRef, useState } from "react";
import type { Job } from "../types";
import { api } from "../services/api";

/** Load data on mount / when deps change; exposes reload(). */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const d = await fnRef.current();
      setData(d);
      setError(null);
      return d;
    } catch (e) {
      setError((e as Error).message);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload, setData };
}

const ACTIVE = new Set(["queued", "running"]);

/** Poll a generation job until it finishes; calls onDone once. */
export function useJob(jobId: string | null | undefined, onDone?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const j = await api.job(jobId);
        if (stop) return;
        setJob(j);
        if (ACTIVE.has(j.status)) timer = setTimeout(tick, 1200);
        else doneRef.current?.(j);
      } catch {
        if (!stop) timer = setTimeout(tick, 3000);
      }
    };
    tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  return job;
}

export const isActive = (job: Job | null | undefined) => !!job && ACTIVE.has(job.status);
