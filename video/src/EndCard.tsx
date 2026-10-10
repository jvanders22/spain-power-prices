import React from 'react';
import {spring, useCurrentFrame, useVideoConfig} from 'remotion';
import data from './data.json';
import {fmtPct} from './format';
import {COLORS, MARGIN} from './theme';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const fmtDay = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
};

const [Y1, Y2] = data.years;

type Stat = {big: React.ReactNode; caption: string[]};

const Change: React.FC<{from: string; to: string}> = ({from, to}) => (
  <>
    {from} <span style={{color: COLORS.textMuted}}>→</span> <span style={{color: COLORS.year2}}>{to}</span>
  </>
);

const stats: Stat[] = [
  {
    big: <Change from={fmtPct(Y1.solar_share)} to={fmtPct(Y2.solar_share)} />,
    caption: ['Solar share of demand'],
  },
  {
    big: <Change from={fmtPct(Y1.solar_capture_rate)} to={fmtPct(Y2.solar_capture_rate)} />,
    caption: ['Solar capture rate: its avg price vs the overall avg'],
  },
  {
    big: <span style={{color: COLORS.year2}}>{fmtPct(data.pct_zero_or_negative)}</span>,
    caption: [
      `of hours at or below €0 (${fmtDay(data.period[0])} – ${fmtDay(data.period[1])})`,
      `${fmtPct(data.zero_hours_midday_pct)} of them between 10:00 and 17:59`,
    ],
  },
];

export const EndCard: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = (delay: number) => spring({frame: frame - delay, fps, config: {damping: 200}, durationInFrames: 28});

  const head = enter(0);
  // Accent bar grows only after the headline is legible, so it never reads as a lone orange dash.
  const bar = enter(12);
  const footer = enter(40);

  return (
    <div style={{position: 'absolute', inset: 0, padding: `0 ${MARGIN}px`}}>
      <div style={{position: 'absolute', left: MARGIN, right: MARGIN, top: 120}}>
        <div
          style={{
            fontSize: 58,
            fontWeight: 800,
            letterSpacing: -1,
            lineHeight: 1.1,
            color: COLORS.text,
            opacity: head,
            transform: `translateY(${(1 - head) * 24}px)`,
          }}
        >
          Solar up, midday prices down
        </div>
        <div style={{marginTop: 14, fontSize: 26, fontWeight: 500, color: COLORS.textMuted, opacity: head}}>
          {Y1.label} <span style={{color: COLORS.textFaint}}>vs</span> <span style={{color: COLORS.year2}}>{Y2.label}</span>
        </div>
        {/* Accent bar: fades with the headline and grows via scaleX. Previously it was fully opaque from
            the card's first frame with width = 120 * head, so it showed as a stray orange dash before the text appeared. */}
        <div
          style={{
            marginTop: 22,
            height: 5,
            width: 120,
            background: COLORS.year2,
            borderRadius: 3,
            opacity: bar,
            transform: `scaleX(${bar})`,
            transformOrigin: 'left center',
          }}
        />

        <div style={{marginTop: 56, display: 'flex', flexDirection: 'column', gap: 50}}>
          {stats.map((s, i) => {
            const p = enter(10 + i * 9);
            return (
              <div key={i} style={{opacity: p, transform: `translateX(${(1 - p) * -30}px)`}}>
                <div style={{fontSize: 72, fontWeight: 800, color: COLORS.text, letterSpacing: -1, lineHeight: 1}}>
                  {s.big}
                </div>
                <div style={{marginTop: 12, fontSize: 30, fontWeight: 500, color: COLORS.textMuted, lineHeight: 1.3}}>
                  {s.caption.map((line) => (
                    <div key={line}>{line}</div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{position: 'absolute', left: MARGIN, right: MARGIN, bottom: 64, fontSize: 22, color: COLORS.textFaint, opacity: footer}}>
        Data: OMIE day-ahead prices, Red Eléctrica (REE)
      </div>
    </div>
  );
};
