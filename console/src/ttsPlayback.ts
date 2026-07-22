export type TTSStartTrigger = "CONFIRMATION" | "RESTORE" | "MANUAL";
export type TTSFailureReason = "MEDIA_ERROR" | "DECODE_FAILED" | "PLAY_REJECTED";

export function shouldStartTTS(trigger: TTSStartTrigger): boolean {
  return trigger !== "RESTORE";
}

export function mediaFailureReason(mediaErrorCode: number | null): TTSFailureReason {
  return mediaErrorCode === 3 ? "DECODE_FAILED" : "MEDIA_ERROR";
}

export function playFailureReason(): TTSFailureReason {
  return "PLAY_REJECTED";
}
