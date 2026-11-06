import { useRef, useState } from 'react';
import type { PointerEvent, ReactNode } from 'react';
import { motion, useMotionTemplate, useMotionValue, useReducedMotion, useSpring } from 'motion/react';
import styles from './TiltCard.module.css';

interface TiltCardProps {
  children: ReactNode;
  className?: string;
  /** Largest tilt, in degrees, at the card's edges. */
  max?: number;
}

/**
 * A card that tilts a little towards the pointer, with a soft glare that follows it. Mouse and pen
 * only (touch scrolls), and still when motion is reduced. While a field inside has focus the tilt
 * is a third as strong, so text being typed does not move about.
 */
export function TiltCard({ children, className, max = 6 }: TiltCardProps) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const [typing, setTyping] = useState(false);
  const spring = { stiffness: 260, damping: 24, mass: 0.6 };
  const rotateX = useSpring(0, spring);
  const rotateY = useSpring(0, spring);
  const lift = useSpring(1, spring);
  const glare = useSpring(0, { stiffness: 200, damping: 30 });
  const gx = useMotionValue(50);
  const gy = useMotionValue(30);
  const background = useMotionTemplate`radial-gradient(520px circle at ${gx}% ${gy}%, var(--tilt-glare), transparent 60%)`;

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    if (reduce || e.pointerType === 'touch' || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    const strength = typing ? max / 3 : max;
    rotateY.set((x - 0.5) * 2 * strength);
    rotateX.set(-(y - 0.5) * 2 * strength);
    lift.set(1.012);
    gx.set(x * 100);
    gy.set(y * 100);
    glare.set(1);
  };
  const onLeave = () => {
    rotateX.set(0);
    rotateY.set(0);
    lift.set(1);
    glare.set(0);
  };

  return (
    <motion.div ref={ref} className={`${styles.tilt} ${className ?? ''}`}
      style={reduce ? undefined : { rotateX, rotateY, scale: lift, transformPerspective: 1000 }}
      onPointerMove={onMove} onPointerLeave={onLeave}
      onFocusCapture={(e) => setTyping(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)}
      onBlurCapture={() => setTyping(false)}>
      {children}
      {!reduce && <motion.span className={styles.glare} style={{ background, opacity: glare }} aria-hidden="true" />}
      {!reduce && <motion.span className={styles.edge} style={{ opacity: glare }} aria-hidden="true" />}
    </motion.div>
  );
}
