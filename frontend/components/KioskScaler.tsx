"use client";
import { useEffect, useState, ReactNode } from "react";

/** Scales a 1920×1080 kiosk canvas to fill the viewport, preserving aspect ratio. */
export function KioskScaler({ children, bg = "#1d1a15" }: { children: ReactNode; bg?: string }) {
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const update = () =>
      setScale(Math.min(window.innerWidth / 1920, window.innerHeight / 1080));
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return (
    <div style={{ width: "100vw", height: "100vh", overflow: "hidden", background: bg }}>
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
    </div>
  );
}
