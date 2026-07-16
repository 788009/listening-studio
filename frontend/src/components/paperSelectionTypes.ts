import type { Audio } from '@/api/audios'

export type PaperSelectionState =
  | 'valid'
  | 'checking'
  | 'unavailable'
  | 'changed'

export interface PaperSelection {
  audio: Audio
  state: PaperSelectionState
  message?: string
}
