import React from 'react';
import {AbsoluteFill, Easing, interpolate, Sequence, useCurrentFrame} from 'remotion';
import {Callouts} from './Callouts';
import {Chart} from './Chart';
import {EndCard} from './EndCard';
import {COLORS, FONT} from './theme';
import {T} from './timeline';
import {Title} from './Title';

export const SolarExplainer: React.FC = () => {
  const frame = useCurrentFrame();

  // Main scene (title + chart + callouts) eases out before the end card.
  // Title, Chart and Callouts are timed against absolute frames (see timeline.ts).
  const out = interpolate(frame, [T.sceneOut, T.sceneOutEnd], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.cubic),
  });

  return (
    <AbsoluteFill
      style={{
        fontFamily: FONT,
        color: COLORS.text,
        background: `radial-gradient(circle at 50% 30%, ${COLORS.bgGlow} 0%, ${COLORS.bg} 70%)`,
      }}
    >
      {out < 1 ? (
        <AbsoluteFill style={{opacity: 1 - out, transform: `scale(${1 - out * 0.02})`}}>
          <Title />
          <Chart />
          <Callouts />
        </AbsoluteFill>
      ) : null}

      <Sequence from={T.endIn}>
        <EndCard />
      </Sequence>
    </AbsoluteFill>
  );
};
