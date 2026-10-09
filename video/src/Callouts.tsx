import React from 'react';
import {Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import data from './data.json';
import {fmt1} from './format';
import {COLORS, MARGIN} from './theme';
import {T} from './timeline';

const [Y1, Y2] = data.years;

const Arrow: React.FC<{dir: 'up' | 'down'; color: string}> = ({dir, color}) => (
  <svg width={30} height={30} viewBox="0 0 30 30" style={{flexShrink: 0}}>
    <path
      d={dir === 'down' ? 'M15 27 L3 11 H11 V3 H19 V11 H27 Z' : 'M15 3 L27 19 H19 V27 H11 V19 H3 Z'}
      fill={color}
    />
  </svg>
);

const Card: React.FC<{
  label: string;
  from: number;
  to: number;
  dir: 'up' | 'down';
  color: string;
  delay: number;
}> = ({label, from, to, dir, color, delay}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame: frame - delay, fps, config: {damping: 200}});
  const count = interpolate(frame, [T.countStart + (delay - T.calloutsIn), T.countEnd + (delay - T.calloutsIn)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });
  const value = from + (to - from) * count;

  return (
    <div
      style={{
        flex: 1,
        padding: '18px 26px',
        borderRadius: 18,
        background: 'rgba(255,255,255,0.04)',
        border: `1.5px solid ${color}55`,
        opacity: enter,
        transform: `translateY(${(1 - enter) * 30}px)`,
      }}
    >
      <div style={{display: 'flex', alignItems: 'center', gap: 10, fontSize: 24, fontWeight: 600, color: COLORS.textMuted}}>
        <Arrow dir={dir} color={color} />
        {label}
      </div>
      <div style={{marginTop: 8, display: 'flex', alignItems: 'baseline', gap: 10, whiteSpace: 'nowrap'}}>
        <span style={{fontSize: 30, fontWeight: 600, color: COLORS.textMuted}}>{fmt1(from)} →</span>
        <span style={{fontSize: 46, fontWeight: 800, color, fontVariantNumeric: 'tabular-nums'}}>{fmt1(value)}</span>
        <span style={{fontSize: 22, fontWeight: 600, color: COLORS.textMuted}}>€/MWh</span>
      </div>
    </div>
  );
};

export const Callouts: React.FC = () => (
  <div style={{position: 'absolute', left: MARGIN, right: MARGIN, top: 878, display: 'flex', gap: 24}}>
    <Card
      label="Midday 11:00–16:59"
      from={Y1.midday_11_16}
      to={Y2.midday_11_16}
      dir="down"
      color={COLORS.down}
      delay={T.calloutsIn}
    />
    <Card
      label="Evening 19:00–22:59"
      from={Y1.evening_19_22}
      to={Y2.evening_19_22}
      dir="up"
      color={COLORS.up}
      delay={T.calloutsIn + T.calloutStagger}
    />
  </div>
);
