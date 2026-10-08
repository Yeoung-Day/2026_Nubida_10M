/**
 * 누비다플랫폼 — USB OTG 시리얼 브리지 (Android 앱 전용)
 * =====================================================
 * 안드로이드 앱(WebView)에는 Web Serial API(navigator.serial)가 없다.
 * 그래서 네이티브 플러그인(NubidaSerial)을 감싸 **Web Serial 과 동일한 인터페이스**를
 * 제공한다 → 기존 STK500 업로드 코드를 수정 없이 그대로 재사용할 수 있다.
 *
 * 제공하는 흉내(호환) 인터페이스:
 *   navigator.serial.requestPort()   → 안드로이드 앱에서 사용 가능한 포트 반환
 *   port.open({ baudRate })          → 네이티브 open
 *   port.close()                     → 네이티브 close
 *   port.write(Uint8Array)           → 네이티브 write (Base64)
 *   port.read()                      → 네이티브 read  ({ value: Uint8Array, done })
 *   port.setSignals({ dataTerminalReady, requestToSend }) → DTR/RTS
 *   port.getInfo()                   → { usbVendorId, usbProductId }
 *   port.readable / port.writable     → getReader() 를 가진 최소 스트림 스텁
 *
 * 주의: 웹 브라우저에는 아무 것도 하지 않는다(navigator.serial 이 이미 있으면 손대지 않음).
 */
