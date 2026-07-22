import { describe, expect, it } from "vitest";

import {
  mediaFailureReason,
  playFailureReason,
  shouldStartTTS,
} from "./ttsPlayback";

describe("reply TTS browser policy", () => {
  it("auto-starts only after confirmation and never on refresh restore", () => {
    expect(shouldStartTTS("CONFIRMATION")).toBe(true);
    expect(shouldStartTTS("RESTORE")).toBe(false);
    expect(shouldStartTTS("MANUAL")).toBe(true);
  });

  it("reports only the bounded decode, media, and play rejection reasons", () => {
    expect(mediaFailureReason(3)).toBe("DECODE_FAILED");
    expect(mediaFailureReason(4)).toBe("MEDIA_ERROR");
    expect(mediaFailureReason(null)).toBe("MEDIA_ERROR");
    expect(playFailureReason()).toBe("PLAY_REJECTED");
  });
});
