// All timings in frames @ 30fps. This is the single source of truth for pacing.
//
//  0.0s  title in
//  3.0s  axes + bands
//  4.2s  year-1 curve draws (to 7.2s)
//  8.3s  morph to year 2 (to 12.0s)
// 12.3s  callouts in, counters run; evening counter settles at 14.9s (frame 448)
// 14.9s  HOLD: full chart + both final callouts, ~3.7s
// 18.6s  crossfade chart -> closing card (0.7s chart fade-out 18.6-19.3s; card fades in from 19.2s)
// 21.4s  closing card fully visible (incl. source line), HOLD ~5.1s
// 26.5s  end
export const T = {
  titleIn: 0,
  axesIn: 90,
  curveDrawStart: 125,
  curveDrawEnd: 215,
  morphStart: 250,
  morphEnd: 360,
  calloutsIn: 370,
  calloutStagger: 8, // evening card starts this many frames after the midday card
  countStart: 385,
  countEnd: 440,
  // Main scene fade-out (eased in-out, 0.7s). Starts ~3.7s after the last counter settles.
  sceneOut: 558,
  sceneOutEnd: 579,
  // Closing card starts once the chart is below ~3% opacity, so the two scenes' text never overlaps.
  endIn: 575,
  end: 795,
};

// Frame at which the last (evening) counter reaches its final value.
export const lastCounterSettled = T.countEnd + T.calloutStagger;
