'use client';
import { Component, type ReactNode } from 'react';
export class MapBoundary extends Component<{ children: ReactNode; retry: () => void; fallback?: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? (this.props.fallback ?? <p role="alert">지도를 불러오지 못했습니다. <button onClick={this.props.retry}>지도 다시 시도</button></p>) : this.props.children; }
}
