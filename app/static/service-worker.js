"use strict";

// Increment this value whenever a tracked frontend asset changes.
const CACHE_VERSION = "v11";
const CACHE_PREFIX = "ecare-static-";
const CACHE_NAME = `${CACHE_PREFIX}${CACHE_VERSION}`;
const OFFLINE_URL = "/offline";
const ORIGIN_UNAVAILABLE_STATUSES = new Set([502, 503, 504, 521, 522, 523, 524, 530]);
const PRECACHE_URLS = [
  OFFLINE_URL,
  "/manifest.webmanifest",
  "/static/css/phone-frame.css",
  "/static/css/app.css",
  "/static/css/auth.css",
  "/static/css/pwa.css",
  "/static/css/offline.css",
  "/static/js/pwa.js",
  "/static/js/offline.js",
  "/static/images/roaming-advisor-hero.jpg",
  "/static/icons/apple-touch-icon.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon-maskable-192.png",
  "/static/icons/icon-maskable-512.png",
];
const SAFE_SHELL_PATHS = new Set(PRECACHE_URLS);

function hasExpectedContentType(pathname, response) {
  const contentType = (response.headers.get("Content-Type") || "").toLowerCase();
  if (pathname.endsWith(".css")) return contentType.startsWith("text/css");
  if (pathname.endsWith(".js")) return contentType.includes("javascript");
  if (pathname.endsWith(".png")) return contentType.startsWith("image/png");
  if (pathname.endsWith(".jpg") || pathname.endsWith(".jpeg")) {
    return contentType.startsWith("image/jpeg");
  }
  if (pathname === "/manifest.webmanifest") {
    return contentType.startsWith("application/manifest+json");
  }
  if (pathname === OFFLINE_URL) return contentType.startsWith("text/html");
  return false;
}

function isSafeShellResponse(request, response) {
  if (!response.ok || response.type !== "basic" || response.redirected) return false;

  const requestUrl = new URL(request.url);
  const responseUrl = new URL(response.url);
  if (
    requestUrl.origin !== responseUrl.origin
    || requestUrl.pathname !== responseUrl.pathname
    || requestUrl.search !== responseUrl.search
  ) {
    return false;
  }

  const cacheControl = response.headers.get("Cache-Control") || "";
  if (/(?:^|,)\s*(?:no-store|private)(?:\s|,|=|$)/i.test(cacheControl)) return false;
  return hasExpectedContentType(requestUrl.pathname, response);
}

async function precacheShell() {
  const cache = await caches.open(CACHE_NAME);
  await Promise.all(PRECACHE_URLS.map(async (pathname) => {
    const request = new Request(pathname, {
      cache: "reload",
      credentials: "same-origin",
      redirect: "error",
    });
    const response = await fetch(request);
    if (!isSafeShellResponse(request, response)) {
      throw new Error(`Refused to cache unsafe application-shell response: ${pathname}`);
    }
    await cache.put(request, response);
  }));
}

self.addEventListener("install", (event) => {
  event.waitUntil(precacheShell());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(
        names
          .filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
          .map((name) => caches.delete(name)),
      ))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
});

async function staticAssetResponse(request, event) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  const network = fetch(request, { redirect: "error" }).then(async (response) => {
    if (isSafeShellResponse(request, response)) {
      await cache.put(request, response.clone());
    }
    return response;
  });
  if (cached) {
    event.waitUntil(network.catch(() => undefined));
    return cached;
  }
  return network;
}

async function offlineFallback() {
  const cache = await caches.open(CACHE_NAME);
  return cache.match(OFFLINE_URL);
}

async function navigationResponse(request) {
  try {
    const response = await fetch(request, { cache: "no-store" });
    if (!ORIGIN_UNAVAILABLE_STATUSES.has(response.status)) return response;
    return (await offlineFallback()) || response;
  } catch {
    return (await offlineFallback()) || Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(navigationResponse(request));
    return;
  }

  if (
    url.pathname === "/app"
    || url.pathname.startsWith("/api/")
    || url.pathname.startsWith("/auth/")
  ) {
    return;
  }

  if (!url.search && SAFE_SHELL_PATHS.has(url.pathname)) {
    event.respondWith(staticAssetResponse(request, event));
  }
});
