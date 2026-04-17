"use client";

import { useRef, useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";

type RecorderState = "idle" | "permission-denied" | "ready" | "recording" | "preview" | "done";

interface CameraRecorderProps {
  onClose: () => void;
}

const MAX_SECONDS = 10;

export function CameraRecorder({ onClose }: CameraRecorderProps) {
  const [recState, setRecState] = useState<RecorderState>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [videoURL, setVideoURL] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<"idle" | "uploading" | "done">("idle");

  const videoRef = useRef<HTMLVideoElement>(null);
  const previewRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Request camera + mic on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: true,
        });
        if (cancelled) { stream.getTracks().forEach(t => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(() => {});
        }
        setRecState("ready");
      } catch {
        if (!cancelled) setRecState("permission-denied");
      }
    })();
    return () => {
      cancelled = true;
      cleanup();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cleanup = () => {
    timerRef.current && clearInterval(timerRef.current);
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
  };

  const startRecording = useCallback(() => {
    if (!streamRef.current) return;
    chunksRef.current = [];
    const mr = new MediaRecorder(streamRef.current, {
      mimeType: MediaRecorder.isTypeSupported("video/webm;codecs=vp9") ? "video/webm;codecs=vp9" : "video/webm",
    });
    mr.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data); };
    mr.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: "video/webm" });
      const url = URL.createObjectURL(blob);
      setVideoURL(url);
      setRecState("preview");
      setElapsed(0);
    };
    mr.start(100);
    recorderRef.current = mr;
    setElapsed(0);
    setRecState("recording");

    let sec = 0;
    timerRef.current = setInterval(() => {
      sec += 1;
      setElapsed(sec);
      if (sec >= MAX_SECONDS) stopRecording();
    }, 1000);
  }, []);

  const stopRecording = useCallback(() => {
    timerRef.current && clearInterval(timerRef.current);
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }, []);

  const retake = () => {
    if (videoURL) URL.revokeObjectURL(videoURL);
    setVideoURL(null);
    setElapsed(0);
    setUploadStatus("idle");
    setRecState("ready");
    // Re-attach stream to live preview
    if (videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
      videoRef.current.play().catch(() => {});
    }
  };

  const handleUpload = async () => {
    if (!videoURL) return;
    setUploadStatus("uploading");
    // INTEGRATION BOUNDARY: send the blob to your backend here.
    // const blob = chunksRef.current and POST to /api/v1/incidents/evidence
    await new Promise(r => setTimeout(r, 800)); // mock upload
    setUploadStatus("done");
    setRecState("done");
  };

  const handleClose = () => {
    cleanup();
    if (videoURL) URL.revokeObjectURL(videoURL);
    onClose();
  };

  const progress = (elapsed / MAX_SECONDS) * 100;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-[100] bg-black flex flex-col"
    >
      {/* ── Permission Denied ────────────────────────────── */}
      {recState === "permission-denied" && (
        <div className="flex-1 flex flex-col items-center justify-center gap-6 px-8 text-center">
          <span className="material-symbols-outlined text-5xl text-white/30">no_photography</span>
          <div>
            <p className="text-white font-['Space_Grotesk'] font-bold text-lg mb-2">Camera Access Required</p>
            <p className="text-white/40 text-sm font-['Manrope']">
              GigShield needs camera and microphone access to record incident evidence. Please allow access in your browser settings.
            </p>
          </div>
          <button onClick={handleClose} className="px-6 py-3 rounded-full bg-white/10 text-white font-bold font-['Space_Grotesk']">
            Close
          </button>
        </div>
      )}

      {/* ── Upload Done ──────────────────────────────────── */}
      {recState === "done" && (
        <div className="flex-1 flex flex-col items-center justify-center gap-6 px-8 text-center">
          <div className="w-20 h-20 rounded-full bg-[#4ade80]/10 border border-[#4ade80]/30 flex items-center justify-center">
            <span className="material-symbols-outlined text-[#4ade80] text-4xl" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
          </div>
          <div>
            <p className="text-white font-['Space_Grotesk'] font-bold text-xl mb-2">Evidence Uploaded</p>
            <p className="text-white/40 text-sm font-['Manrope']">Your incident video has been securely attached to your claim.</p>
          </div>
          <button onClick={handleClose} className="w-full max-w-xs py-4 rounded-full bg-[var(--color-rider-primary)] text-[#002635] font-['Space_Grotesk'] font-bold text-lg">
            Done
          </button>
        </div>
      )}

      {/* ── Camera + Record + Preview ────────────────────── */}
      {(recState === "idle" || recState === "ready" || recState === "recording" || recState === "preview") && (
        <>
          {/* Live viewfinder or static preview */}
          <div className="relative flex-1 overflow-hidden bg-black">
            {/* Live viewfinder (hidden during preview) */}
            <video
              ref={videoRef}
              className={`absolute inset-0 w-full h-full object-cover ${recState === "preview" ? "hidden" : ""}`}
              muted
              playsInline
              autoPlay
            />

            {/* Recorded preview */}
            {recState === "preview" && videoURL && (
              <video
                ref={previewRef}
                src={videoURL}
                className="absolute inset-0 w-full h-full object-cover"
                controls
                playsInline
                autoPlay
                loop
              />
            )}

            {/* Top bar */}
            <div className="absolute top-0 left-0 right-0 flex items-center justify-between px-5 pt-safe-top pt-4 z-10">
              <button
                onClick={handleClose}
                className="w-10 h-10 rounded-full bg-black/50 backdrop-blur flex items-center justify-center"
              >
                <span className="material-symbols-outlined text-white text-xl">close</span>
              </button>

              {recState === "recording" && (
                <div className="flex items-center gap-2 bg-black/60 backdrop-blur px-3 py-1.5 rounded-full">
                  <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                  <span className="text-white text-xs font-bold font-['Space_Grotesk'] tabular-nums">
                    {elapsed}s / {MAX_SECONDS}s
                  </span>
                </div>
              )}

              {recState === "preview" && (
                <div className="bg-black/60 backdrop-blur px-3 py-1.5 rounded-full">
                  <span className="text-white/70 text-xs font-['Manrope']">Preview</span>
                </div>
              )}
            </div>

            {/* Recording progress bar */}
            {recState === "recording" && (
              <div className="absolute bottom-0 left-0 right-0 h-1 bg-white/10">
                <motion.div
                  className="h-full bg-red-500"
                  initial={{ width: "0%" }}
                  animate={{ width: `${progress}%` }}
                  transition={{ duration: 0.5, ease: "linear" }}
                />
              </div>
            )}
          </div>

          {/* ── Controls strip ──────────────────────────── */}
          <div className="bg-[#0a0e14] px-8 pt-6 pb-safe-bottom pb-8 flex items-center justify-center gap-10">

            {recState === "preview" ? (
              /* Preview mode: Retake + Upload */
              <>
                <button
                  onClick={retake}
                  className="flex flex-col items-center gap-1.5"
                >
                  <div className="w-12 h-12 rounded-full bg-white/10 flex items-center justify-center">
                    <span className="material-symbols-outlined text-white text-xl">replay</span>
                  </div>
                  <span className="text-xs text-white/60 font-['Manrope'] font-bold uppercase tracking-wide">Retake</span>
                </button>

                <motion.button
                  whileTap={{ scale: 0.94 }}
                  onClick={handleUpload}
                  disabled={uploadStatus === "uploading"}
                  className="w-20 h-20 rounded-full bg-[var(--color-rider-primary)] flex flex-col items-center justify-center shadow-[0_0_24px_rgba(84,199,252,0.4)] disabled:opacity-50"
                >
                  {uploadStatus === "uploading" ? (
                    <span className="material-symbols-outlined text-[#002635] text-2xl animate-spin">autorenew</span>
                  ) : (
                    <>
                      <span className="material-symbols-outlined text-[#002635] text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>upload</span>
                      <span className="text-[#002635] text-[9px] font-bold font-['Space_Grotesk'] mt-0.5">UPLOAD</span>
                    </>
                  )}
                </motion.button>

                <div className="w-12 h-12" /> {/* spacer */}
              </>
            ) : (
              /* Ready / Recording: single record button */
              <>
                <div className="w-10 h-10" /> {/* spacer */}

                {recState === "recording" ? (
                  <motion.button
                    whileTap={{ scale: 0.9 }}
                    onClick={stopRecording}
                    className="w-20 h-20 rounded-full bg-red-500 flex items-center justify-center shadow-[0_0_24px_rgba(239,68,68,0.4)]"
                  >
                    <span className="w-7 h-7 rounded-sm bg-white block" />
                  </motion.button>
                ) : (
                  <motion.button
                    whileTap={{ scale: 0.9 }}
                    onClick={startRecording}
                    disabled={recState !== "ready"}
                    className="w-20 h-20 rounded-full border-4 border-white/30 bg-transparent flex items-center justify-center disabled:opacity-30"
                  >
                    <span className="w-14 h-14 rounded-full bg-red-500 block shadow-[0_0_16px_rgba(239,68,68,0.5)]" />
                  </motion.button>
                )}

                <div className="w-10 h-10" /> {/* spacer */}
              </>
            )}
          </div>
        </>
      )}
    </motion.div>
  );
}