(function () {
  'use strict';

  var TAG = '[NubidaSerial]';

  // ── 네이티브 플러그인 접근 ──
  function getPlugin() {
    try {
      if (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.NubidaSerial) {
        return window.Capacitor.Plugins.NubidaSerial;
      }
    } catch (e) {}
    return null;
  }

  // ── 네이티브 앱 여부 ──
  function isNativeApp() {
    if (window.IS_NATIVE) return true;
    try {
      if (window.Capacitor && window.Capacitor.isNativePlatform) return window.Capacitor.isNativePlatform();
    } catch (e) {}
    return false;
  }

  var plugin = getPlugin();
  var NATIVE = isNativeApp() && !!plugin;

  // ── Base64 ↔ Uint8Array ──
  function b64ToBytes(b64) {
    if (!b64) return new Uint8Array(0);
    var bin = atob(b64);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  function bytesToB64(bytes) {
    var arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    var s = '';
    var CHUNK = 0x8000;   // 스택 오버플로 방지
    for (var i = 0; i < arr.length; i += CHUNK) {
      s += String.fromCharCode.apply(null, arr.subarray(i, i + CHUNK));
    }
    return btoa(s);
  }

  // ── 타임아웃 헬퍼 ──
  function withTimeout(promise, ms, label) {
    return new Promise(function (resolve, reject) {
      var done = false;
      var t = setTimeout(function () {
        if (done) return;
        done = true;
        reject(new Error((label || '작업') + ' 시간 초과 (' + ms + 'ms)'));
      }, ms);
      promise.then(function (v) {
        if (done) return; done = true; clearTimeout(t); resolve(v);
      }, function (e) {
        if (done) return; done = true; clearTimeout(t); reject(e);
      });
    });
  }

  // ───────────────────────────────────────────────────────────
  //  Web Serial 호환 포트 객체
  // ───────────────────────────────────────────────────────────
  function NativePort(nativeInfo) {
    this._info = nativeInfo || {};
    this._open = false;
    this._baudRate = 115200;
    this._closed = false;
    // STK500 코드가 port.readable.getReader() 를 쓰는 경우 대비 (최소 스텁)
    var self = this;
    this.readable = {
      getReader: function () { return self._makeReader(); }
    };
    this.writable = {
      getWriter: function () { return self._makeWriter(); }
    };
  }

  NativePort.prototype.getInfo = function () {
    return {
      usbVendorId: this._info.vendorId || undefined,
      usbProductId: this._info.productId || undefined,
    };
  };

  NativePort.prototype.open = function (opts) {
    var self = this;
    opts = opts || {};
    this._baudRate = opts.baudRate || 115200;
    // 시작 시 DTR/RTS 는 true (아두이노가 리셋되지 않도록 유지)
    return plugin.open({
      index: this._info.index != null ? this._info.index : 0,
      deviceId: this._info.deviceId || null,
      baudRate: this._baudRate,
      dtr: true,
      rts: true,
    }).then(function (res) {
      self._open = true;
      self._closed = false;
      log('✅ 네이티브 시리얼 포트 열림 — ' + (res.deviceName || '?') +
          ' (' + (res.chip || 'USB') + ', ' + self._baudRate + ' baud)');
      return undefined;
    });
  };

  NativePort.prototype.close = function () {
    var self = this;
    if (!this._open) return Promise.resolve();
    return plugin.close().then(function () {
      self._open = false;
      self._closed = true;
      log('🔌 네이티브 시리얼 포트 닫힘');
    }, function () {
      self._open = false;
      self._closed = true;
    });
  };

  NativePort.prototype.setSignals = function (signals) {
    if (!this._open) return Promise.resolve();
    var s = signals || {};
    var payload = {};
    if ('dataTerminalReady' in s) payload.dtr = !!s.dataTerminalReady;
    if ('requestToSend' in s) payload.rts = !!s.requestToSend;
    if (!Object.keys(payload).length) return Promise.resolve();
    // 네이티브 setSignals 는 빠르지만 연속 호출 시 안정성을 위해 순차 처리
    return plugin.setSignals(payload);
  };

  NativePort.prototype.write = function (data) {
    if (!this._open) return Promise.reject(new Error('포트가 열려 있지 않습니다.'));
    var bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
    var b64 = bytesToB64(bytes);
    return plugin.write({ data: b64, timeout: 4000 }).then(function () {
      return undefined;
    });
  };

  NativePort.prototype.read = function () {
    var self = this;
    if (!this._open) return Promise.resolve({ value: undefined, done: true });
    return plugin.read({ timeout: 1200, size: 512 }).then(function (res) {
      if (res && res.data) {
        return { value: b64ToBytes(res.data), done: false };
      }
      return { value: undefined, done: false };
    }, function () {
      return { value: undefined, done: false };
    });
  };

  // 스트림 스텁 — read() 를 감싼 reader
  NativePort.prototype._makeReader = function () {
    var self = this;
    return {
      read: function () { return self.read(); },
      releaseLock: function () {},
      cancel: function () { return Promise.resolve(); },
    };
  };
  NativePort.prototype._makeWriter = function () {
    var self = this;
    return {
      write: function (data) { return self.write(data).then(function () { return undefined; }); },
      releaseLock: function () {},
      close: function () { return Promise.resolve(); },
    };
  };

  // ───────────────────────────────────────────────────────────
  //  navigator.serial 흉내
  // ───────────────────────────────────────────────────────────
  function NativeSerialShim() {}

  /** 안드로이드 앱: 현재 연결된 USB 시리얼 장치를 반환 (선택 다이얼로그 없음 → 바로 사용) */
  NativeSerialShim.prototype.requestPort = function () {
    return plugin.list().then(function (res) {
      var devices = (res && res.devices) || [];
      if (!devices.length) {
        var e = new Error(
          'NO_DEVICE: USB 시리얼 장치를 찾을 수 없습니다.\n' +
          '· OTG 케이블이 제대로 꽂혀 있는지 확인하세요.\n' +
          '· 아두이노 보드의 전원 LED 가 켜져 있는지 확인하세요.'
        );
        e.name = 'NotFoundError';
        throw e;
      }
      var withPerm = devices.filter(function (d) { return d.hasPermission; });
      var chosen = withPerm.length ? withPerm[0] : devices[0];
      log('🔌 USB 장치 선택: ' + (chosen.chip || 'USB') +
          ' (VID:' + chosen.vendorId + ' PID:' + chosen.productId + ')' +
          (chosen.hasPermission ? '' : ' — 권한 요청 필요'));
      return new NativePort(chosen);
    });
  };

  /** 승인된(연결된) 포트 목록 */
  NativeSerialShim.prototype.getPorts = function () {
    return plugin.list().then(function (res) {
      return ((res && res.devices) || []).map(function (d) { return new NativePort(d); });
    }, function () { return []; });
  };

  // ── 로그 (페이지에 log() 가 있으면 사용, 없으면 console) ──
  function log(msg) {
    try {
      if (typeof window.addSerialLine === 'function') { window.addSerialLine(msg); return; }
    } catch (e) {}
    console.log(TAG, msg);
  }

  // ───────────────────────────────────────────────────────────
  //  설치
  // ───────────────────────────────────────────────────────────
  var api = {
    /** 네이티브 OTG 사용 가능 여부 */
    supported: NATIVE,
    /** 네이티브 플러그인 원본 (고급 사용) */
    plugin: plugin || null,
    /** 장치 목록 조회 */
    list: function () {
      if (!NATIVE) return Promise.resolve([]);
      return plugin.list().then(function (r) { return (r && r.devices) || []; }, function () { return []; });
    },
    /** 진단 문자열 */
    diagnose: function () {
      return 'NubidaSerial: ' + (NATIVE ? '사용가능 ✅' : '사용불가 ❌') +
             ' (네이티브앱=' + isNativeApp() + ', 플러그인=' + !!plugin + ')';
    },
  };

  if (NATIVE) {
    // navigator.serial 이 없는 앱에서만 주입 (웹 동작 불변)
    try {
      if (!('serial' in navigator)) {
        Object.defineProperty(navigator, 'serial', {
          value: new NativeSerialShim(),
          writable: false,
          configurable: true,
        });
        console.log(TAG, '✅ navigator.serial 셔림 설치 완료 (Android OTG)');
      } else {
        console.log(TAG, 'ℹ️ navigator.serial 이 이미 존재 — 셔림 미설치(웹 경로 유지)');
      }
    } catch (e) {
      console.warn(TAG, '셔림 설치 실패:', e);
    }
  } else {
    console.log(TAG, 'ℹ️ 네이티브 OTG 비활성 — ' + api.diagnose());
  }

  window.NubidaSerial = api;
})();
