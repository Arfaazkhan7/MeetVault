import { Buffer } from "node:buffer";

export interface Env {
  AI_JOBS: Queue<AiJobMessage>;
  AI: Ai;
  BACKEND_API_BASE_URL: string;
  MEETVAULT_WORKER_SECRET: string;
  BACKEND_WORKER_CALLBACK_SECRET: string;
  PYANNOTEAI_API_KEY?: string;
  PYANNOTEAI_API_URL?: string;
}

interface AiJobMessage {
  job_id: string;
}

interface WorkerAiSegment {
  text: string;
  start_time: number;
  end_time: number;
  speaker_label: string;
  attribution_status?: "unknown" | "unverified" | "confirmed";
  confidence?: number;
}

interface JobContext {
  job_id: string;
  meeting_id: string;
  meeting_title: string;
  recording_url: string;
  file_type: string;
  duration_seconds?: number;
}

export interface SpeakerTurn {
  start: number;
  end: number;
  speaker: string;
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
    if ((context as JobContext & { completed?: boolean; processing?: boolean }).completed || (context as JobContext & { processing?: boolean }).processing) return;
    const audioResponse = await fetch(context.recording_url);
    if (!audioResponse.ok) {
      throw new Error(`Recording download failed ${audioResponse.status}: ${await audioResponse.text()}`);
    }

    const audioBuffer = await audioResponse.arrayBuffer();
    if (audioBuffer.byteLength > 20971520) throw new Error("Recording exceeds the free upload limit");
    const audio = Buffer.from(audioBuffer).toString("base64");
    const transcription = await env.AI.run("@cf/openai/whisper-large-v3-turbo", {
      audio,
      task: "transcribe",
      vad_filter: true,
    } as never) as unknown as Record<string, unknown>;

    const parsedSegments = parseSegments(transcription, Number(context.duration_seconds || 0));

    // Diarization: if pyannoteAI is configured, fetch real speaker turns
    let speakerTurns: SpeakerTurn[] = [];
    if (env.PYANNOTEAI_API_KEY) {
      try {
        speakerTurns = await diarizeRecording(context.recording_url, env);
      } catch (err) {
        console.warn("pyannoteAI diarization failed; proceeding with unassigned attribution", err);
      }
    }

