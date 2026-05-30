/**
 * Phase 43a — Captioned screenshot for help pages.
 *
 * Replaces the placeholder boxes left by Phase 43 in the three
 * getting-started pages. Renders a <figure> with the image and the
 * authoritative caption text directly below it. The caption doubles as
 * the alt text — Phase 43a captions are descriptive enough to serve
 * both purposes.
 */
export default function HelpScreenshot({ src, caption, alt }) {
  return (
    <figure className="my-3">
      <img
        src={src}
        alt={alt ?? caption}
        loading="lazy"
        className="w-full rounded-lg border border-gray-200 shadow-sm"
      />
      <figcaption className="mt-2 text-xs text-gray-500 italic">
        {caption}
      </figcaption>
    </figure>
  );
}
