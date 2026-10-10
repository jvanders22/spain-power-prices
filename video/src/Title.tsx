import React from 'react';
import {interpolateColors, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {COLORS, MARGIN} from './theme';

export const Title: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const enter = (delay: number) => spring({frame: frame - delay, fps, config: {damping: 200}, durationInFrames: 30});
  const t = enter(4);
  const s = enter(16);
  const midday = interpolateColors(frame, [30, 55], [COLORS.text, COLORS.year2]);

  return (
    <div style={{position: 'absolute', left: MARGIN, right: MARGIN, top: 72}}>
      <div
        style={{
          fontSize: 62,
          fontWeight: 800,
          lineHeight: 1.08,
          letterSpacing: -1.2,
          color: COLORS.text,
          opacity: t,
          transform: `translateY(${(1 - t) * 28}px)`,
        }}
      >
        Solar is eating Spain’s <span style={{color: midday}}>midday</span> power price
      </div>
      <div
        style={{
          marginTop: 18,
          fontSize: 30,
          fontWeight: 500,
          color: COLORS.textMuted,
          opacity: s,
          transform: `translateY(${(1 - s) * 20}px)`,
        }}
      >
        Average day-ahead price by hour, Spain
      </div>
    </div>
  );
};
