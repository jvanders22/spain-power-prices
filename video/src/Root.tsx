import React from 'react';
import {Composition} from 'remotion';
import {SolarExplainer} from './SolarExplainer';
import {SIZE} from './theme';
import {T} from './timeline';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="SolarExplainer"
    component={SolarExplainer}
    durationInFrames={T.end}
    fps={30}
    width={SIZE}
    height={SIZE}
  />
);