    const hasDiarization = speakerTurns.length > 0;
    const mappedSegments = hasDiarization
      ? alignSpeakers(parsedSegments, speakerTurns)
      : parsedSegments.map((s) => ({
          ...s,
          speaker_label: "SPEAKER_UNASSIGNED",
          attribution_status: "unknown" as const,
        }));

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
          segments: mappedSegments,
          raw_result: {
            model: "@cf/openai/whisper-large-v3-turbo",
            diarization_provider: hasDiarization ? "pyannoteAI" : "none",
            speaker_attribution: hasDiarization ? "unverified" : "unknown",
            turns_detected: speakerTurns.length,
          },
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

export function parseSegments(transcription: Record<string, unknown>, durationSeconds = 0): WorkerAiSegment[] {
  const rawSegments = Array.isArray(transcription.segments) ? transcription.segments : [];
  const segments = rawSegments
    .map((item): WorkerAiSegment | null => {
      if (!item || typeof item !== "object") return null;
      const value = item as Record<string, unknown>;
      const text = String(value.text || "").trim();
      if (!text) return null;
      const rawStart = Number(value.start ?? value.start_time ?? 0);
      const rawEnd = Number(value.end ?? value.end_time ?? 0);
      const start_time = Number.isFinite(rawStart) ? Math.max(0, rawStart) : 0;
      let end_time = Number.isFinite(rawEnd) ? Math.max(start_time, rawEnd) : start_time;
      if (end_time === start_time && durationSeconds > start_time) {
        end_time = durationSeconds;
      }
      return {
        text,
        start_time,
        end_time,
        speaker_label: "SPEAKER_UNASSIGNED",
        attribution_status: "unknown",
        confidence: typeof value.avg_logprob === "number" ? value.avg_logprob : undefined,
      };
    })
    .filter((item): item is WorkerAiSegment => Boolean(item));

  if (segments.length) return segments;

  const text = String(transcription.text || "").trim();
  return text ? [{ text, start_time: 0, end_time: Math.max(0, durationSeconds), speaker_label: "SPEAKER_UNASSIGNED", attribution_status: "unknown" }] : [];
}

export async function diarizeRecording(recordingUrl: string, env: Env): Promise<SpeakerTurn[]> {
  if (!env.PYANNOTEAI_API_KEY) return [];

  const endpoint = env.PYANNOTEAI_API_URL || "https://api.pyannote.ai/v1/diarize";
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "authorization": `Bearer ${env.PYANNOTEAI_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({ url: recordingUrl }),
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    console.warn("pyannoteAI diarization skipped", response.status, detail.slice(0, 300));
    return [];
  }

  let payload = (await response.json().catch(() => null)) as Record<string, unknown> | null;
  // If pyannote returns an async job ID, poll until complete or timeout
  if (payload && (payload.jobId || payload.job_id) && !payload.output && payload.status !== "succeeded") {
    const jobId = String(payload.jobId || payload.job_id);
    const jobsEndpoint = endpoint.replace(/\/diarize\/?$/, `/jobs/${encodeURIComponent(jobId)}`);
    for (let attempt = 0; attempt < 30; attempt++) {
      await new Promise((r) => setTimeout(r, 2000));
      const pollResp = await fetch(jobsEndpoint, {
        headers: { "authorization": `Bearer ${env.PYANNOTEAI_API_KEY}` },
      });
      if (!pollResp.ok) break;
      payload = (await pollResp.json().catch(() => null)) as Record<string, unknown> | null;
      if (payload?.status === "succeeded" || payload?.output || payload?.diarization) break;
      if (payload?.status === "failed") break;
    }
  }

  return parseSpeakerTurns(payload);
}

export function parseSpeakerTurns(payload: Record<string, unknown> | null): SpeakerTurn[] {
  if (!payload) return [];
  const output = payload.output && typeof payload.output === "object"
    ? payload.output as Record<string, unknown>
    : {};
  const rawTurns = Array.isArray(output.diarization)
    ? output.diarization
    : Array.isArray(payload.diarization)
      ? payload.diarization
      : Array.isArray(payload)
        ? payload
        : [];

  return rawTurns
    .map((item): SpeakerTurn | null => {
      if (!item || typeof item !== "object") return null;
      const value = item as Record<string, unknown>;
      const start = Number(value.start ?? 0);
      const end = Number(value.end ?? 0);
      const speaker = String(value.speaker || value.label || "").trim();
      if (!speaker || !Number.isFinite(start) || !Number.isFinite(end) || end <= start || start < 0) {
        return null;
      }
      return { start, end, speaker };
    })
    .filter((item): item is SpeakerTurn => Boolean(item));
}

export function alignSpeakers(segments: WorkerAiSegment[], speakerTurns: SpeakerTurn[]): WorkerAiSegment[] {
  if (!segments.length) return [];
  if (!speakerTurns.length) {
    return segments.map((s) => ({
      ...s,
      speaker_label: "SPEAKER_UNASSIGNED",
      attribution_status: "unknown",
    }));
  }

  return segments.map((segment) => {
    let bestTurn: SpeakerTurn | null = null;
    let bestOverlap = 0;
    for (const turn of speakerTurns) {
      const overlap = Math.max(0, Math.min(segment.end_time, turn.end) - Math.max(segment.start_time, turn.start));
      if (overlap > bestOverlap) {
        bestOverlap = overlap;
        bestTurn = turn;
      }
    }

    if (!bestTurn && segment.end_time <= segment.start_time) {
      bestTurn = speakerTurns.find((turn) => turn.start <= segment.start_time && turn.end >= segment.start_time) || null;
    }

    return {
      ...segment,
      speaker_label: bestTurn ? bestTurn.speaker : "SPEAKER_UNASSIGNED",
      attribution_status: bestTurn ? "unverified" : "unknown",
    };
  });
}

