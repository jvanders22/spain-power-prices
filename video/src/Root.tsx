import React from 'react';
import {Composition} from 'remotion';
import {SolarExplainer} from './SolarExplainer';
import {SIZE} from './theme';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="SolarExplainer"
    component={SolarExplainer}
    durationInFrames={600}
    fps={30}
    width={SIZE}
    height={SIZE}
  />
);
