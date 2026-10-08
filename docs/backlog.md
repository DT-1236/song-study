# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on backlog-sweep-5 (LRCLIB 404s, the document page's edit mode)

- **Drop the LRCLIB choice with the `lrclib` edit mode.** In
  `frontend/src/DocumentViewPage.tsx`, the chosen match lives in
  `useLrclibChoice` (`frontend/src/useLrclibChoice.ts`), outside `EditMode`. So
  `startChoosingLrclib` clears it with `lrclibChoice.choose(undefined)`, and
  `lrclibPreview` is gated on `lrclibSong`. A lyrics fetch still in flight when
  the mode is left (Cancel, linking, switching documents) runs to completion.
  Tie the choice's lifetime to the mode, for example by moving the picker and
  `useLrclibChoice` into a component mounted only in `lrclib` mode that reports
  the loaded lyrics up for the preview. Then delete both guards. Keep
  `NewDocumentForm`, the hook's other caller, working unchanged. *Opus 5,
  medium*: the preview and the "Link" flow fail quietly if the lyrics stop
  reaching the page, and the target shape still needs choosing.
