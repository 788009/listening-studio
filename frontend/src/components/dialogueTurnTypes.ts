export interface SpeakerDraft {
  key: number
  name: string
  voiceId: string
}

export interface DialogueTurnDraft {
  key: number
  speakerKey: number | ''
  text: string
}
