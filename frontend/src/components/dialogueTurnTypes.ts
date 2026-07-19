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

export type DialogueTurnPreviewStatus =
  | 'idle'
  | 'stale'
  | 'submitting'
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'

export interface DialogueTurnPreview {
  status: DialogueTurnPreviewStatus
  progress: number
  mediaPath?: string
  errorMessage?: string
}
