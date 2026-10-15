// Shroom service worker: makes the portal installable and lets notifications be shown on phones (where
// `new Notification()` is not allowed). It deliberately caches nothing: every request goes to the network, so a
// deploy is visible at once and no private API data is stored on the device.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});   // network only (a fetch handler is part of the install criteria)
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(list => {
    const tab = list.find(c => new URL(c.url).origin === self.location.origin);
    if (tab) { tab.postMessage({type: 'open-chat', chat: e.notification.data && e.notification.data.chat}); return tab.focus(); }
    return self.clients.openWindow('/');
  }));
});
