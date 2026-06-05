"use client";
import { LucideIcon } from "@/components/ui/Icon";
import { setActiveClause } from "@/lib/api";
import { startAudioCapture, type AudioCaptureHandle } from "@/lib/audioCapture";
import type {
  DebugLine,
  RiskReport,
  TranscriptEntry,
  VoiceStatus,
} from "@/lib/types";
import { useCallback, useEffect, useRef, useState } from "react";

interface VoicePanelProps {
  sessionId: string;
  riskReport: RiskReport;
  initialClauseId?: string | null;
  /** Risk IDs the user selected before clicking "Call Your Agent" (multi-clause). */
  selectedClauseIds?: string[];
  onClose: () => void;
  onDebugLine: (kind: DebugLine["kind"], text: string) => void;
  /**
   * Phase 8E: use Gemini Live native audio-in/audio-out (/ws/live/).
   * When false (default): Journey TTS pipeline (/ws/voice/).
   */
  useLive?: boolean;
}

type MicLang = "en-US" | "ar-SA";

type WsState = "connecting" | "open" | "closed" | "error";

// Silent reconnect attempts before we surface a manual "Reconnect" button.
const MAX_SILENT_RECONNECTS = 3;

interface LiveDiag {
  micStatus: "off" | "granted" | "denied" | "capturing";
  chunksSent: number; // audio_input chunks sent by the browser
  audioChunksRecv: number; // audio_chunk events received from backend
  lastCloseCode: number | null;
  lastCloseReason: string;
  lastError: string;
  timeToFirstAudio: number | null; // seconds, from turn submit to first audio
  fellBack: boolean; // auto-switched to Journey TTS
}

const INITIAL_DIAG: LiveDiag = {
  micStatus: "off",
  chunksSent: 0,
  audioChunksRecv: 0,
  lastCloseCode: null,
  lastCloseReason: "",
  lastError: "",
  timeToFirstAudio: null,
  fellBack: false,
};

/** Read a NEXT_PUBLIC_ numeric env (seconds) with a fallback. */
function envSeconds(name: string, fallback: number): number {
  const raw = process.env[name];
  const n = raw ? Number(raw) : NaN;
  return Number.isFinite(n) && n > 0 ? n : fallback;
}
// First Live turn can be cold (~4.5s); give it a longer grace window than
// subsequent turns before auto-falling back to Journey TTS. Configurable.
const FIRST_TURN_TIMEOUT_MS =
  envSeconds("NEXT_PUBLIC_LIVE_FIRST_TURN_TIMEOUT_SECONDS", 8) * 1000;
const TURN_TIMEOUT_MS =
  envSeconds("NEXT_PUBLIC_LIVE_TURN_TIMEOUT_SECONDS", 5) * 1000;

const STATUS_ICON: Record<VoiceStatus, string> = {
  idle: "mic-off",
  listening: "mic",
  thinking: "loader",
  speaking: "volume-2",
  tool_running: "zap",
  draft_ready: "check-circle",
  error: "alert-circle",
};

// Stored per audio chunk in the playback queue
interface AudioChunkEntry {
  audio: string; // base64 WAV
  text: string; // chunk text (drives live caption when available)
  duration_ms: number;
  turn_id: number;
  // Web Audio: undefined = not decoded yet, AudioBuffer = ready, null = decode failed.
  buffer?: AudioBuffer | null;
}

type MicPhase =
  | "ready"
  | "listening"
  | "heard"
  | "processing"
  | "no-speech"
  | "error";

interface MicDiag {
  language: string;
  permission: string;
  status: string;
  lastInterim: string;
  lastFinal: string;
  lastError: string;
}

const MIC_PHASE_LABEL: Record<MicPhase, string> = {
  ready: "Mic ready",
  listening: "Listening…",
  heard: "Heard voice…",
  processing: "Processing speech…",
  "no-speech": "No speech detected — try again",
  error: "Mic error — try again",
};

const LOOKAHEAD_S = 0.1; // 100ms schedule lookahead for gapless Web Audio playback

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

function estimateDurationMs(text: string): number {
  return Math.max(text.trim().split(/\s+/).length * 400, 600);
}

function getWsUrl(sessionId: string, useLive = false): string {
  // Prefer an explicit WS base URL; otherwise derive it from the API base URL
  // (http→ws). Accepts NEXT_PUBLIC_WS_BASE_URL / NEXT_PUBLIC_API_BASE_URL and
  // the legacy NEXT_PUBLIC_API_URL.
  const wsBase = process.env.NEXT_PUBLIC_WS_BASE_URL;
  const apiBase =
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://localhost:8001";
  const base = wsBase || apiBase.replace(/^http/, "ws");
  return (
    base.replace(/\/$/, "") + `/ws/${useLive ? "live" : "voice"}/${sessionId}`
  );
}

function buildWs(
  url: string,
  onOpen: () => void,
  onMsg: (e: MessageEvent) => void,
  onClose: (e: CloseEvent) => void,
  onError: (e: Event) => void,
): WebSocket {
  const ws = new WebSocket(url);
  ws.onopen = onOpen;
  ws.onmessage = onMsg;
  ws.onclose = onClose;
  ws.onerror = onError;
  return ws;
}

