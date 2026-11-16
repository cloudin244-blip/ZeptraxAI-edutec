// Exam proctoring helpers: camera, on-device object detection (COCO-SSD) and snapshots.
// Everything runs in the student's browser; only events and the occasional evidence snapshot reach the server.

export const PHONE_SCORE = 0.6; // confidence needed to count a detection
export const PERSON_SCORE = 0.6;
export const CHECK_EVERY_MS = 1500;
export const PHONE_CHECKS = 2; // consecutive checks (~3 s) before a phone counts
export const CROWD_CHECKS = 3; // consecutive checks (~4.5 s) with two or more people
export const ABSENT_CHECKS = 7; // consecutive checks (~10 s) with nobody in view

export const EVENT_TEXT = {
  tab_hidden: "You left the test tab.",
  window_blur: "You switched to another window or app.",
  fullscreen_exit: "You left full screen.",
  no_person: "You were not visible on camera.",
  camera_off: "Your camera was turned off.",
};

export async function openCamera() {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser can't use a camera. Use the latest Chrome, Edge or Firefox on a laptop.");
  return navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }, audio: false });
}

export function stopCamera(stream) {
  stream?.getTracks().forEach((t) => t.stop());
}

let detectorPromise = null;

// Loaded on demand (only the exam screen needs it) and shared between the camera check and the exam
export function loadDetector() {
  if (!detectorPromise) {
    detectorPromise = (async () => {
      const tf = await import("@tensorflow/tfjs-core");
      await import("@tensorflow/tfjs-backend-webgl");
      await import("@tensorflow/tfjs-backend-cpu");
      await import("@tensorflow/tfjs-converter");
      if (!(await tf.setBackend("webgl").catch(() => false))) await tf.setBackend("cpu");
      await tf.ready();
      const cocoSsd = await import("@tensorflow-models/coco-ssd");
      return cocoSsd.load({ base: "lite_mobilenet_v2" });
    })().catch((err) => {
      detectorPromise = null; // allow a retry
      throw err;
    });
  }
  return detectorPromise;
}

// What the camera sees right now: number of people and whether a phone is in view
export async function inspect(detector, video) {
  const found = await detector.detect(video, 10, 0.4);
  return {
    people: found.filter((f) => f.class === "person" && f.score >= PERSON_SCORE).length,
    phone: found.some((f) => f.class === "cell phone" && f.score >= PHONE_SCORE),
  };
}

// Small JPEG of the current camera frame, kept as evidence for staff
export function snapshot(video) {
  if (!video?.videoWidth) return undefined;
  const canvas = document.createElement("canvas");
  canvas.width = 320;
  canvas.height = Math.round((320 * video.videoHeight) / video.videoWidth);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.6);
}

export const fullscreenSupported = () => !!document.documentElement.requestFullscreen;

export async function enterFullscreen() {
  if (!fullscreenSupported()) return false;
  try {
    await document.documentElement.requestFullscreen({ navigationUI: "hide" });
    return true;
  } catch {
    return false;
  }
}

// A second monitor lets a student read notes off-camera (Chrome and Edge can tell)
export const extraScreen = () => window.screen?.isExtended === true;
