// AudioPaper Service Worker
const CACHE_NAME = 'audiopaper-v2';
const AUDIO_CACHE_NAME = 'audiopaper-audio-v1';

const STATIC_ASSETS = [
    '/',
    '/index.html',
    '/static/manifest.json',
    '/static/css/style.css',
    '/static/js/main.js',
    '/static/icons/icon.svg',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('AudioPaper: Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter((name) => name !== CACHE_NAME && name !== AUDIO_CACHE_NAME)
                    .map((name) => caches.delete(name))
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch event - network first, fallback to cache
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Skip non-GET requests except for navigation
    if (request.method !== 'GET' && request.mode !== 'navigate') return;

    // Handle API calls - network only
    if (url.pathname.startsWith('/api') || url.pathname.startsWith('/summarize') || 
        url.pathname.startsWith('/transcript') || url.pathname.startsWith('/generate') ||
        url.pathname.startsWith('/chat') || url.pathname.startsWith('/ragflow')) {
        return; // Let these go through normally
    }

    // Handle audio files - cache first, then network
    if (url.pathname.startsWith('/generated_audio/')) {
        event.respondWith(
            caches.open(AUDIO_CACHE_NAME).then((cache) => {
                return cache.match(request).then((cachedResponse) => {
                    if (cachedResponse) {
                        return cachedResponse;
                    }
                    return fetch(request).then((response) => {
                        if (response.status === 200) {
                            cache.put(request, response.clone());
                        }
                        return response;
                    }).catch(() => {
                        return new Response('Audio not available offline', { 
                            status: 503,
                            statusText: 'Service Unavailable'
                        });
                    });
                });
            })
        );
        return;
    }

    // Handle static assets and navigation - network first, fallback to cache
    event.respondWith(
        fetch(request)
            .then((response) => {
                // Clone and cache successful responses
                if (response.status === 200) {
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(request, responseClone);
                    });
                }
                return response;
            })
            .catch(() => {
                // Network failed, try cache
                return caches.match(request).then((cachedResponse) => {
                    if (cachedResponse) {
                        return cachedResponse;
                    }

                    // Return offline page for navigation requests
                    if (request.mode === 'navigate') {
                        return caches.match('/');
                    }

                    return new Response('Offline', { status: 503 });
                });
            })
    );
});

// Handle messages from the main app
self.addEventListener('message', (event) => {
    if (event.data === 'skipWaiting') {
        self.skipWaiting();
    }
    
    // Cache a specific audio file
    if (event.data && event.data.type === 'cacheAudio') {
        const audioUrl = event.data.url;
        caches.open(AUDIO_CACHE_NAME).then((cache) => {
            fetch(audioUrl).then((response) => {
                if (response.status === 200) {
                    cache.put(audioUrl, response);
                    console.log('AudioPaper: Cached audio file:', audioUrl);
                }
            }).catch((err) => {
                console.error('AudioPaper: Failed to cache audio:', err);
            });
        });
    }
});

// Background sync for failed uploads
self.addEventListener('sync', (event) => {
    if (event.tag === 'sync-uploads') {
        event.waitUntil(syncUploads());
    }
});

async function syncUploads() {
    // Get pending uploads from IndexedDB and retry
    console.log('AudioPaper: Syncing pending uploads...');
}
