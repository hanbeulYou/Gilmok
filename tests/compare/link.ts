// The standalone validation bundle has no Next router; the deployed app uses next/link.
import { createElement, type ComponentProps } from 'react';
export default function Link(props: ComponentProps<'a'>) { return createElement('a', props); }
