/* シンプルなオフラインキャッシュ。中身を更新したら CACHE の数字を上げること */
var CACHE = 'ygolife-v10';   /* index.html の CACHE_NAME と同じ値にすること */

/* インストール時に先読みするのは、アプリ本体と軽い効果音だけ。
   BGMはアプリ側が取得したものを自分でキャッシュに入れる（index.html の
   cacheForOffline）ので、長い曲に差し替えてもインストールが重くならない。 */
var SHELL = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  './assets/audio/damage.m4a',
  './assets/audio/coin.m4a',
  './assets/audio/dice.m4a',
  './assets/audio/buzzer.m4a'
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

  /* それ以外（音源・アイコン等）はキャッシュを即返しつつ、裏で更新を確認する。
     条件付きGET（cache:'no-cache'）なので中身が変わっていなければ304が返り、
     通信量はほぼゼロ。変わっていればキャッシュを差し替え、次回の起動から反映される。
     これが無いと、同じファイル名で音源を差し替えても古いほうが鳴り続ける。
     （音源が無い場合は 404 がそのまま返り、アプリ側で無音扱いになる） */
  e.respondWith(
    caches.match(e.request).then(function(hit){
      var fresh = fetch(e.request.url, { cache:'no-cache' }).then(function(res){
        if(res && res.status === 200){
          var copy = res.clone();
          caches.open(CACHE).then(function(c){ c.put(e.request, copy); });
        }
        return res;
      });
      if(hit){
        fresh.catch(function(){});        /* オフラインなら黙って諦める */
        return hit;                       /* 表示・再生はキャッシュから即座に */
      }
      return fresh.catch(function(){ return caches.match('./index.html'); });
    })
  );
});
