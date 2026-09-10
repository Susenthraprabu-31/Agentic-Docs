import { useCallback, useEffect, useRef, useState } from "react";
import { getRun, getWebSocketUrl, RunDetail, RunEvent } from "../api/client";

export function useRunStream(runId: string | undefined) {
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const refresh = useCallback(async () => {
    if (!runId) return;
    const detail = await getRun(runId);
    setRunDetail(detail);
    setEvents(detail.events);
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    refresh();

    const ws = new WebSocket(getWebSocketUrl(runId));
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        if (data.type === "ping") return;
        if (data.event_type) {
          setEvents((prev) => {
            const exists = prev.some((e) => e.id === data.id);
            return exists ? prev : [...prev, data];
          });
          refresh();
        }
      } catch {
        /* ignore */
      }
    };

    const poll = setInterval(refresh, 5000);

    return () => {
      ws.close();
      clearInterval(poll);
    };
  }, [runId, refresh]);

  return { runDetail, events, connected, refresh };
}
