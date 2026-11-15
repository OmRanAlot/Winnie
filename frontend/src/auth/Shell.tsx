// The design's page frame (colors, fonts, buttons) for screens shown before App loads:
// login, "Loading your session…", account errors.
import type { ReactNode } from 'react';
import { CSS } from '../App.jsx';

export function Shell({ children }: { children: ReactNode }) {
    return <div className="app"><style>{CSS}</style><main className="page-content">{children}</main></div>;
}
