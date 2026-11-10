import "./channel3-thumb.css";

const SIZES = { sm: 32, md: 48, lg: 64 } as const;

export interface Channel3ThumbProps {
  /** The item's picture (`channel3_image_url`, or `image_url` on a catalogue line). */
  src?: string | null;
  /** The item's title: it is the picture's alt text. */
  title?: string | null;
  size?: keyof typeof SIZES;
  className?: string;
  testId?: string;
}

/** Only a web address can be a picture; anything else is treated as no picture. */
function pictureUrl(src: string | null | undefined): string {
  const url = String(src ?? "").trim();
  return /^https?:\/\//i.test(url) ? url : "";
}

/**
 * A Channel3 item's picture as a small thumbnail. The box has a fixed size, set
 * on the element itself, so the row does not move when the picture arrives, and
 * the picture is only fetched when it comes near the screen. Without a URL
 * nothing is rendered: there is no placeholder box.
 */
export function Channel3Thumb({ src, title, size = "md", className = "", testId = "channel3-thumb" }: Channel3ThumbProps) {
  const url = pictureUrl(src);
  if (!url) return null;
  const edge = SIZES[size];
  return (
    <img
      src={url}
      alt={String(title ?? "").trim()}
      width={edge}
      height={edge}
      loading="lazy"
      decoding="async"
      className={`channel3-thumb channel3-thumb--${size}${className ? ` ${className}` : ""}`}
      data-testid={testId}
    />
  );
}
