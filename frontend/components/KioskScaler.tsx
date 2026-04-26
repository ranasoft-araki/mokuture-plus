"use client";
import { useEffect, useState, ReactNode } from "react";

type Ripple = { id: number; x: number; y: number };

/** Scales a 1920×1080 kiosk canvas to fill the viewport, preserving aspect ratio. */
export function KioskScaler({ children, bg = "#1d1a15" }: { children: ReactNode; bg?: string }) {
  const [scale, setScale] = useState(1);
  const [ripples, setRipples] = useState<Ripple[]>([]);

  useEffect(() => {
    const update = () =>
      setScale(Math.min(window.innerWidth / 1920, window.innerHeight / 1080));
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  const handlePointer = (e: React.PointerEvent) => {
    setRipples(prev => [...prev, { id: Date.now(), x: e.clientX, y: e.clientY }]);
  };

  const removeRipple = (id: number) => {
    setRipples(prev => prev.filter(r => r.id !== id));
  };

  return (
    <div
      style={{ width: "100vw", height: "100vh", overflow: "hidden", background: bg }}
      onPointerDown={handlePointer}
    >
      <div
        style={{
          width: 1920,
          height: 1080,
          transformOrigin: "top left",
          transform: `scale(${scale})`,
        }}
      >
        {children}
      </div>
      {ripples.map(r => (
        <span
          key={r.id}
          onAnimationEnd={() => removeRipple(r.id)}
          style={{
            position: "fixed",
            left: r.x - 70,
            top: r.y - 70,
            width: 140,
            height: 140,
            borderRadius: "50%",
            background: "rgba(255,255,255,0.35)",
            pointerEvents: "none",
            animation: "kiosk-ripple 0.6s ease-out forwards",
          }}
        />
      ))}
    </div>
  );
}
