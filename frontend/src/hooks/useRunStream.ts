import { useCallback, useEffect, useRef, useState } from "react";

import { executeRunAIAgent, getRun, getWebSocketUrl, RunDetail, RunEvent } from "../api/client";



export function useRunStream(runId: string | undefined) {

  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);

  const [events, setEvents] = useState<RunEvent[]>([]);

  const [connected, setConnected] = useState(false);

  const [liveFrame, setLiveFrame] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  const handledInvokes = useRef<Set<string>>(new Set());



  const refresh = useCallback(async () => {

    if (!runId) return;

    const detail = await getRun(runId);

    setRunDetail(detail);

    setEvents(detail.events);

  }, [runId]);



  useEffect(() => {

    handledInvokes.current.clear();

  }, [runId]);



  useEffect(() => {

    if (!runId) return;



    for (const event of events) {

      if (event.event_type !== "ai_agent_invoke") continue;

      const canvasId = String(event.payload?.canvas_id || "");

      if (!canvasId) continue;

      const invokeKey = `${event.id || event.created_at || ""}:${canvasId}`;

      if (handledInvokes.current.has(invokeKey)) continue;

      handledInvokes.current.add(invokeKey);



      const config = (event.payload?.config || {}) as Record<string, unknown>;

      const contextData = (event.payload?.context_data || {}) as Record<string, unknown>;



      executeRunAIAgent(runId, {

        canvas_id: canvasId,

        config: {

          agent_name: String(config.agent_name || "OpenAI Agent"),

          instructions: String(config.instructions || ""),

          user_prompt: String(config.user_prompt || ""),

          model: String(config.model || "gpt-4o"),

          temperature: Number(config.temperature ?? 0.7),

          max_tokens: Number(config.max_tokens ?? 1000),

        },

        context_data: contextData,

      })

        .then(() => refresh())

        .catch((err) => console.error("AI agent execute failed:", err));

    }

  }, [events, runId, refresh]);



  useEffect(() => {

    if (!runId) {

      setLiveFrame(null);

      return;

    }

    setLiveFrame(null);

    refresh();



    const ws = new WebSocket(getWebSocketUrl(runId));

    wsRef.current = ws;



    ws.onopen = () => setConnected(true);

    ws.onclose = () => setConnected(false);

    ws.onmessage = (msg) => {

      try {

        const data = JSON.parse(msg.data);

        if (data.type === "ping") return;



        if (data.event_type === "browser_frame") {

          const frame = data.payload?.frame as string | undefined;

          if (frame) setLiveFrame(frame);

          return;

        }



        if (data.event_type) {

          setEvents((prev) => {

            const exists = prev.some((e) => e.id === data.id);

            if (exists) return prev;

            return [...prev, data];

          });

          if (data.event_type === "run_completed" || data.event_type === "run_failed") {

            refresh();

          } else {

            setRunDetail((prev) => {

              if (!prev) return prev;

              return {

                ...prev,

                run: {

                  ...prev.run,

                  status:

                    data.event_type === "run_completed"

                      ? "completed"

                      : data.event_type === "run_failed"

                        ? "failed"

                        : prev.run.status,

                },

              };

            });

          }

        }

      } catch {

        /* ignore */

      }

    };



    const poll = setInterval(refresh, 15000);



    return () => {

      ws.close();

      clearInterval(poll);

      setLiveFrame(null);

    };

  }, [runId, refresh]);



  return { runDetail, events, connected, liveFrame, refresh };

}


