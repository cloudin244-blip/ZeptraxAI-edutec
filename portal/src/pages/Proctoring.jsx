import { useCallback, useEffect, useRef, useState } from "react";
import { portal } from "../api.js";
import { Button, Card, ErrorText, Spinner } from "../components/ui.jsx";
import {
  ABSENT_CHECKS, CHECK_EVERY_MS, CROWD_CHECKS, EVENT_TEXT, PHONE_CHECKS,
  enterFullscreen, extraScreen, inspect, loadDetector, openCamera, snapshot, stopCamera,
} from "../proctor.js";

const MODEL_WAIT_MS = 45000; // on a very slow connection the student may start without AI detection (recorded)

export function ProctoringRules({ test }) {
  return (
    <ul className="list-disc space-y-1.5 pl-5 text-slate-300">
      <li>Your camera stays on for the whole test and the test runs in full screen.</li>
      <li>
        Leaving the test tab or window, leaving full screen, or not being visible on camera each count as a warning. At {test.warning_limit} warnings the
        test is submitted automatically and marked as malpractice.
      </li>
      <li>A mobile phone or another person on camera ends the test immediately and marks it as malpractice.</li>
      <li>Copying, pasting, right-clicking and keyboard shortcuts are disabled.</li>
      <li>The camera picture is checked on your own device. A snapshot is saved only when something unusual is detected, for ZeptraAI and your university to review.</li>
    </ul>
  );
}

