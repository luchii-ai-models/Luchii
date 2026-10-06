export interface GT6AudioCue {
  id: string;
  kind: 'engine' | 'commentary' | 'music';
  atMs: number;
}
