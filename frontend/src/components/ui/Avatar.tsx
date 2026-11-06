import { useState } from 'react';
import styles from './Avatar.module.css';

interface AvatarProps {
  name?: string | null;
  /** The picture from GitHub, Google or Gravatar; initials when there is none or it fails to load. */
  src?: string | null;
  size?: number;
  className?: string;
}

function initialsOf(name?: string | null) {
  return (name || 'Local').trim().split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase() || '?';
}

/** A round profile picture. No referrer is sent with it, so the picture's host does not learn where it is shown. */
export function Avatar({ name, src, size = 28, className }: AvatarProps) {
  const [failed, setFailed] = useState<string | null>(null);
  const show = src && failed !== src;
  return (
    <span className={`${styles.avatar} ${className ?? ''}`} style={{ width: size, height: size, fontSize: Math.round(size * 0.4) }}
      aria-hidden="true">
      {show ? (
        <img src={src} alt="" width={size} height={size} referrerPolicy="no-referrer" decoding="async"
          onError={() => setFailed(src)} />
      ) : (
        initialsOf(name)
      )}
    </span>
  );
}
