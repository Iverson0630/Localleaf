// Map/WeakMap upsert (TC39 "Map.prototype.getOrInsert" proposal).
//
// pdf.js 5.6.x calls getOrInsertComputed / getOrInsert in both the main thread (11 sites) and
// the worker (8 sites). Firefox ships them; Chrome 143 does not, where the viewer dies with
//     this[#fr].getOrInsertComputed is not a function
// Loading this module before pdf.js keeps the bundled viewer usable on those browsers. Each
// definition is guarded, so a browser that already implements the proposal is left untouched.
for (const Ctor of [Map, WeakMap]) {
  const proto = Ctor.prototype;
  if (typeof proto.getOrInsert !== 'function') {
    Object.defineProperty(proto, 'getOrInsert', {
      value: function getOrInsert(key, value) {
        if (!this.has(key)) {
          this.set(key, value);
        }
        return this.get(key);
      },
      writable: true, configurable: true, enumerable: false,
    });
  }
  if (typeof proto.getOrInsertComputed !== 'function') {
    Object.defineProperty(proto, 'getOrInsertComputed', {
      value: function getOrInsertComputed(key, callback) {
        if (typeof callback !== 'function') {
          throw new TypeError('getOrInsertComputed: callback must be callable');
        }
        if (!this.has(key)) {
          // Per the proposal the callback receives the key, and the entry is only inserted
          // after it returns, so a callback that mutates the map cannot be clobbered here.
          this.set(key, callback(key));
        }
        return this.get(key);
      },
      writable: true, configurable: true, enumerable: false,
    });
  }
}
