/* シンプルなオフラインキャッシュ。中身を更新したら CACHE の数字を上げること */
var CACHE = 'ygolife-v6';   /* index.html の CACHE_NAME と同じ値にすること */

/* インストール時に先読みするのは、アプリ本体と軽い音（効果音＋最初のBGM）だけ。
   残りのBGMは初回再生時にキャッシュされる。音源を長い曲に差し替えても
   インストールが重くならないようにするため。 */
var SHELL = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  './assets/audio/bgm1.m4a',
  './assets/audio/damage.m4a',
  './assets/audio/coin.m4a',
  './assets/audio/dice.m4a'
];

self.addEventListener('install', function(e){
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE).then(function(c){
      /* 1つでも落ちると install ごと失敗するので個別に握りつぶす */
      return Promise.all(SHELL.map(function(u){
        return c.add(u).catch(function(){});
      }));
    })
  );
});

self.addEventListener('activate', function(e){
  e.waitUntil(
    caches.keys().then(function(keys){
      return Promise.all(keys.map(function(k){
        return k === CACHE ? null : caches.delete(k);
      }));
    }).then(function(){ return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function(e){
  if(e.request.method !== 'GET') return;
  var url = new URL(e.request.url);
  if(url.origin !== location.origin) return;

  /* HTML はネットワーク優先（更新をすぐ反映）、オフライン時のみキャッシュ */
  var isDoc = e.request.mode === 'navigate' || e.request.destination === 'document';
  if(isDoc){
    e.respondWith(
      fetch(e.request).then(function(res){
        var copy = res.clone();
        caches.open(CACHE).then(function(c){ c.put(e.request, copy); });
        return res;
      }).catch(function(){
        return caches.match(e.request).then(function(hit){
          return hit || caches.match('./index.html');
        });
      })
    );
    return;
  }

  /* それ以外（音源・アイコン等）はキャッシュ優先＋取得できたら保存
     （音源が無い場合は 404 がそのまま返り、アプリ側で無音扱いになる） */
  e.respondWith(
    caches.match(e.request).then(function(hit){
      if(hit) return hit;
      return fetch(e.request).then(function(res){
        if(res && res.status === 200 && res.type === 'basic'){
          var copy = res.clone();
          caches.open(CACHE).then(function(c){ c.put(e.request, copy); });
        }
        return res;
      }).catch(function(){
        return caches.match('./index.html');
      });
    })
  );
});
