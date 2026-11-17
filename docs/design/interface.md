# RallyMark interface

The source of truth for product and local-preview presentation. Local import remains development-only; both modes reuse the same player, controls and surface tokens.

## Visual system

Preserve the selected table-tennis direction: court `#07170e`, surface `#10251a`, raised surface `#183322`, boundary `#304b38`, primary text `#f3f7ee`, accent `#c6f568`. Use a locally bundled DM Sans for Latin/numeric text and the system Chinese sans-serif fallback. Numbers use tabular figures. All interactive targets are at least 44px. Spacing follows 4/8/12/16/24/32, surface corners 12/20px, icon strokes share one weight.

The video is the primary visual. Chrome is compact and quieter: no OS-rendered selection menus or file widgets, no browser title tooltips, no decorative looping motion. Short copy is used for stable labels; details and actionable errors remain readable on demand.

## Layout

```text
Brand                                      contextual actions
Match title                         custom selector + settings
┌────────────────────────────┐ ┌───────────────────────────┐
│                            │ │ score / round     auto    │
│          original          │ │        previous play next │
│           video            │ │ timeline + times          │
│                            │ │ full cards + page controls│
└────────────────────────────┘ └───────────────────────────┘
```

Header, workspace toolbar and player share one page gutter and maximum width. Desktop columns share top and bottom boundaries. Narrow screens stack video and controls, with the selector and its adjacent action sharing a height and baseline. Titles truncate rather than move controls. Local-only settings live in a consistent modal rather than expanding the entire page.

Desktop fullscreen uses a full-width video above a compact bottom control strip.
Phone landscape keeps the video at the full available height, overlays controls
at the bottom, and hides them after 2.5 seconds of uninterrupted playback. A tap
reveals controls; pause, buffering, errors and keyboard focus keep them available.
Portrait anchors the video at the top and places score, transport, timeline,
auto-skip and a scrollable complete rally list below it. Only the list scrolls;
rotation preserves playback and does not require re-entering fullscreen.
Preserve the video's aspect ratio with `object-fit: contain`. Browsers without
element fullscreen use the same player expanded to the available viewport,
including focus containment, Escape/button exit and restored focus; do not hand
off to a native video-only surface that loses rally navigation.

## Components and contracts

- Buttons, score badges, toggles, progress, dialogs, selectors, tooltips and file controls have one authoritative implementation in `apps/web/src/ui`.
- Popovers use viewport collision handling, independent scrolling, Escape/outside dismissal and restored focus. Custom listboxes support arrows, Home/End, typing and selection.
- The timeline is visually custom while retaining an accessible range input for keyboard/touch semantics. Manual movement keeps the existing auto-skip rule.
- Rally cards show complete groups; no resting half-card clipping. Score and status occupy separate slots so the number stays centered. Pagination and the active round remain accessible.
- Dialogs contain focus and scroll, close on Escape and return focus. File removal requires confirmation; import errors appear beside their control.
- Loading, upload, failure, history, empty results and local debug views use the same typography, surfaces, actions and focus treatment.

## Acceptance and versioning

Validate 320/390/768/1024/1440/1920px, long names, missing scores, many rounds, last pages, keyboard-only selection, touch-sized actions, modal boundaries, reduced motion, production bundle isolation and existing playback transitions. Capture both closed and expanded controls. UI review follows the current [Web Interface Guidelines](https://github.com/vercel-labs/web-interface-guidelines).

The pre-redesign checkpoint is `ui-baseline-20261113` (`a24c9ea`), pushed to GitLab and GitHub. Commit each passing milestone and synchronize both remotes; preserve history so changes can be reverted independently.

## Product entry and management

The selected homepage centers a concise headline and upload/preview actions over
a working shared-player showcase. Center this group within the available first
screen on desktop, using fluid spacing and a centered maximum-width showcase.
Reserve symmetric scrollbar gutters so the visual center remains the viewport
center. Short screens grow naturally; mobile uses a normal flowing stack. The public
header never includes management. `/app` retains upload/history, `/preview` stays
read-only, and old root `?video=` links remain compatible.

Management reuses the same fields, buttons, selector, dialog and player. Desktop
uses a quiet side navigation; mobile uses four touch-sized tabs. Video names
truncate, numeric facts stay tabular, and action labels remain concise. Modal
errors appear inside the dialog. Portal dropdowns target the nearest native
dialog so its top-layer isolation does not block pointer/keyboard interaction.
