import React from 'react';
import {Easing, interpolate, interpolateColors, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import data from './data.json';
import {smoothPath, Point} from './path';
import {COLORS, FONT} from './theme';
import {T} from './timeline';

export const PLOT = {left: 150, right: 1000, top: 330, bottom: 790};
const Y_MAX = 140;
const Y_TICKS = [0, 40, 80, 120];
const X_TICKS = [0, 3, 6, 9, 12, 15, 18, 21];

const [Y1, Y2] = data.years;

export const xOf = (hour: number): number =>
  PLOT.left + (hour / 23) * (PLOT.right - PLOT.left);
export const yOf = (v: number): number =>
  PLOT.bottom - (v / Y_MAX) * (PLOT.bottom - PLOT.top);

const toPoints = (values: number[]): Point[] =>
  values.map((v, h) => ({x: xOf(h), y: yOf(v)}));

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const ease = Easing.bezier(0.65, 0, 0.35, 1);

const Band: React.FC<{from: number; to: number; fill: string; label: string; opacity: number; highlight: number}> = ({
  from,
  to,
  fill,
  label,
  opacity,
  highlight,
}) => {
  const x0 = xOf(from - 0.5);
  const x1 = xOf(to + 0.5);
  return (
    <g opacity={opacity}>
      <rect x={x0} y={PLOT.top} width={x1 - x0} height={PLOT.bottom - PLOT.top} fill={fill} />
      <rect
        x={x0}
        y={PLOT.top}
        width={x1 - x0}
        height={PLOT.bottom - PLOT.top}
        fill={fill}
        opacity={highlight}
      />
      <text
        x={(x0 + x1) / 2}
        y={PLOT.top + 30}
        textAnchor="middle"
        fill={COLORS.textMuted}
        fontSize={22}
        fontWeight={600}
        letterSpacing={2}
      >
        {label}
      </text>
    </g>
  );
};

const LegendRow: React.FC<{y: number; color: string; label: string; opacity: number; dashed?: boolean}> = ({
  y,
  color,
  label,
  opacity,
  dashed,
}) => {
  const x = xOf(8.6);
  return (
    <g opacity={opacity}>
      <line
        x1={x}
        x2={x + 40}
        y1={y - 10}
        y2={y - 10}
        stroke={color}
        strokeWidth={6}
        strokeLinecap="round"
        strokeDasharray={dashed ? '2 10' : undefined}
      />
      <text x={x + 56} y={y} fill={color} fontSize={30} fontWeight={700}>
        {label}
      </text>
    </g>
  );
};

export const Chart: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  // Axes / grid entrance
  const axesIn = spring({frame: frame - T.axesIn, fps, config: {damping: 200}});
  const gridDraw = interpolate(frame, [T.axesIn, T.axesIn + 35], [0, 1], {...clamp, easing: Easing.out(Easing.cubic)});
  const bandsIn = interpolate(frame, [T.axesIn + 20, T.axesIn + 50], [0, 1], clamp);

  // Year-1 line draw (stroke-dashoffset on a normalized path length)
  const draw = interpolate(frame, [T.curveDrawStart, T.curveDrawEnd], [0, 1], {
    ...clamp,
    easing: Easing.inOut(Easing.cubic),
  });
  const areaIn = interpolate(frame, [T.curveDrawEnd - 20, T.curveDrawEnd + 15], [0, 1], clamp);

  // Morph year 1 -> year 2, gently staggered left-to-right
  const morphDur = T.morphEnd - T.morphStart - 23 * 1.2;
  const values = Y1.hourly_price.map((v1, h) => {
    const start = T.morphStart + h * 1.2;
    const p = interpolate(frame, [start, start + morphDur], [0, 1], {...clamp, easing: ease});
    return v1 + (Y2.hourly_price[h] - v1) * p;
  });
  const morphGlobal = interpolate(frame, [T.morphStart, T.morphEnd], [0, 1], {...clamp, easing: ease});
  const ghostOpacity = interpolate(frame, [T.morphStart, T.morphStart + 20], [0, 0.45], clamp);

  const linePath = smoothPath(toPoints(values));
  const ghostPath = smoothPath(toPoints(Y1.hourly_price));
  const areaPath = `${linePath} L ${xOf(23)} ${PLOT.bottom} L ${xOf(0)} ${PLOT.bottom} Z`;

  // Colour of the live line: blue-grey -> amber during morph
  const colorMix = interpolate(morphGlobal, [0.35, 0.65], [0, 1], clamp);
  const lineColor = interpolateColors(colorMix, [0, 1], [COLORS.year1, COLORS.year2]);

  // Legend
  const legend1 = interpolate(frame, [T.curveDrawStart + 30, T.curveDrawStart + 50], [0, 1], clamp);
  const legend2 = spring({frame: frame - (T.morphStart + 40), fps, config: {damping: 200}});

  // Band highlight during callouts
  const highlight = interpolate(frame, [T.calloutsIn, T.calloutsIn + 20], [0, 1.2], clamp);

  const plotW = PLOT.right - PLOT.left;

  return (
    <svg width={1080} height={1080} style={{position: 'absolute', inset: 0, fontFamily: FONT}}>
      <defs>
        <linearGradient id="areaY1" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={COLORS.year1} stopOpacity={0.22} />
          <stop offset="100%" stopColor={COLORS.year1} stopOpacity={0} />
        </linearGradient>
        <linearGradient id="areaY2" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={COLORS.year2} stopOpacity={0.22} />
          <stop offset="100%" stopColor={COLORS.year2} stopOpacity={0} />
        </linearGradient>
        <filter id="glow" x="-10%" y="-10%" width="120%" height="120%">
          <feGaussianBlur stdDeviation="6" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Bands */}
      <Band from={11} to={16} fill={COLORS.bandMidday} label="MIDDAY" opacity={bandsIn} highlight={highlight} />
      <Band from={19} to={22} fill={COLORS.bandEvening} label="EVENING" opacity={bandsIn} highlight={highlight} />

      {/* Grid + y labels */}
      <g opacity={axesIn}>
        {Y_TICKS.map((t, i) => {
          const local = interpolate(gridDraw, [i * 0.12, i * 0.12 + 0.64], [0, 1], clamp);
          return (
            <g key={t} opacity={local}>
              <line
                x1={PLOT.left}
                x2={PLOT.left + plotW * local}
                y1={yOf(t)}
                y2={yOf(t)}
                stroke={t === 0 ? COLORS.axis : COLORS.grid}
                strokeWidth={t === 0 ? 2 : 1.5}
              />
              <text x={PLOT.left - 20} y={yOf(t) + 8} textAnchor="end" fill={COLORS.textMuted} fontSize={24}>
                {t}
              </text>
            </g>
          );
        })}
        <text x={PLOT.left - 20} y={PLOT.top - 22} textAnchor="end" fill={COLORS.textMuted} fontSize={22} fontWeight={600}>
          €/MWh
        </text>
        {X_TICKS.map((h, i) => (
          <g key={h} opacity={interpolate(gridDraw, [i * 0.08, i * 0.08 + 0.4], [0, 1], clamp)}>
            <line x1={xOf(h)} x2={xOf(h)} y1={PLOT.bottom} y2={PLOT.bottom + 10} stroke={COLORS.axis} strokeWidth={2} />
            <text x={xOf(h)} y={PLOT.bottom + 42} textAnchor="middle" fill={COLORS.textMuted} fontSize={24}>
              {String(h).padStart(2, '0')}
            </text>
          </g>
        ))}
      </g>

      {/* Ghost of year 1 */}
      <path
        d={ghostPath}
        fill="none"
        stroke={COLORS.year1}
        strokeWidth={3}
        strokeDasharray="2 9"
        strokeLinecap="round"
        opacity={ghostOpacity}
      />

      {/* Area under the live curve */}
      <path d={areaPath} fill="url(#areaY1)" opacity={areaIn * (1 - colorMix)} />
      <path d={areaPath} fill="url(#areaY2)" opacity={areaIn * colorMix} />

      {/* Live curve: two stacked strokes cross-fade colour */}
      <path
        d={linePath}
        fill="none"
        stroke={COLORS.year1}
        strokeWidth={6}
        strokeLinecap="round"
        strokeLinejoin="round"
        pathLength={1}
        strokeDasharray="1 1"
        strokeDashoffset={1 - draw}
        opacity={draw > 0 ? 1 - colorMix : 0}
      />
      <path
        d={linePath}
        fill="none"
        stroke={COLORS.year2}
        strokeWidth={6}
        strokeLinecap="round"
        strokeLinejoin="round"
        filter="url(#glow)"
        opacity={colorMix}
      />
      {draw >= 1 ? <circle cx={xOf(23)} cy={yOf(values[23])} r={7} fill={lineColor} /> : null}

      {/* Legend */}
      <LegendRow
        y={PLOT.top + 92}
        color={COLORS.year1}
        label={Y1.label}
        opacity={legend1 * interpolate(morphGlobal, [0, 0.4], [1, 0.75], clamp)}
        dashed={morphGlobal > 0}
      />
      <g transform={`translate(${(1 - legend2) * -16} 0)`}>
        <LegendRow y={PLOT.top + 140} color={COLORS.year2} label={Y2.label} opacity={legend2} />
      </g>
    </svg>
  );
};