export function VoicePanel({
  sessionId,
  riskReport,
  initialClauseId,
  selectedClauseIds = [],
  onClose,
  onDebugLine,
  useLive = false,
}: VoicePanelProps) {
  const [micLang, setMicLang] = useState<MicLang>("en-US"); // mic recognition locale
  const [micLangUnsupported, setMicLangUnsupported] = useState(false);
  const [micPhase, setMicPhase] = useState<MicPhase>("ready");
  const [interimText, setInterimText] = useState(""); // live partial transcript
  const [showMicDiag, setShowMicDiag] = useState(false);
  const [micDiag, setMicDiag] = useState<MicDiag>({
    language: "en-US",
    permission: "unknown",
    status: "idle",
    lastInterim: "",
    lastFinal: "",
    lastError: "",
  });
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus>("idle");
  const [statusLabel, setStatusLabel] = useState("Connecting…");
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [draft, setDraft] = useState<{
    text: string;
    clauseIds: string[];
  } | null>(null);
  const [isMuted, setIsMuted] = useState(false);
  const [isListening, setIsListening] = useState(false); // SpeechRecognition mode
  const [isLiveMic, setIsLiveMic] = useState(false); // Live mic streaming mode
  const [textInput, setTextInput] = useState("");
  const [wsState, setWsState] = useState<WsState>("connecting");
  const [draftCopied, setDraftCopied] = useState(false);
  const [reconnectKey, setReconnectKey] = useState(0);
  const [micLevel, setMicLevel] = useState(0); // 0–1 RMS for level indicator

  // Effective transport mode. Starts from the useLive prop; auto-flips to TTS
  // (false) if Live produces no audio — the call keeps working either way.
  const [liveMode, setLiveMode] = useState(useLive);
  const [diag, setDiag] = useState<LiveDiag>(INITIAL_DIAG);
  const [showDiag, setShowDiag] = useState(true);

  // ── Live caption (growing agent bubble) ─────────────────────────────────
  const [growingText, setGrowingText] = useState<string | null>(null);

  // ── Lifecycle / fallback refs ──────────────────────────────────────────
  const endedByUserRef = useRef(false); // user clicked End Call
  const reconnectAttemptsRef = useRef(0); // silent reconnect counter
  const liveModeRef = useRef(useLive); // current mode (for handlers)
  const fellBackRef = useRef(false); // already fell back this session
  const noAudioTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const gotAudioThisTurnRef = useRef(false); // audio arrived for current turn
  const turnStartRef = useRef<number>(0); // performance.now() at turn submit
  const turnCountRef = useRef(0); // submitted turns (1st gets longer grace)

  // ── Greeting de-dup + playback-state refs ──────────────────────────────────
  const greetingShownRef = useRef(false); // greeting text added to transcript
  const acceptGreetingAudioRef = useRef(false); // play THIS connection's greeting audio
  const audioDoneRef = useRef(false); // backend signalled end-of-turn audio
  const lastPlayedTurnRef = useRef(-1); // turn_id of the chunk last played
  const connectLogKeyRef = useRef(""); // de-dupe "WS connecting" (StrictMode)

  const wsRef = useRef<WebSocket | null>(null);
  const srRef = useRef<any>(null);
  const isMutedRef = useRef(false);
  const voicesRef = useRef<SpeechSynthesisVoice[]>([]);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  // ── Live mic refs ────────────────────────────────────────────────────────
  const captureHandleRef = useRef<AudioCaptureHandle | null>(null);

  // ── Audio queue ──────────────────────────────────────────────────────────
  const audioQueueRef = useRef<Map<number, AudioChunkEntry>>(new Map());
  const nextSeqRef = useRef(0);
  const isPlayingRef = useRef(false);
  const currentTurnIdRef = useRef<number>(0);
  // Seqs whose TTS failed/timed out — skipped so a gap never stalls the queue.
  const failedSeqsRef = useRef<Set<number>>(new Set());

  // ── Web Audio gapless playback ─────────────────────────────────────────────
  const audioCtxRef = useRef<AudioContext | null>(null);
  const nextStartTimeRef = useRef(0); // AudioContext time the next buffer starts
  const activeSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const turnSpeakingRef = useRef<number>(-1); // turn we've already flipped to "speaking"

  // ── Live caption refs ────────────────────────────────────────────────────
  const growingTextRef = useRef("");
  const growingTurnIdRef = useRef(-1);
  const revealTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  // ── Word-by-word reveal ──────────────────────────────────────────────────
  const clearRevealTimers = useCallback(() => {
    revealTimersRef.current.forEach(clearTimeout);
    revealTimersRef.current = [];
  }, []);

  const revealWords = useCallback(
    (text: string, durationMs: number, turnId: number) => {
      const words = text.trim().split(/\s+/).filter(Boolean);
      if (!words.length) return;
      const msPerWord = Math.min(Math.max(durationMs / words.length, 40), 250);
      words.forEach((word, i) => {
        const t = setTimeout(() => {
          if (currentTurnIdRef.current !== turnId) return;
          const sep = growingTextRef.current.length > 0 ? " " : "";
          growingTextRef.current = growingTextRef.current + sep + word;
          setGrowingText(growingTextRef.current);
        }, i * msPerWord);
        revealTimersRef.current.push(t);
      });
    },
    [],
  );

  const finalizeGrowingText = useCallback(() => {
    if (growingTextRef.current.length > 0) {
      const text = growingTextRef.current;
      setTranscript((prev) => [...prev, { role: "agent", text, kind: "text" }]);
    }
    growingTextRef.current = "";
    growingTurnIdRef.current = -1;
    setGrowingText(null);
  }, []);

  // ── Audio playback (Web Audio API — gapless, scheduled buffers) ────────────
  const ensureCtx = useCallback((): AudioContext | null => {
    if (!audioCtxRef.current) {
      const AC =
        (window as any).AudioContext || (window as any).webkitAudioContext;
      if (!AC) return null;
      try {
        audioCtxRef.current = new AC();
      } catch {
        return null;
      }
    }
    if (audioCtxRef.current!.state === "suspended") {
      audioCtxRef.current!.resume().catch(() => {});
    }
    return audioCtxRef.current;
  }, []);

  const maybeGoIdle = useCallback(() => {
    // Idle only when nothing is scheduled/playing AND the next chunk isn't here.
    if (
      activeSourcesRef.current.size > 0 ||
      audioQueueRef.current.has(nextSeqRef.current)
    ) {
      return;
    }
    isPlayingRef.current = false;
    // Turn audio is truly finished: backend sent audio_done, or it was the
    // greeting (turn 0, no audio_done).
    if (audioDoneRef.current || lastPlayedTurnRef.current === 0) {
      audioDoneRef.current = false;
      finalizeGrowingText();
      setVoiceStatus("idle");
      setStatusLabel("Ready");
    }
  }, [finalizeGrowingText]);

  // Schedule every consecutive decoded chunk back-to-back so there are no gaps
  // or clicks between sentences. Called when a chunk finishes decoding, when a
  // tts_error unblocks a gap, and when a source ends.
  const scheduleAvailable = useCallback(() => {
    if (isMutedRef.current) return;
    const ctx = audioCtxRef.current;
    if (!ctx) return;

    // eslint-disable-next-line no-constant-condition
    while (true) {
      // Skip seqs whose TTS failed/timed out (so a gap never stalls the queue).
      while (
        !audioQueueRef.current.has(nextSeqRef.current) &&
        failedSeqsRef.current.has(nextSeqRef.current)
      ) {
        failedSeqsRef.current.delete(nextSeqRef.current);
        nextSeqRef.current += 1;
      }
      const entry = audioQueueRef.current.get(nextSeqRef.current);
      if (!entry) {
        maybeGoIdle(); // gap (awaiting a chunk) or fully drained
        return;
      }
      if (entry.buffer === undefined) {
        return; // next chunk not decoded yet — its decode callback re-invokes us
      }
      // Consume this seq.
      audioQueueRef.current.delete(nextSeqRef.current);
      nextSeqRef.current += 1;

      const { buffer, text, duration_ms, turn_id } = entry;
      const isGreeting = turn_id === 0;
      lastPlayedTurnRef.current = turn_id;

      // New agent turn: finalize the previous growing caption (not for greeting).
      if (!isGreeting && growingTurnIdRef.current !== turn_id) {
        if (growingTextRef.current.length > 0) {
          const prevText = growingTextRef.current;
          setTranscript((prev) => [
            ...prev,
            { role: "agent", text: prevText, kind: "text" },
          ]);
        }
        growingTextRef.current = "";
        growingTurnIdRef.current = turn_id;
        setGrowingText("");
      }

      if (buffer === null) {
        // Decode failed → show this chunk's text as a fallback and continue.
        if (text && !isGreeting) {
          const sep = growingTextRef.current.length > 0 ? " " : "";
          growingTextRef.current += sep + text.trim();
          setGrowingText(growingTextRef.current);
        }
        continue;
      }

      const startAt = Math.max(
        ctx.currentTime + LOOKAHEAD_S,
        nextStartTimeRef.current,
      );
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(ctx.destination);
      activeSourcesRef.current.add(src);
      isPlayingRef.current = true;

      const delayMs = Math.max(0, (startAt - ctx.currentTime) * 1000);
      // Reveal the caption aligned to when this chunk actually starts.
      if (text && !isGreeting) {
        const dur = duration_ms > 0 ? duration_ms : Math.round(buffer.duration * 1000);
        const rt = setTimeout(() => revealWords(text, dur, turn_id), delayMs);
        revealTimersRef.current.push(rt);
      }
      // Flip to "speaking" once per turn, when its first chunk starts.
      if (turnSpeakingRef.current !== turn_id) {
        turnSpeakingRef.current = turn_id;
        const st = setTimeout(() => {
          if (currentTurnIdRef.current === turn_id || isGreeting) {
            setVoiceStatus("speaking");
            setStatusLabel("Speaking…");
          }
        }, delayMs);
        revealTimersRef.current.push(st);
      }

      src.onended = () => {
        activeSourcesRef.current.delete(src);
        if (activeSourcesRef.current.size === 0) maybeGoIdle();
      };
      src.start(startAt);
      nextStartTimeRef.current = startAt + buffer.duration;
    }
  }, [revealWords, maybeGoIdle]);

  // Decode an incoming chunk (in parallel) then try to schedule.
  const ingestChunk = useCallback(
    (seq: number, entry: AudioChunkEntry) => {
      audioQueueRef.current.set(seq, entry);
      const ctx = ensureCtx();
      if (!ctx) {
        entry.buffer = null; // no Web Audio → text fallback
        scheduleAvailable();
        return;
      }
      ctx
        .decodeAudioData(base64ToArrayBuffer(entry.audio))
        .then((buf) => {
          entry.buffer = buf;
        })
        .catch(() => {
          entry.buffer = null;
        })
        .finally(() => scheduleAvailable());
    },
    [ensureCtx, scheduleAvailable],
  );

  const stopAudio = useCallback(() => {
    activeSourcesRef.current.forEach((s) => {
      try {
        s.onended = null;
        s.stop();
      } catch {
        /* already stopped */
      }
    });
    activeSourcesRef.current.clear();
    nextStartTimeRef.current = 0;
    turnSpeakingRef.current = -1;
    audioQueueRef.current.clear();
    failedSeqsRef.current.clear();
    nextSeqRef.current = 0;
    isPlayingRef.current = false;
  }, []);

  const stopAll = useCallback(() => {
    if (typeof window !== "undefined") window.speechSynthesis.cancel();
    stopAudio();
    clearRevealTimers();
  }, [stopAudio, clearRevealTimers]);

  const resetAudioForNewTurn = useCallback(() => {
    stopAudio();
    nextSeqRef.current = 0;
    audioDoneRef.current = false;
  }, [stopAudio]);

  // Close the AudioContext when the panel unmounts.
  useEffect(() => {
    return () => {
      try {
        audioCtxRef.current?.close();
      } catch {
        /* already closed */
      }
      audioCtxRef.current = null;
    };
  }, []);

  // ── No-audio → Journey TTS auto-fallback ───────────────────────────────────
  const clearNoAudioTimer = useCallback(() => {
    if (noAudioTimerRef.current) {
      clearTimeout(noAudioTimerRef.current);
      noAudioTimerRef.current = null;
    }
  }, []);

  // Switch the whole call to the Journey TTS pipeline (reliable demo audio).
  const fallbackToTts = useCallback(
    (reason: string) => {
      if (fellBackRef.current || !liveModeRef.current) return;
      fellBackRef.current = true;
      reconnectAttemptsRef.current = 0; // give the TTS connection fresh retries
      clearNoAudioTimer();
      captureHandleRef.current?.stop();
      captureHandleRef.current = null;
      setIsLiveMic(false);
      setMicLevel(0);
      liveModeRef.current = false;
      setLiveMode(false);
      setDiag((d) => ({ ...d, fellBack: true, micStatus: "off" }));
      onDebugLine(
        "error",
        `[Fallback] Gemini Live produced no audio. Using Journey TTS mode. (${reason})`,
      );
      setTranscript((prev) => [
        ...prev,
        {
          role: "agent",
          text: "Live voice didn't respond — switched to standard voice (Journey TTS). Please ask your question again.",
          kind: "error",
        },
      ]);
      setStatusLabel("Switched to standard voice");
      setVoiceStatus("idle");
      // Force a reconnect onto /ws/voice/ (the effect reads liveModeRef).
      setReconnectKey((k) => k + 1);
    },
    [clearNoAudioTimer, onDebugLine],
  );

  // Arm the no-audio watchdog after a turn is submitted. Cleared on first audio.
  // First Live turn gets a longer grace window (cold start) than later turns.
  const armNoAudioTimer = useCallback(() => {
    if (!liveModeRef.current || fellBackRef.current) return;
    clearNoAudioTimer();
    gotAudioThisTurnRef.current = false;
    turnStartRef.current = performance.now();
    turnCountRef.current += 1;
    const timeoutMs =
      turnCountRef.current <= 1 ? FIRST_TURN_TIMEOUT_MS : TURN_TIMEOUT_MS;
    onDebugLine(
      "info",
      `No-audio watchdog armed: ${timeoutMs / 1000}s (turn ${turnCountRef.current})`,
    );
    noAudioTimerRef.current = setTimeout(() => {
      if (!gotAudioThisTurnRef.current) {
        setTranscript((prev) => [
          ...prev,
          {
            role: "agent",
            text: "No audio received from Live model. Falling back to Journey TTS.",
            kind: "error",
          },
        ]);
        fallbackToTts(`no audio in ${timeoutMs / 1000}s`);
      }
    }, timeoutMs);
  }, [clearNoAudioTimer, fallbackToTts, onDebugLine]);

  useEffect(() => {
    liveModeRef.current = liveMode;
  }, [liveMode]);

  // ── Live mic control ─────────────────────────────────────────────────────
  const startLiveMic = useCallback(async () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    if (captureHandleRef.current) return; // already running

    // Finalize previous agent turn — new user turn begins
    currentTurnIdRef.current += 1;
    finalizeGrowingText();
    clearRevealTimers();
    stopAudio();
    resetAudioForNewTurn();

    setIsLiveMic(true);
    setVoiceStatus("listening");
    setStatusLabel("Listening…");
    onDebugLine("info", `Live mic started — turn=${currentTurnIdRef.current}`);

    try {
      captureHandleRef.current = await startAudioCapture(
        wsRef.current,
        (level) => setMicLevel(level),
        (info) => onDebugLine("info", `[Audio] ${info}`),
        (count) => setDiag((d) => ({ ...d, chunksSent: count })),
      );
      setDiag((d) => ({ ...d, micStatus: "capturing" }));
      onDebugLine("info", "Mic permission granted — capture started");
    } catch (err: any) {
      setIsLiveMic(false);
      setVoiceStatus("error");
      setDiag((d) => ({
        ...d,
        micStatus: "denied",
        lastError: `Mic: ${err?.message ?? err}`,
      }));
      onDebugLine(
        "error",
        `Mic permission denied / error: ${err?.message ?? err}`,
      );
    }
  }, [
    finalizeGrowingText,
    clearRevealTimers,
    stopAudio,
    resetAudioForNewTurn,
    onDebugLine,
  ]);

  const stopLiveMic = useCallback(() => {
    // Tell the backend the mic was released so VAD finalizes the turn and the
    // model replies immediately (we won't be streaming trailing silence).
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "end_audio_turn" }));
    }
    if (captureHandleRef.current) {
      captureHandleRef.current.stop();
      captureHandleRef.current = null;
    }
    setIsLiveMic(false);
    setMicLevel(0);
    setDiag((d) => ({ ...d, micStatus: "granted" }));
    setVoiceStatus("thinking");
    setStatusLabel("Thinking…");
    onDebugLine("info", "Live mic stopped — waiting for response");
    armNoAudioTimer(); // 5s watchdog → fall back to Journey TTS if silent
  }, [onDebugLine, armNoAudioTimer]);

  // ── Browser speechSynthesis (TTS mode) fallback ──────────────────────────
  const hasSR =
    typeof window !== "undefined" &&
    !!(
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition
    );

  useEffect(() => {
    isMutedRef.current = isMuted;
  }, [isMuted]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const load = () => {
      voicesRef.current = window.speechSynthesis.getVoices();
    };
    load();
    window.speechSynthesis.addEventListener("voiceschanged", load);
    return () =>
      window.speechSynthesis.removeEventListener("voiceschanged", load);
  }, []);

  // Auto-scroll transcript
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript, growingText]);

  const addEntry = useCallback((entry: TranscriptEntry) => {
    setTranscript((prev) => [...prev, entry]);
  }, []);

  // ── WebSocket event handler ──────────────────────────────────────────────
  const onEventRef = useRef<(ev: Record<string, any>) => void>(null!);
  onEventRef.current = (ev) => {
    switch (ev.type) {
      case "status": {
        const st = ev.state as VoiceStatus;
        // In TTS mode the FRONTEND owns "speaking"/"idle" — they reflect real
        // audio playback (set in playNextChunk), not the backend's optimistic
        // timing. Honor thinking / tool_running / draft_ready / listening / error.
        if (!liveMode && (st === "speaking" || st === "idle")) break;
        setVoiceStatus(st);
        setStatusLabel(ev.label ?? "");
        break;
      }

      case "sentence": {
        // Greeting: render ONCE per panel as a static intro line, and remember
        // whether to play THIS connection's greeting audio (de-dupes the repeat
        // from StrictMode double-mount / silent reconnects).
        if (ev.greeting) {
          if (greetingShownRef.current) {
            acceptGreetingAudioRef.current = false; // a duplicate greeting — drop its audio
            onDebugLine("info", "greeting suppressed (already shown)");
          } else {
            greetingShownRef.current = true;
            acceptGreetingAudioRef.current = true;
            addEntry({ role: "agent", text: ev.text, kind: "text" });
            onDebugLine("info", "[Voice] greeting shown (once)");
          }
          break;
        }

        if (liveMode) {
          // Live: captions come from sentence events (audio carries no text).
          if (isMutedRef.current) {
            addEntry({ role: "agent", text: ev.text, kind: "text" });
          } else {
            const sep = growingTextRef.current.length > 0 ? " " : "";
            growingTextRef.current = growingTextRef.current + sep + ev.text;
            setGrowingText(growingTextRef.current);
          }
        } else if (isMutedRef.current) {
          // TTS + muted: no audio will play, so show the text directly.
          addEntry({ role: "agent", text: ev.text, kind: "text" });
        }
        // TTS + not muted: do NOT render here. The visible caption is revealed
        // word-by-word from audio_chunk playback (avoids duplicate text).
        onDebugLine("info", `Sentence: ${String(ev.text).slice(0, 60)}`);
        break;
      }

      case "audio_chunk": {
        const chunkTurnId: number = ev.turn_id ?? 0;
        const seq: number = ev.seq ?? 0;

        // Drop the audio of a duplicate greeting (turn 0 from a repeat connection).
        if (chunkTurnId === 0 && !acceptGreetingAudioRef.current) {
          onDebugLine("info", `greeting audio suppressed (dup) seq=${seq}`);
          break;
        }

        // Audio arrived → the session genuinely works.
        gotAudioThisTurnRef.current = true;
        reconnectAttemptsRef.current = 0; // healthy: allow future silent reconnects
        clearNoAudioTimer();
        {
          const tfa = turnStartRef.current
            ? (performance.now() - turnStartRef.current) / 1000
            : null;
          setDiag((d) => ({
            ...d,
            audioChunksRecv: d.audioChunksRecv + 1,
            timeToFirstAudio:
              d.audioChunksRecv === 0 && tfa !== null
                ? Math.round(tfa * 100) / 100
                : d.timeToFirstAudio,
          }));
        }
        // Greeting audio (turn 0) plays at panel open while currentTurnIdRef is
        // still 0; otherwise discard chunks from interrupted/old turns.
        if (chunkTurnId !== currentTurnIdRef.current) {
          onDebugLine(
            "info",
            `audio_chunk seq=${seq} turn=${chunkTurnId} discarded (current=${currentTurnIdRef.current})`,
          );
          break;
        }
        onDebugLine(
          "info",
          `audio_chunk seq=${seq} turn=${chunkTurnId} ${ev.duration_ms ?? "?"}ms`,
        );
        if (!isMutedRef.current) {
          ingestChunk(seq, {
            audio: ev.audio ?? "",
            text: ev.text ?? "",
            duration_ms: ev.duration_ms ?? 0,
            turn_id: chunkTurnId,
          });
        }
        break;
      }

      case "audio_done":
        onDebugLine("info", `audio_done turn=${ev.turn_id ?? "?"}`);
        // Mark end-of-turn audio. If nothing is scheduled/decoding, go idle now;
        // otherwise the last source's onended → maybeGoIdle flips to idle.
        audioDoneRef.current = true;
        if (
          activeSourcesRef.current.size === 0 &&
          audioQueueRef.current.size === 0
        ) {
          audioDoneRef.current = false;
          finalizeGrowingText();
          if (!liveMode) {
            setVoiceStatus("idle");
            setStatusLabel("Ready");
          }
        }
        break;

      case "tts_error": {
        const errTurnId: number = ev.turn_id ?? currentTurnIdRef.current;
        const errSeq: number = typeof ev.seq === "number" ? ev.seq : -1;
        // Ignore late errors from an interrupted/old turn.
        if (errTurnId !== currentTurnIdRef.current) {
          onDebugLine(
            "info",
            `tts_error seq=${errSeq} turn=${errTurnId} discarded`,
          );
          break;
        }
        // Mark this seq failed so playNextChunk skips it instead of stalling.
        if (errSeq >= 0) failedSeqsRef.current.add(errSeq);
        const errText: string = ev.text ?? "";
        if (errText && !isMutedRef.current) {
          const sep = growingTextRef.current.length > 0 ? " " : "";
          growingTextRef.current += sep + errText.trim();
          setGrowingText(growingTextRef.current);
        } else if (errText) {
          addEntry({ role: "agent", text: errText.trim(), kind: "text" });
        }
        // Unblock the scheduler if it was waiting on this seq.
        if (!isMutedRef.current) scheduleAvailable();
        onDebugLine(
          "error",
          `[TTS] seq=${errSeq}: ${ev.message ?? "TTS failed"}`,
        );
        break;
      }

      case "draft_ready":
        clearNoAudioTimer();
        setDraft({ text: ev.draft, clauseIds: ev.clause_ids ?? [] });
        addEntry({ role: "agent", text: ev.draft, kind: "draft" });
        onDebugLine("agent", `draft_ready — ${String(ev.draft).length} chars`);
        break;

      case "debug":
        onDebugLine("tool", ev.log);
        break;

      case "tool_result":
        onDebugLine("tool", `tool_result: ${ev.tool}`);
        break;

      case "error":
        setDiag((d) => ({ ...d, lastError: String(ev.message ?? "") }));
        onDebugLine("error", `Voice: ${ev.message}`);
        // In Live mode a backend error means no audio is coming → fall back.
        if (liveModeRef.current && !fellBackRef.current) {
          fallbackToTts("Live backend error");
        } else {
          addEntry({ role: "agent", text: ev.message, kind: "error" });
          setVoiceStatus("error");
        }
        break;
    }
  };

  // Set active clause when opened from a risk card
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!initialClauseId) return;
    // The dashboard already set + awaited the active clause before opening this
    // panel; this re-POST is a defensive backstop and confirms it's loaded.
    setActiveClause(sessionId, initialClauseId)
      .then(() =>
        onDebugLine("info", `[Voice] active clause loaded: ${initialClauseId}`),
      )
      .catch(() => onDebugLine("error", "Failed to set active clause"));
  }, []);

  // WebSocket lifecycle
  useEffect(() => {
    const mode = liveMode;
    // De-dupe the connecting log across React StrictMode's double-invoke (dev):
    // same reconnectKey+mode → log once. A real reconnect changes the key.
    const connectKey = `${reconnectKey}:${mode}`;
    if (connectLogKeyRef.current !== connectKey) {
      connectLogKeyRef.current = connectKey;
      onDebugLine(
        "info",
        `WS connecting — ${mode ? "Live (/ws/live/)" : "TTS (/ws/voice/)"}…`,
      );
    }
    setWsState("connecting");

    const ws = buildWs(
      getWsUrl(sessionId, mode),
      () => {
        setWsState("open");
        setStatusLabel("Connected");
        // NOTE: do NOT reset the reconnect counter here. A session that opens
        // then dies immediately would otherwise loop forever. The counter is
        // reset only when real audio arrives (proof the session works).
        setDiag((d) => ({ ...d, chunksSent: 0, audioChunksRecv: 0 }));
        onDebugLine("info", "WS opened");
      },
      (e: MessageEvent) => {
        try {
          onEventRef.current(JSON.parse(e.data));
        } catch {
          onDebugLine("error", "Malformed WS message");
        }
      },
      (ev?: CloseEvent) => {
        const code = ev?.code ?? 0;
        const reason = ev?.reason ?? "";
        setIsListening(false);
        setIsLiveMic(false);
        captureHandleRef.current?.stop();
        captureHandleRef.current = null;
        setDiag((d) => ({
          ...d,
          lastCloseCode: code,
          lastCloseReason: reason,
          micStatus: "off",
        }));
        onDebugLine(
          "info",
          `WS closed code=${code} reason=${reason || "(none)"}`,
        );

        if (endedByUserRef.current) {
          setWsState("closed"); // user hung up → "Call ended"
          return;
        }
        if (reconnectAttemptsRef.current < MAX_SILENT_RECONNECTS) {
          reconnectAttemptsRef.current += 1;
          onDebugLine(
            "info",
            `Unexpected close — silent reconnect ${reconnectAttemptsRef.current}/${MAX_SILENT_RECONNECTS}`,
          );
          setStatusLabel("Reconnecting…");
          setReconnectKey((k) => k + 1);
        } else if (liveModeRef.current && !fellBackRef.current) {
          // Live keeps dropping → switch to Journey TTS so the demo still talks.
          onDebugLine(
            "error",
            `Live unstable — ${MAX_SILENT_RECONNECTS} reconnects failed (last close code=${code})`,
          );
          fallbackToTts(
            `Live unstable (${MAX_SILENT_RECONNECTS} reconnects failed)`,
          );
        } else {
          setWsState("error"); // give up → manual reconnect + reason
          onDebugLine(
            "error",
            `Reconnect failed after ${MAX_SILENT_RECONNECTS} attempts (last close code=${code})`,
          );
        }
      },
      () => {
        setDiag((d) => ({ ...d, lastError: "WebSocket connection error" }));
        onDebugLine("error", "WS error");
      },
    );
    wsRef.current = ws;

    return () => {
      clearNoAudioTimer();
      captureHandleRef.current?.stop();
      captureHandleRef.current = null;
      stopAll();
      srRef.current?.stop();
      ws.onclose = null;
      ws.onerror = null;
      ws.close();
    };
  }, [sessionId, reconnectKey, liveMode]);

  const reconnect = useCallback(() => {
    currentTurnIdRef.current = 0;
    growingTextRef.current = "";
    growingTurnIdRef.current = -1;
    setGrowingText(null);
    setTranscript([]);
    setDraft(null);
    setVoiceStatus("idle");
    setIsLiveMic(false);
    setMicLevel(0);
    endedByUserRef.current = false;
    reconnectAttemptsRef.current = 0;
    turnCountRef.current = 0;
    greetingShownRef.current = false;
    acceptGreetingAudioRef.current = false;
    audioDoneRef.current = false;
    clearNoAudioTimer();
    clearRevealTimers();
    resetAudioForNewTurn();
    captureHandleRef.current?.stop();
    captureHandleRef.current = null;
    setDiag((d) => ({ ...INITIAL_DIAG, fellBack: d.fellBack }));
    setReconnectKey((k) => k + 1);
  }, [clearRevealTimers, resetAudioForNewTurn, clearNoAudioTimer]);

  const sendMessage = useCallback(
    (text: string, type: "transcript" | "text_input") => {
      if (wsRef.current?.readyState !== WebSocket.OPEN || !text.trim()) return;
      currentTurnIdRef.current += 1;
      finalizeGrowingText();
      clearRevealTimers();
      stopAll();
      resetAudioForNewTurn();
      addEntry({ role: "user", text, kind: "text" });
      wsRef.current.send(JSON.stringify({ type, text }));
      onDebugLine(
        "info",
        `Sent (${type}) turn=${currentTurnIdRef.current}: ${text}`,
      );
      armNoAudioTimer();
    },
    [
      stopAll,
      resetAudioForNewTurn,
      addEntry,
      finalizeGrowingText,
      clearRevealTimers,
      onDebugLine,
      armNoAudioTimer,
    ],
  );

  const startListening = useCallback(() => {
    if (!hasSR || liveMode) return;
    // Guard against duplicate starts (double-click / re-render).
    if (isListening || srRef.current) {
      onDebugLine("info", "[Speech] already listening (duplicate start ignored)");
      return;
    }
    // Stop the agent's own audio FIRST so the browser STT isn't confused by it.
    stopAll();

    const SR =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition;
    const sr = new SR();
    sr.continuous = false;
    sr.interimResults = true; // stream partial words while the user speaks
    sr.maxAlternatives = 1;
    sr.lang = micLang; // "en-US" or "ar-SA" depending on the Mic Language toggle

    setMicLangUnsupported(false);
    setInterimText("");
    setMicPhase("listening");
    setMicDiag((d) => ({ ...d, language: micLang, status: "starting", lastError: "" }));

    sr.onstart = () => {
      setMicDiag((d) => ({ ...d, status: "listening", permission: "granted" }));
      onDebugLine("info", "[Speech] permission=granted");
      onDebugLine("info", "[Speech] started");
    };
    sr.onspeechstart = () => {
      setMicPhase("heard");
      setMicDiag((d) => ({ ...d, status: "speech detected" }));
    };
    sr.onresult = (e: any) => {
      let interim = "";
      let final = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const tr: string = e.results[i][0].transcript;
        if (e.results[i].isFinal) final += tr;
        else interim += tr;
      }
      if (interim) {
        setInterimText(interim);
        setMicPhase("heard");
        setMicDiag((d) => ({ ...d, lastInterim: interim }));
        onDebugLine("info", `[Speech] interim: ${interim}`);
      }
      if (final.trim()) {
        const text = final.trim();
        setInterimText("");
        setMicPhase("processing");
        setIsListening(false);
        setVoiceStatus("thinking");
        setMicDiag((d) => ({ ...d, lastFinal: text, status: "final" }));
        onDebugLine("info", `[Speech] final: ${text}`);
        sendMessage(text, "transcript");
      }
    };
    sr.onnomatch = () => {
      setMicPhase("no-speech");
      onDebugLine("error", "[Speech] error=no-match");
    };
    sr.onerror = (e: any) => {
      const err = String(e.error || "unknown");
      setIsListening(false);
      setInterimText("");
      setMicDiag((d) => ({ ...d, lastError: err, status: `error:${err}` }));
      onDebugLine("error", `[Speech] error=${err}`);
      if (err === "no-speech") {
        setMicPhase("no-speech");
        setVoiceStatus("idle");
        setStatusLabel("Ready");
        addEntry({
          role: "agent",
          text: "I didn’t catch that. Please try again or type your question.",
          kind: "error",
        });
      } else if (err === "not-allowed" || err === "service-not-allowed") {
        setMicPhase("error");
        setVoiceStatus("idle");
        setMicDiag((d) => ({ ...d, permission: "denied" }));
        addEntry({
          role: "agent",
          text: "Microphone permission is blocked. Please allow the mic, or type your question.",
          kind: "error",
        });
      } else if (micLang !== "en-US" && /language/i.test(err)) {
        setMicLangUnsupported(true);
        setMicPhase("error");
        setVoiceStatus("idle");
      } else {
        setMicPhase("error");
        setVoiceStatus("idle");
      }
    };
    sr.onend = () => {
      setIsListening(false);
      srRef.current = null;
      setMicDiag((d) => ({ ...d, status: "ended" }));
      onDebugLine("info", "[Speech] ended");
      // Keep a terminal phase (processing/no-speech/error) visible; else reset.
      setMicPhase((p) =>
        p === "processing" || p === "no-speech" || p === "error" ? p : "ready",
      );
    };

    srRef.current = sr;
    try {
      sr.start();
    } catch (err: any) {
      srRef.current = null;
      setIsListening(false);
      setMicPhase("error");
      onDebugLine("error", `[Speech] start failed: ${err?.message ?? err}`);
      return;
    }
    setIsListening(true);
    setVoiceStatus("listening");
    onDebugLine("info", `[Speech] recognition language=${micLang}`);
  }, [
    hasSR,
    liveMode,
    isListening,
    micLang,
    sendMessage,
    stopAll,
    onDebugLine,
    addEntry,
  ]);

  const stopListening = useCallback(() => {
    srRef.current?.stop();
    srRef.current = null;
    setIsListening(false);
    setInterimText("");
    setMicPhase("ready");
    setVoiceStatus("idle");
  }, []);

  const handleEndCall = useCallback(() => {
    endedByUserRef.current = true;
    clearNoAudioTimer();
    finalizeGrowingText();
    clearRevealTimers();
    captureHandleRef.current?.stop();
    captureHandleRef.current = null;
    stopAll();
    srRef.current?.stop();
    wsRef.current?.close();
    onClose();
  }, [
    finalizeGrowingText,
    clearRevealTimers,
    stopAll,
    clearNoAudioTimer,
    onClose,
  ]);

  const handleTextSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!textInput.trim()) return;
      sendMessage(textInput.trim(), "text_input");
      setTextInput("");
      setVoiceStatus("thinking");
    },
    [textInput, sendMessage],
  );

  const handleCopyDraft = useCallback(async () => {
    if (!draft) return;
    await navigator.clipboard.writeText(draft.text);
    setDraftCopied(true);
    onDebugLine("info", "Draft copied to clipboard");
    setTimeout(() => setDraftCopied(false), 2000);
  }, [draft, onDebugLine]);

  const canInteract =
    wsState === "open" &&
    voiceStatus !== "thinking" &&
    voiceStatus !== "tool_running";

  const isMicActive = liveMode ? isLiveMic : isListening;
  const handleMicClick = liveMode
    ? () => {
        isMicActive ? stopLiveMic() : void startLiveMic();
      }
    : () => {
        isMicActive ? stopListening() : startListening();
      };
  const canShowMic = liveMode || hasSR;

  // Header context: multiple selected clauses → "N selected clauses";
  // otherwise the single focused clause title (if any).
  const activeRisk = initialClauseId
    ? riskReport.risks.find((r) => r.id === initialClauseId)
    : null;
  const headerContext =
    selectedClauseIds.length >= 2
      ? `${selectedClauseIds.length} selected clauses`
      : activeRisk
        ? activeRisk.title
        : null;
  return (
    <div className="flex flex-col h-full bg-white relative animate-in slide-in-from-right duration-500 ">
      <div className="p-4 px-6 border-b border-slate-100 flex items-center justify-between ">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xs bg-gradient-to-br from-[#67a1ff] via-[#7aadff] to-cyan-500 flex items-center justify-center text-white shadow-lg shadow-blue-200">
            <LucideIcon name="mic" size={20} />
          </div>
          <div>
            <h2 className="text-base font-black text-[#2e2e2e] tracking-tight">
              Legal Assistant
            </h2>{" "}
            <p
              className="text-[10px] text-slate-400 font-bold uppercase tracking-widest truncate max-w-[200px]"
              title={headerContext ?? undefined}
            >
              {headerContext ?? "Neural Audio Session"}
            </p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 hover:bg-slate-50 rounded-xl transition-all"
        >
          <LucideIcon name="x" size={20} className="text-zinc-500" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-hide flex flex-col bg-white">
        <div className="py-2 pt-0  flex flex-col items-center justify-center bg-white">
          <div className="relative flex items-center justify-center w-36 h-36">
            {(voiceStatus === "listening" || voiceStatus === "speaking") && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div
                  className="absolute rounded-full border-2 border-[#67a1ff]/20 bg-[#67a1ff]/5 transition-all duration-150 ease-out"
                  style={{
                    width: `${140 + micLevel * 200}px`,
                    height: `${140 + micLevel * 200}px`,
                    opacity: 0.3 + micLevel,
                  }}
                />
                <div
                  className="absolute rounded-full border-2 border-[#67a1ff]/40 transition-all duration-200 ease-out"
                  style={{
                    width: `${100 + micLevel * 120}px`,
                    height: `${100 + micLevel * 120}px`,
                  }}
                />
                <div
                  className="absolute rounded-full bg-[#67a1ff]/10 animate-ping"
                  style={{
                    width: `${80 + micLevel * 50}px`,
                    height: `${80 + micLevel * 50}px`,
                  }}
                />
              </div>
            )}

            <div
              className={`relative w-28 h-28 rounded-full flex items-center justify-center z-20 transition-all duration-500
        ${
          voiceStatus === "listening"
            ? "bg-[#67a1ff] text-white shadow-[0_0_50px_rgba(103,161,255,0.4)] scale-110"
            : "bg-white border-2 border-slate-100 text-slate-400 shadow-xl shadow-slate-100"
        }
      `}
            >
              <LucideIcon
                name={STATUS_ICON[voiceStatus]}
                size={34}
                className={voiceStatus === "thinking" ? "animate-spin" : ""}
              />

              {voiceStatus === "thinking" && (
                <div className="absolute inset-[-6px] rounded-full border-2 border-[#67a1ff]/20 border-t-[#67a1ff] animate-spin" />
              )}
            </div>
          </div>

          <div className="mt-0 flex flex-col items-center gap-1">
            <h3
              className={`text-base font-bold tracking-tight transition-colors duration-300 ${
                voiceStatus === "listening" ? "text-red-500" : "text-[#67a1ff]"
              }`}
            >
              {statusLabel}
            </h3>
            {wsState === "closed" && endedByUserRef.current && (
              <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest mt-1">
                Session Ended
              </span>
            )}
          </div>
        </div>
        <div className="flex-1 p-8 py-4 space-y-4">
          {transcript.length === 0 && !growingText && (
            <div className="text-center py-10 opacity-30">
              <LucideIcon
                name="message-square"
                size={32}
                className="mx-auto mb-4"
              />
              <p className="text-xs font-bold uppercase tracking-widest leading-relaxed">
                Start talking to analyze
                <br />
                this document together
              </p>
            </div>
          )}

          {transcript.map((entry, i) => (
            <div
              key={i}
              className={`flex flex-col ${entry.role === "user" ? "items-end" : "items-start"}`}
            >
              <span className="text-gray-500 mb-1 text-xs">
                {entry.role === "user" ? "You" : "Agent"}
              </span>
              {entry.kind === "draft" ? (
                <div className="w-full bg-blue-50/50 border border-blue-100 p-4 rounded-2xl mb-2">
                  <div className="flex justify-between mb-2">
                    <span className="text-[10px] font-black text-blue-500 uppercase">
                      AI Draft Ready
                    </span>
                    <button
                      onClick={handleCopyDraft}
                      className="text-xs font-bold text-blue-600"
                    >
                      Copy
                    </button>
                  </div>
                  <pre dir="auto" className="text-xs text-slate-600 whitespace-pre-wrap">
                    {entry.text}
                  </pre>
                </div>
              ) : (
                <div
                  dir="auto"
                  className={`max-w-[85%] p-5 rounded-2xl text-sm leading-relaxed font-medium  transition-all ${
                    entry.role === "user"
                      ? "bg-[#7aadff] text-white rounded-tr-none"
                      : "bg-slate-50 text-[#4f4f4f] border border-[#eee] rounded-tl-none"
                  }`}
                >
                  {entry.text}
                </div>
              )}
            </div>
          ))}

          {growingText !== null && (
            <div className="flex flex-col items-start animate-pulse">
              <div dir="auto" className="max-w-[85%] p-5 rounded-2xl rounded-tl-none bg-[#67a1ff]/10 text-[#67a1ff] font-medium text-sm border border-[#67a1ff]/20">
                {growingText || "..."}
              </div>
            </div>
          )}
          <div ref={transcriptEndRef} />
        </div>
      </div>

      <div className="p-6 bg-white border-t border-slate-50 space-y-4">
        {!liveMode && hasSR && (
          <div className="flex flex-col items-center gap-1.5">
            <div className="flex items-center gap-2">
              <span className="text-[9px] font-black uppercase tracking-widest text-slate-400">
                Mic Language
              </span>
              <div className="flex rounded-full bg-slate-100 p-0.5">
                {(["en-US", "ar-SA"] as MicLang[]).map((lng) => (
                  <button
                    key={lng}
                    type="button"
                    onClick={() => {
                      setMicLang(lng);
                      setMicLangUnsupported(false);
                      onDebugLine("info", `[Speech] recognition language=${lng}`);
                    }}
                    className={`px-3 py-1 text-[11px] font-bold rounded-full transition-all ${
                      micLang === lng
                        ? "bg-white text-[#67a1ff] shadow-sm"
                        : "text-slate-400 hover:text-slate-600"
                    }`}
                  >
                    {lng === "en-US" ? "English" : "Arabic"}
                  </button>
                ))}
              </div>
            </div>
            {micLang !== "en-US" && micLangUnsupported && (
              <p className="text-[10px] text-amber-600 text-center max-w-[260px] leading-snug">
                Arabic voice input may not be supported in this browser. Please
                type Arabic instead.
              </p>
            )}

            {/* Live mic phase + interim transcript preview */}
            <div className="flex flex-col items-center gap-0.5 min-h-[16px]">
              <span
                className={`text-[10px] font-bold ${
                  micPhase === "error" || micPhase === "no-speech"
                    ? "text-amber-600"
                    : micPhase === "listening" || micPhase === "heard"
                      ? "text-[#67a1ff]"
                      : "text-slate-400"
                }`}
              >
                {MIC_PHASE_LABEL[micPhase]}
              </span>
              {interimText && (
                <span
                  dir="auto"
                  className="text-[11px] text-slate-500 italic text-center max-w-[280px] truncate"
                >
                  Heard: {interimText}…
                </span>
              )}
            </div>

            {/* Mic diagnostics (debug) */}
            <button
              type="button"
              onClick={() => setShowMicDiag((v) => !v)}
              className="text-[9px] text-slate-300 hover:text-slate-500 uppercase tracking-widest font-bold"
            >
              {showMicDiag ? "hide mic diagnostics" : "mic diagnostics"}
            </button>
            {showMicDiag && (
              <div className="w-full max-w-[300px] bg-slate-50 rounded-lg p-2 text-[10px] text-slate-500 font-mono space-y-0.5">
                <div>language: {micDiag.language}</div>
                <div>permission: {micDiag.permission}</div>
                <div>status: {micDiag.status}</div>
                <div className="truncate">last interim: {micDiag.lastInterim || "—"}</div>
                <div className="truncate">last final: {micDiag.lastFinal || "—"}</div>
                <div>last error: {micDiag.lastError || "—"}</div>
              </div>
            )}
          </div>
        )}
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={handleMicClick}
            className={`w-12 h-12 !rounded-full flex items-center justify-center  transition-all ${isMicActive ? "bg-[#67a1ff] text-white  shadow-blue-200" : "bg-slate-100 text-slate-400 hover:bg-slate-100"}`}
          >
            <LucideIcon name={isMicActive ? "mic" : "mic-off"} size={24} />
          </button>
          <button
            onClick={() => setIsMuted(!isMuted)}
            className={`w-12 h-12 !rounded-full  flex items-center justify-center transition-all ${!isMuted ? "bg-indigo-50 text-[#67a1ff]" : "bg-slate-50 text-slate-300"}`}
          >
            <LucideIcon name={isMuted ? "volume-x" : "volume-2"} size={24} />
          </button>
          <button
            onClick={handleEndCall}
            className="w-12 h-12 !rounded-full  flex items-center justify-center bg-red-500 text-white transition-all"
          >
            <LucideIcon name="phone-off" size={20} />
          </button>
        </div>

        <form onSubmit={handleTextSubmit} className="relative group">
          <input
            className="w-full bg-slate-50 border border-slate-200 rounded-2xl py-4 pl-6 pr-12 text-sm text-slate-700 outline-none focus:ring-4 focus:ring-[#67a1ff0a] focus:border-[#67a1ff50] transition-all"
            type="text"
            value={textInput}
            onChange={(e) => setTextInput(e.target.value)}
            placeholder={
              liveMode
                ? "Ask Gemini Live anything..."
                : hasSR
                  ? "Type or use the mic..."
                  : "Type your question (Mic unavailable)..."
            }
          />
          <button
            type="submit"
            disabled={!textInput.trim()}
            className="absolute right-2 top-2 p-2 !rounded-full text-[#67a1ff] hover:bg-[#67a1ff] hover:text-white transition-all disabled:opacity-20"
          >
            <LucideIcon name="send" size={20} />
          </button>
        </form>

        <div className="flex items-center justify-center gap-2 pt-2 opacity-40">
          <LucideIcon name="lock" size={12} />
          <span className="text-[9px] font-black uppercase tracking-widest">
            Privacy Protected AI Session
          </span>
        </div>
      </div>
    </div>
  );
}
