/**
 * imageResize.js — Phase 9.9 W3
 *
 * Client-side image resize utility. Reads any image File, draws it to a
 * canvas at most maxDim pixels on its longest edge, and returns a JPEG File
 * suitable for multipart upload. The server still does its own canonical
 * resize to display sizes (128/48); this just gets the wire payload down
 * from a multi-MB phone photo to ~30 KB so the upload succeeds quickly and
 * stays well under the 6 MB backend ceiling.
 *
 * Aspect ratio is preserved. quality applies to JPEG encoding.
 */
export async function resizeImageFile(file, maxDim = 256, quality = 0.85) {
  const dataUrl = await new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.onerror = rej;
    r.readAsDataURL(file);
  });
  const img = await new Promise((res, rej) => {
    const i = new Image();
    i.onload = () => res(i);
    i.onerror = rej;
    i.src = dataUrl;
  });
  const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
  const w = Math.round(img.width * scale);
  const h = Math.round(img.height * scale);
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0, w, h);
  const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', quality));
  return new File([blob], file.name.replace(/\.[^.]+$/, '.jpg'), { type: 'image/jpeg' });
}