function Check({ ok, busy, label, children }) {
  return (
    <div className="flex items-start gap-3">
      <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs ${ok ? "bg-green-500/20 text-green-300" : busy ? "" : "bg-red-500/20 text-red-300"}`}>
        {busy ? <Spinner small /> : ok ? "✓" : "!"}
      </span>
      <div className="text-sm">
        <p className="font-medium">{label}</p>
        {children && <div className="mt-0.5 text-muted">{children}</div>}
      </div>
    </div>
  );
}

// Camera, detection model and screen checks before the timer starts (or before resuming)
export function Precheck({ test, resuming, onReady }) {
  const [stream, setStream] = useState(null);
  const [cameraError, setCameraError] = useState("");
  const [model, setModel] = useState("loading");
  const [starting, setStarting] = useState(false);
  const detector = useRef(null);
  const video = useRef(null);
  const live = useRef(null);
  const handedOver = useRef(false);
  const extended = extraScreen();

  const askCamera = useCallback(async () => {
    setCameraError("");
    try {
      const s = await openCamera();
      live.current = s;
      setStream(s);
    } catch (e) {
      setCameraError(
        e.name === "NotAllowedError"
          ? "Camera permission is blocked. Click the camera icon in the address bar, choose Allow, then press Try again."
          : e.name === "NotFoundError"
            ? "No camera was found. Connect a webcam, then press Try again."
            : e.name === "NotReadableError"
              ? "Another app is using your camera. Close it, then press Try again."
              : e.message || "Couldn't start the camera."
      );
    }
  }, []);

  useEffect(() => {
    askCamera();
    const timeout = new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), MODEL_WAIT_MS));
    Promise.race([loadDetector(), timeout])
      .then((d) => {
        detector.current = d;
        setModel("ready");
      })
      .catch(() => setModel("failed"));
    return () => {
      if (!handedOver.current) stopCamera(live.current);
    };
  }, [askCamera]);

  useEffect(() => {
    if (video.current && stream) {
      video.current.srcObject = stream;
      video.current.play().catch(() => {});
    }
  }, [stream]);

  const start = async () => {
    setStarting(true);
    const fullscreen = await enterFullscreen();
    handedOver.current = true;
    onReady({ stream, detector: detector.current, fullscreen });
  };

  const ready = stream && model !== "loading" && !extended;

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <Card className="p-6 sm:p-8">
        <p className="text-xs font-semibold uppercase tracking-wider text-accent">Camera and screen check</p>
        <h1 className="mt-1 text-xl font-semibold">{test.title}</h1>
        {resuming && <p className="mt-2 text-sm text-amber-300">Your test has already started and the timer is still running. Finish the check to continue.</p>}
        <div className="mt-6 grid gap-6 sm:grid-cols-[280px_1fr]">
          <div className="aspect-[4/3] overflow-hidden rounded-lg border border-border bg-black">
            {stream ? (
              <video ref={video} muted playsInline className="h-full w-full -scale-x-100 object-cover" />
            ) : (
              <div className="flex h-full items-center justify-center p-4 text-center text-xs text-muted">{cameraError ? "Camera off" : "Waiting for camera permission…"}</div>
            )}
          </div>
          <div className="space-y-4">
            <Check ok={!!stream} busy={!stream && !cameraError} label={stream ? "Camera is on" : cameraError ? "Camera needed" : "Allow camera access"}>
              {cameraError && (
                <>
                  <ErrorText>{cameraError}</ErrorText>
                  <Button variant="secondary" className="mt-2" onClick={askCamera}>
                    Try again
                  </Button>
                </>
              )}
              {stream && "Sit facing the camera in a well-lit place, alone, with your phone away."}
            </Check>
            <Check ok={model === "ready"} busy={model === "loading"} label={model === "ready" ? "Proctoring ready" : model === "loading" ? "Loading proctoring…" : "Proctoring couldn't load"}>
              {model === "loading" && "This can take up to a minute on a slow connection."}
              {model === "failed" && "You can still start; this is recorded for your university."}
            </Check>
            <Check ok={!extended} label={extended ? "Disconnect your extra monitor" : "One screen"}>
              {extended && "A second display is connected. Disconnect it, then reload this page."}
            </Check>
          </div>
        </div>
        <div className="mt-6 text-sm">
          <ProctoringRules test={test} />
        </div>
        <Button className="mt-6 w-full" disabled={!ready} loading={starting} onClick={start}>
          {resuming ? "Enter full screen and resume" : "Enter full screen and start the test"}
        </Button>
      </Card>
    </div>
  );
}

// Watches the student during the exam and reports to the server, which decides warnings and malpractice
export function useProctoring({ attemptId, proctor, enabled, initialWarnings, limit, done, onTerminated }) {
  const [warnings, setWarnings] = useState(initialWarnings || 0);
  const [notice, setNotice] = useState(null);
  const [needsFullscreen, setNeedsFullscreen] = useState(false);
  const [cameraLost, setCameraLost] = useState(false);
  const [stream, setStream] = useState(proctor?.stream || null);
  const video = useRef(null);
  const live = useRef(stream);
  const lost = useRef(false);
  const lastWarning = useRef(0);
  const watching = enabled && !!proctor;

  const report = useCallback(
    async (type, withSnapshot) => {
      if (done.current) return;
      const warning = type in EVENT_TEXT;
      if (warning) {
        // One action often fires several events (switching apps = blur + hidden): count it once
        const now = Date.now();
        if (now - lastWarning.current < 3000) return;
        lastWarning.current = now;
      }
      const body = { type };
      if (withSnapshot) body.snapshot = snapshot(video.current);
      try {
        const r = await portal.post(`/attempts/${attemptId}/event`, body, { retries: 3 });
        if (r.terminated) {
          done.current = true;
          onTerminated(r.result);
          return;
        }
        if (warning) {
          setWarnings(r.warnings);
          if (r.warning_limit) setNotice({ text: EVENT_TEXT[type], warnings: r.warnings, limit: r.warning_limit });
        }
      } catch {
        // event lost on a bad connection; later ones still count
      }
    },
    [attemptId, done, onTerminated]
  );

  // Leaving the test (recorded for every test; only counts towards malpractice when proctoring is on)
  useEffect(() => {
    let blurTimer;
    const onVisibility = () => document.visibilityState === "hidden" && report("tab_hidden");
    const onBlur = () => {
      blurTimer = setTimeout(() => {
        if (document.visibilityState === "visible" && !document.hasFocus()) report("window_blur");
      }, 400);
    };
    const onFocus = () => clearTimeout(blurTimer);
    document.addEventListener("visibilitychange", onVisibility);
    if (watching) {
      window.addEventListener("blur", onBlur);
      window.addEventListener("focus", onFocus);
    }
    return () => {
      clearTimeout(blurTimer);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
    };
  }, [report, watching]);

  // Full screen, blocked shortcuts, one-off notes for the server
  useEffect(() => {
    if (!watching) return;
    if (!proctor.detector) report("proctor_unavailable");
    if (!proctor.fullscreen) report("fullscreen_unavailable");
    const onFullscreen = () => {
      const inside = !!document.fullscreenElement;
      setNeedsFullscreen(!inside);
      if (!inside && !done.current) report("fullscreen_exit");
    };
    if (proctor.fullscreen) {
      document.addEventListener("fullscreenchange", onFullscreen);
      if (!document.fullscreenElement) setNeedsFullscreen(true);
    }
    const block = (e) => e.preventDefault();
    const blocked = ["contextmenu", "copy", "cut", "paste", "dragstart", "selectstart"];
    blocked.forEach((t) => document.addEventListener(t, block));
    const onKey = (e) => {
      const key = e.key?.toLowerCase();
      if (((e.ctrlKey || e.metaKey) && "acfijknopstuvwx".includes(key) && key.length === 1) || ["f12", "printscreen", "contextmenu"].includes(key)) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (key === "printscreen") navigator.clipboard?.writeText("").catch(() => {});
    };
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("keyup", onKey, true);
    return () => {
      document.removeEventListener("fullscreenchange", onFullscreen);
      blocked.forEach((t) => document.removeEventListener(t, block));
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("keyup", onKey, true);
    };
  }, [watching, proctor, report, done]);

  // Camera: show it, notice if it stops, release it when the exam ends
  useEffect(() => {
    if (!watching || !stream) return;
    live.current = stream;
    if (video.current) {
      video.current.srcObject = stream;
      video.current.play().catch(() => {});
    }
    const track = stream.getVideoTracks()[0];
    const onEnded = () => {
      if (done.current) return;
      lost.current = true;
      setCameraLost(true);
      report("camera_off");
    };
    track?.addEventListener("ended", onEnded);
    return () => track?.removeEventListener("ended", onEnded);
  }, [watching, stream, report, done]);

  useEffect(
    () => () => {
      stopCamera(live.current);
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    },
    []
  );

  const restoreCamera = async () => {
    try {
      const s = await openCamera();
      lost.current = false;
      setCameraLost(false);
      setStream(s);
    } catch {
      setCameraLost(true);
    }
  };

  // Phone / extra person / nobody in view
  useEffect(() => {
    if (!watching || !proctor.detector) return;
    let phone = 0, crowd = 0, absent = 0, absentReported = false, busy = false;
    const timer = setInterval(async () => {
      const v = video.current;
      if (busy || done.current || lost.current || !v || v.readyState < 2) return;
      busy = true;
      try {
        const seen = await inspect(proctor.detector, v);
        phone = seen.phone ? phone + 1 : 0;
        crowd = seen.people >= 2 ? crowd + 1 : 0;
        absent = seen.people === 0 ? absent + 1 : 0;
        if (!absent) absentReported = false;
        if (phone >= PHONE_CHECKS) {
          phone = 0;
          report("phone_detected", true);
        } else if (crowd >= CROWD_CHECKS) {
          crowd = 0;
          report("multiple_people", true);
        } else if (absent >= ABSENT_CHECKS && !absentReported) {
          absentReported = true;
          report("no_person", true);
        }
      } catch {
        // a skipped frame is fine
      } finally {
        busy = false;
      }
    }, CHECK_EVERY_MS);
    return () => clearInterval(timer);
  }, [watching, proctor, report, done]);

  const cameraView = watching && stream && (
    <div className="fixed bottom-4 right-4 z-30 w-40 overflow-hidden rounded-lg border border-border bg-black shadow-lg">
      <video ref={video} muted playsInline className="aspect-[4/3] w-full -scale-x-100 object-cover" />
      <p className="flex items-center gap-1.5 bg-card px-2 py-1 text-[11px] text-muted">
        <span className="inline-block h-2 w-2 rounded-full bg-red-500" /> Proctoring on
      </p>
    </div>
  );

  let overlay = null;
  if (watching && needsFullscreen) {
    overlay = (
      <Blocker title="Return to full screen">
        <p>The test only runs in full screen. Leaving it counts as a warning.</p>
        <Button className="mt-5" onClick={() => enterFullscreen()}>
          Return to full screen
        </Button>
      </Blocker>
    );
  } else if (watching && cameraLost) {
    overlay = (
      <Blocker title="Your camera stopped">
        <p>Turn your camera back on to continue the test.</p>
        <Button className="mt-5" onClick={restoreCamera}>
          Turn camera on
        </Button>
      </Blocker>
    );
  } else if (notice) {
    overlay = (
      <Blocker title={`Warning ${notice.warnings} of ${notice.limit}`} tone="amber">
        <p>{notice.text}</p>
        <p className="mt-2 text-muted">
          At {notice.limit} warnings your test is submitted automatically and marked as malpractice.
        </p>
        <Button className="mt-5" onClick={() => setNotice(null)}>
          Back to the test
        </Button>
      </Blocker>
    );
  }

  return { warnings, limit: watching ? limit : null, overlay, cameraView };
}

function Blocker({ title, tone, children }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/95 p-4" role="alertdialog" aria-label={title}>
      <Card className={`max-w-md p-6 text-center text-sm ${tone === "amber" ? "border-amber-500/40" : ""}`}>
        <h2 className={`text-lg font-semibold ${tone === "amber" ? "text-amber-200" : ""}`}>{title}</h2>
        <div className="mt-3 text-slate-300">{children}</div>
      </Card>
    </div>
  );
}
