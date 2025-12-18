import { useEffect, useRef, useState } from 'react';
import type { Asset } from '@/lib/api';
import { getThumbnailUrl, getAssetUrl } from '@/lib/api';

export default function Thumbnail({
  asset,
  alt = '',
  className = '',
  onError,
}: {
  asset: Asset;
  alt?: string;
  className?: string;
  onError?: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    if (inView) return;
    const el = ref.current;
    if (typeof IntersectionObserver === 'undefined') {
      // fallback: immediately render
      setInView(true);
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          setInView(true);
          io.disconnect();
        }
      });
    }, { rootMargin: '200px' });
    io.observe(el);
    return () => io.disconnect();
  }, [ref, inView]);

  const src = asset ? (asset.thumbnail_path ? getThumbnailUrl(asset) : getAssetUrl(asset)) : undefined;

  return (
    <div ref={ref} className={className}>
      {inView && src ? (
        <img
          src={src}
          alt={alt}
          className="absolute inset-0 w-full h-full object-cover"
          loading="lazy"
          decoding="async"
          onError={() => onError && onError()}
        />
      ) : (
        <div className="absolute inset-0 bg-muted animate-pulse" />
      )}
    </div>
  );
}
