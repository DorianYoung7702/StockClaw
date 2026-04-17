"use client";



import { useState, useRef, useEffect, useCallback, useId } from "react";

import { cn } from "@/lib/utils";



interface LogoProps {

  collapsed?: boolean;

  className?: string;

}



// Mascot — StockClaw AI Guardian — 32×32 viewBox, fintech aesthetic
let _logoCounter = 0;
export const LobsterSvgPaths = () => {
  const id = `sc${++_logoCounter}`;
  return (
    <>
      <defs>
        {/* Body specular — top-left */}
        <radialGradient id={`${id}-sp`} cx="0.3" cy="0.22" r="0.55">
          <stop offset="0%" stopColor="white" stopOpacity="0.28" />
          <stop offset="55%" stopColor="white" stopOpacity="0.05" />
          <stop offset="100%" stopColor="white" stopOpacity="0" />
        </radialGradient>
        {/* Body shadow — bottom */}
        <radialGradient id={`${id}-sh`} cx="0.5" cy="0.92" r="0.4">
          <stop offset="0%" stopColor="black" stopOpacity="0.22" />
          <stop offset="100%" stopColor="black" stopOpacity="0" />
        </radialGradient>
        {/* Antenna glow */}
        <radialGradient id={`${id}-ag`} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor="#fde68a" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#fde68a" stopOpacity="0" />
        </radialGradient>
        {/* Hover glow — beneath body */}
        <radialGradient id={`${id}-hv`} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor="#10b981" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
        </radialGradient>
        {/* Body radial fill — bright center to dark edge */}
        <radialGradient id={`${id}-body`} cx="0.45" cy="0.38" r="0.6">
          <stop offset="0%" stopColor="#34d399" />
          <stop offset="50%" stopColor="#10b981" />
          <stop offset="100%" stopColor="#059669" />
        </radialGradient>
      </defs>

      {/* ── Background ── */}
      <rect width="32" height="32" rx="7" className="fill-brand/8" />

      {/* ── Hover glow — floating effect ── */}
      <ellipse cx="16" cy="29.5" rx="7" ry="2" fill={`url(#${id}-hv)`} />

      {/* ── Antennae — two feelers ── */}
      <path d="M13 7 Q11 3 8 1.5" className="stroke-brand-dark" strokeWidth="1.2" strokeLinecap="round" fill="none" opacity="0.65" />
      <circle cx="8" cy="1.5" r="2.2" fill={`url(#${id}-ag)`} />
      <circle cx="8" cy="1.5" r="0.9" fill="#fde68a" />
      <circle cx="8" cy="1.5" r="0.35" fill="white" opacity="0.75" />
      <path d="M19 7 Q21 3 24 1.5" className="stroke-brand-dark" strokeWidth="1.2" strokeLinecap="round" fill="none" opacity="0.65" />
      <circle cx="24" cy="1.5" r="2.2" fill={`url(#${id}-ag)`} />
      <circle cx="24" cy="1.5" r="0.9" fill="#fde68a" />
      <circle cx="24" cy="1.5" r="0.35" fill="white" opacity="0.75" />

      {/* ── Pincers — solid claws, no arms ── */}
      <path d="M6 15 Q3.5 12.5 2 14 Q3 15.5 5 15" className="fill-brand-dark" />
      <path d="M6 15 Q4 11.5 2.5 12.5 Q2 14 4.5 14.5" className="fill-brand-dark" />
      <path d="M26 15 Q28.5 12.5 30 14 Q29 15.5 27 15" className="fill-brand-dark" />
      <path d="M26 15 Q28 11.5 29.5 12.5 Q30 14 27.5 14.5" className="fill-brand-dark" />
      {/* ── Body — smooth egg ── */}
      <ellipse cx="16" cy="16" rx="10" ry="11" fill={`url(#${id}-body)`} />
      <ellipse cx="16" cy="16" rx="10" ry="11" fill={`url(#${id}-sp)`} />
      <ellipse cx="16" cy="16" rx="10" ry="11" fill={`url(#${id}-sh)`} />

      {/* ── Visor — recessed face plate ── */}
      <ellipse cx="16" cy="12" rx="7" ry="3.5" className="fill-brand-dark" opacity="0.22" />

      {/* ── Eyes — pure white ── */}
      <circle cx="12.5" cy="12" r="0.9" fill="white" />
      <circle cx="19.5" cy="12" r="0.9" fill="white" />

      {/* ── Belly label ── */}
      <text x="16" y="21.5" textAnchor="middle" fontSize="3.8" fontWeight="bold" fill="white" opacity="0.35" fontFamily="system-ui, sans-serif" letterSpacing="0.3">Atlas</text>

      {/* ── Panel seam ── */}
      <path d="M7.5 16.5 Q16 17.2 24.5 16.5" stroke="white" strokeWidth="0.25" fill="none" opacity="0.07" />

      {/* ── Bottom rim light ── */}
      <path d="M8 22 Q16 27.5 24 22" stroke="white" strokeWidth="0.3" fill="none" opacity="0.06" />
    </>
  );
};



