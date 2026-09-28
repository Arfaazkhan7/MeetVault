export interface Env {
  AI_JOBS: Queue<AiJobMessage>;
  AI: Ai;
  BACKEND_API_BASE_URL: string;
  MEETVAULT_WORKER_SECRET: string;
  BACKEND_WORKER_CALLBACK_SECRET: string;
}

interface AiJobMessage {
  job_id: string;
}

interface WorkerAiSegment {
  text: string;
  start_time: number;
  end_time: number;
  speaker_label: string;
  confidence?: number;
}

interface JobContext {
  job_id: string;
  meeting_id: string;
  meeting_title: string;
  recording_url: string;
  file_type: string;
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method !== "POST") {
      return jsonResponse({ ok: false, error: "method_not_allowed" }, 405);
    }

    const providedSecret = request.headers.get("x-meetvault-worker-secret") || "";
    if (!env.MEETVAULT_WORKER_SECRET || providedSecret !== env.MEETVAULT_WORKER_SECRET) {
      return jsonResponse({ ok: false, error: "unauthorized" }, 401);
    }

    const body = (await request.json().catch(() => null)) as AiJobMessage | null;
    if (!body?.job_id) {
      return jsonResponse({ ok: false, error: "job_id_required" }, 400);
    }

    await env.AI_JOBS.send({ job_id: body.job_id });
    return jsonResponse({ ok: true, queued: body.job_id });
  },

  async queue(batch: MessageBatch<AiJobMessage>, env: Env): Promise<void> {
    for (const message of batch.messages) {
      const { job_id } = message.body;
      try {
        await processJob(job_id, env);
        message.ack();
      } catch (error) {
        console.error("MeetVault Cloudflare AI job failed", job_id, error);
        message.retry();
      }
    }
  },
};

async function processJob(jobId: string, env: Env): Promise<void> {
  const secret = env.BACKEND_WORKER_CALLBACK_SECRET || env.MEETVAULT_WORKER_SECRET;
  try {
    const contextResponse = await fetch(
      `${env.BACKEND_API_BASE_URL}/ai-jobs/${encodeURIComponent(jobId)}/cloudflare/context`,
      { headers: { "x-meetvault-worker-secret": secret } },
    );
    if (!contextResponse.ok) {
      throw new Error(`Context request failed ${contextResponse.status}: ${await contextResponse.text()}`);
    }

    const context = (await contextResponse.json()) as JobContext;
    const audioResponse = await fetch(context.recording_url);
    if (!audioResponse.ok) {
      throw new Error(`Recording download failed ${audioResponse.status}: ${await audioResponse.text()}`);
    }

    const audio = [...new Uint8Array(await audioResponse.arrayBuffer())];
    const transcription = await env.AI.run("@cf/openai/whisper-large-v3-turbo", {
      audio,
      task: "transcribe",
      vad_filter: true,
    } as never) as unknown as Record<string, unknown>;

    const resultResponse = await fetch(
      `${env.BACKEND_API_BASE_URL}/ai-jobs/${encodeURIComponent(jobId)}/cloudflare/result`,
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-meetvault-worker-secret": secret,
        },
        body: JSON.stringify({
          provider: "cloudflare-workers-ai",
          transcription_text: String(transcription.text || ""),
          segments: parseSegments(transcription),
          raw_result: transcription,
        }),
      },
    );

    if (!resultResponse.ok) {
      throw new Error(`Result callback failed ${resultResponse.status}: ${await resultResponse.text()}`);
    }
  } catch (error) {
    await fetch(`${env.BACKEND_API_BASE_URL}/ai-jobs/${encodeURIComponent(jobId)}/cloudflare/fail`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-meetvault-worker-secret": secret,
      },
      body: JSON.stringify({ error: error instanceof Error ? error.message : String(error) }),
    }).catch(() => undefined);
    throw error;
  }
}

function parseSegments(transcription: Record<string, unknown>): WorkerAiSegment[] {
  const rawSegments = Array.isArray(transcription.segments) ? transcription.segments : [];
  const segments = rawSegments
    .map((item): WorkerAiSegment | null => {
      if (!item || typeof item !== "object") return null;
      const value = item as Record<string, unknown>;
      const text = String(value.text || "").trim();
      if (!text) return null;
      return {
        text,
        start_time: Number(value.start ?? value.start_time ?? 0),
        end_time: Number(value.end ?? value.end_time ?? 0),
        speaker_label: "SPEAKER_0",
        confidence: typeof value.avg_logprob === "number" ? value.avg_logprob : undefined,
      };
    })
    .filter((item): item is WorkerAiSegment => Boolean(item));

  if (segments.length) return segments;

  const text = String(transcription.text || "").trim();
  return text ? [{ text, start_time: 0, end_time: 0, speaker_label: "SPEAKER_0" }] : [];
}
