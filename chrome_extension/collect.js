// Injected into the current page when the popup opens. Returns the tracking numbers, a likely address and the
// photos found on the page. The last expression is the script's result.
(() => {
  const text = document.body ? document.body.innerText : "";
  const trackingIds = [...new Set(text.match(/\bSPX[A-Z]{3}\d{12,}\b/g) || [])];
  const addresses = [...new Set(text.match(/\b\d+[A-Za-z]?\s[^,\n]{2,60},[^,\n]{2,40},\s*[A-Z]{2}\s+\d{5}\b/g) || [])];

  const seen = new Set();
  const images = [];
  const add = (url, w, h) => {
    if (!url || !/^https?:/.test(url)) return;
    const key = url.split("?")[0];
    if (seen.has(key)) return;
    seen.add(key);
    images.push({ url, w, h });
  };
  for (const img of document.images) {
    const url = img.currentSrc || img.src;
    if (img.naturalWidth >= 200 && img.naturalHeight >= 200) add(url, img.naturalWidth, img.naturalHeight);
  }
  for (const a of document.querySelectorAll("a[href]")) {
    if (/\.(jpe?g|png|webp)(\?|$)/i.test(a.href)) add(a.href, 0, 0);
  }
  // a photo opened directly in its own tab
  if (document.contentType && document.contentType.startsWith("image/")) add(location.href, 0, 0);
  return { trackingIds, addresses, images, url: location.href };
})();