export function StockClawLogo({ collapsed = true, className }: LogoProps) {

  const [wandering, setWandering] = useState(false);

  const [pos, setPos] = useState<{ x: number; y: number; rot: number } | null>(null);

  const anchorRef = useRef<HTMLDivElement>(null);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const originRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });



  const moveToRandom = useCallback(() => {

    const pad = 48;

    const x = pad + Math.random() * (window.innerWidth - pad * 2);

    const y = pad + Math.random() * (window.innerHeight - pad * 2);

    const rot = Math.round(Math.random() * 360 - 180);

    setPos({ x, y, rot });

  }, []);



  const startWandering = useCallback(() => {

    // Start at origin, then after a frame fly out — ensures smooth exit animation

    if (anchorRef.current) {

      const rect = anchorRef.current.getBoundingClientRect();

      setPos({ x: rect.left, y: rect.top, rot: 0 });

    }

    // Delay first random move so the element mounts at origin first

    requestAnimationFrame(() => {

      requestAnimationFrame(() => {

        moveToRandom();

        intervalRef.current = setInterval(moveToRandom, 1800);

      });

    });

  }, [moveToRandom]);



  const [returning, setReturning] = useState(false);



  const stopWandering = useCallback(() => {

    if (intervalRef.current) {

      clearInterval(intervalRef.current);

      intervalRef.current = null;

    }

    setReturning(true);

    // Animate back to origin

    if (anchorRef.current) {

      const rect = anchorRef.current.getBoundingClientRect();

      setPos({ x: rect.left, y: rect.top, rot: 0 });

    }

    // Wait for CSS transition to finish, then unmount

    setTimeout(() => {

      setPos(null);

      setWandering(false);

      setReturning(false);

    }, 1600);

  }, []);



  useEffect(() => {

    return () => {

      if (intervalRef.current) clearInterval(intervalRef.current);

    };

  }, []);



  const handleClick = () => {

    if (returning) return; // ignore clicks during return animation

    if (wandering) {

      stopWandering();

    } else {

      if (anchorRef.current) {

        const rect = anchorRef.current.getBoundingClientRect();

        originRef.current = { x: rect.left, y: rect.top };

      }

      setWandering(true);

      startWandering();

    }

  };



  return (

    <>

      <div ref={anchorRef} className={cn("flex items-center gap-2", className)}>

        <svg

          width="32"

          height="32"

          viewBox="0 0 32 32"

          fill="none"

          xmlns="http://www.w3.org/2000/svg"

          className={cn("shrink-0 cursor-pointer select-none", wandering && "opacity-0")}

          onClick={handleClick}

        >

          <LobsterSvgPaths />

        </svg>

        {!collapsed && (

          <span className="text-sm font-bold tracking-tight text-brand">

            StockClaw

          </span>

        )}

      </div>



      {/* Wandering clone — fixed overlay bouncing around viewport */}

      {pos && (

        <svg

          width="32"

          height="32"

          viewBox="0 0 32 32"

          fill="none"

          xmlns="http://www.w3.org/2000/svg"

          className="cursor-pointer select-none drop-shadow-lg"

          style={{

            position: "fixed",

            left: pos.x,

            top: pos.y,

            transform: `rotate(${pos.rot}deg)`,

            transition: "left 1.5s cubic-bezier(.4,0,.2,1), top 1.5s cubic-bezier(.4,0,.2,1), transform 1.5s cubic-bezier(.4,0,.2,1)",

            zIndex: 9999,

            pointerEvents: "auto",

          }}

          onClick={handleClick}

        >

          <LobsterSvgPaths />

        </svg>

      )}

    </>

  );

}

