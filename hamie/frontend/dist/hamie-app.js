// node_modules/@lit/reactive-element/css-tag.js
var t = globalThis;
var e = t.ShadowRoot && (void 0 === t.ShadyCSS || t.ShadyCSS.nativeShadow) && "adoptedStyleSheets" in Document.prototype && "replace" in CSSStyleSheet.prototype;
var s = Symbol();
var o = /* @__PURE__ */ new WeakMap();
var n = class {
  constructor(t5, e6, o7) {
    if (this._$cssResult$ = true, o7 !== s) throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");
    this.cssText = t5, this.t = e6;
  }
  get styleSheet() {
    let t5 = this.o;
    const s6 = this.t;
    if (e && void 0 === t5) {
      const e6 = void 0 !== s6 && 1 === s6.length;
      e6 && (t5 = o.get(s6)), void 0 === t5 && ((this.o = t5 = new CSSStyleSheet()).replaceSync(this.cssText), e6 && o.set(s6, t5));
    }
    return t5;
  }
  toString() {
    return this.cssText;
  }
};
var r = (t5) => new n("string" == typeof t5 ? t5 : t5 + "", void 0, s);
var i = (t5, ...e6) => {
  const o7 = 1 === t5.length ? t5[0] : e6.reduce((e7, s6, o8) => e7 + ((t6) => {
    if (true === t6._$cssResult$) return t6.cssText;
    if ("number" == typeof t6) return t6;
    throw Error("Value passed to 'css' function must be a 'css' function result: " + t6 + ". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.");
  })(s6) + t5[o8 + 1], t5[0]);
  return new n(o7, t5, s);
};
var S = (s6, o7) => {
  if (e) s6.adoptedStyleSheets = o7.map((t5) => t5 instanceof CSSStyleSheet ? t5 : t5.styleSheet);
  else for (const e6 of o7) {
    const o8 = document.createElement("style"), n6 = t.litNonce;
    void 0 !== n6 && o8.setAttribute("nonce", n6), o8.textContent = e6.cssText, s6.appendChild(o8);
  }
};
var c = e ? (t5) => t5 : (t5) => t5 instanceof CSSStyleSheet ? ((t6) => {
  let e6 = "";
  for (const s6 of t6.cssRules) e6 += s6.cssText;
  return r(e6);
})(t5) : t5;

// node_modules/@lit/reactive-element/reactive-element.js
var { is: i2, defineProperty: e2, getOwnPropertyDescriptor: h, getOwnPropertyNames: r2, getOwnPropertySymbols: o2, getPrototypeOf: n2 } = Object;
var a = globalThis;
var c2 = a.trustedTypes;
var l = c2 ? c2.emptyScript : "";
var p = a.reactiveElementPolyfillSupport;
var d = (t5, s6) => t5;
var u = { toAttribute(t5, s6) {
  switch (s6) {
    case Boolean:
      t5 = t5 ? l : null;
      break;
    case Object:
    case Array:
      t5 = null == t5 ? t5 : JSON.stringify(t5);
  }
  return t5;
}, fromAttribute(t5, s6) {
  let i7 = t5;
  switch (s6) {
    case Boolean:
      i7 = null !== t5;
      break;
    case Number:
      i7 = null === t5 ? null : Number(t5);
      break;
    case Object:
    case Array:
      try {
        i7 = JSON.parse(t5);
      } catch (t6) {
        i7 = null;
      }
  }
  return i7;
} };
var f = (t5, s6) => !i2(t5, s6);
var b = { attribute: true, type: String, converter: u, reflect: false, useDefault: false, hasChanged: f };
Symbol.metadata ??= Symbol("metadata"), a.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
var y = class extends HTMLElement {
  static addInitializer(t5) {
    this._$Ei(), (this.l ??= []).push(t5);
  }
  static get observedAttributes() {
    return this.finalize(), this._$Eh && [...this._$Eh.keys()];
  }
  static createProperty(t5, s6 = b) {
    if (s6.state && (s6.attribute = false), this._$Ei(), this.prototype.hasOwnProperty(t5) && ((s6 = Object.create(s6)).wrapped = true), this.elementProperties.set(t5, s6), !s6.noAccessor) {
      const i7 = Symbol(), h6 = this.getPropertyDescriptor(t5, i7, s6);
      void 0 !== h6 && e2(this.prototype, t5, h6);
    }
  }
  static getPropertyDescriptor(t5, s6, i7) {
    const { get: e6, set: r6 } = h(this.prototype, t5) ?? { get() {
      return this[s6];
    }, set(t6) {
      this[s6] = t6;
    } };
    return { get: e6, set(s7) {
      const h6 = e6?.call(this);
      r6?.call(this, s7), this.requestUpdate(t5, h6, i7);
    }, configurable: true, enumerable: true };
  }
  static getPropertyOptions(t5) {
    return this.elementProperties.get(t5) ?? b;
  }
  static _$Ei() {
    if (this.hasOwnProperty(d("elementProperties"))) return;
    const t5 = n2(this);
    t5.finalize(), void 0 !== t5.l && (this.l = [...t5.l]), this.elementProperties = new Map(t5.elementProperties);
  }
  static finalize() {
    if (this.hasOwnProperty(d("finalized"))) return;
    if (this.finalized = true, this._$Ei(), this.hasOwnProperty(d("properties"))) {
      const t6 = this.properties, s6 = [...r2(t6), ...o2(t6)];
      for (const i7 of s6) this.createProperty(i7, t6[i7]);
    }
    const t5 = this[Symbol.metadata];
    if (null !== t5) {
      const s6 = litPropertyMetadata.get(t5);
      if (void 0 !== s6) for (const [t6, i7] of s6) this.elementProperties.set(t6, i7);
    }
    this._$Eh = /* @__PURE__ */ new Map();
    for (const [t6, s6] of this.elementProperties) {
      const i7 = this._$Eu(t6, s6);
      void 0 !== i7 && this._$Eh.set(i7, t6);
    }
    this.elementStyles = this.finalizeStyles(this.styles);
  }
  static finalizeStyles(s6) {
    const i7 = [];
    if (Array.isArray(s6)) {
      const e6 = new Set(s6.flat(1 / 0).reverse());
      for (const s7 of e6) i7.unshift(c(s7));
    } else void 0 !== s6 && i7.push(c(s6));
    return i7;
  }
  static _$Eu(t5, s6) {
    const i7 = s6.attribute;
    return false === i7 ? void 0 : "string" == typeof i7 ? i7 : "string" == typeof t5 ? t5.toLowerCase() : void 0;
  }
  constructor() {
    super(), this._$Ep = void 0, this.isUpdatePending = false, this.hasUpdated = false, this._$Em = null, this._$Ev();
  }
  _$Ev() {
    this._$ES = new Promise((t5) => this.enableUpdating = t5), this._$AL = /* @__PURE__ */ new Map(), this._$E_(), this.requestUpdate(), this.constructor.l?.forEach((t5) => t5(this));
  }
  addController(t5) {
    (this._$EO ??= /* @__PURE__ */ new Set()).add(t5), void 0 !== this.renderRoot && this.isConnected && t5.hostConnected?.();
  }
  removeController(t5) {
    this._$EO?.delete(t5);
  }
  _$E_() {
    const t5 = /* @__PURE__ */ new Map(), s6 = this.constructor.elementProperties;
    for (const i7 of s6.keys()) this.hasOwnProperty(i7) && (t5.set(i7, this[i7]), delete this[i7]);
    t5.size > 0 && (this._$Ep = t5);
  }
  createRenderRoot() {
    const t5 = this.shadowRoot ?? this.attachShadow(this.constructor.shadowRootOptions);
    return S(t5, this.constructor.elementStyles), t5;
  }
  connectedCallback() {
    this.renderRoot ??= this.createRenderRoot(), this.enableUpdating(true), this._$EO?.forEach((t5) => t5.hostConnected?.());
  }
  enableUpdating(t5) {
  }
  disconnectedCallback() {
    this._$EO?.forEach((t5) => t5.hostDisconnected?.());
  }
  attributeChangedCallback(t5, s6, i7) {
    this._$AK(t5, i7);
  }
  _$ET(t5, s6) {
    const i7 = this.constructor.elementProperties.get(t5), e6 = this.constructor._$Eu(t5, i7);
    if (void 0 !== e6 && true === i7.reflect) {
      const h6 = (void 0 !== i7.converter?.toAttribute ? i7.converter : u).toAttribute(s6, i7.type);
      this._$Em = t5, null == h6 ? this.removeAttribute(e6) : this.setAttribute(e6, h6), this._$Em = null;
    }
  }
  _$AK(t5, s6) {
    const i7 = this.constructor, e6 = i7._$Eh.get(t5);
    if (void 0 !== e6 && this._$Em !== e6) {
      const t6 = i7.getPropertyOptions(e6), h6 = "function" == typeof t6.converter ? { fromAttribute: t6.converter } : void 0 !== t6.converter?.fromAttribute ? t6.converter : u;
      this._$Em = e6;
      const r6 = h6.fromAttribute(s6, t6.type);
      this[e6] = r6 ?? this._$Ej?.get(e6) ?? r6, this._$Em = null;
    }
  }
  requestUpdate(t5, s6, i7, e6 = false, h6) {
    if (void 0 !== t5) {
      const r6 = this.constructor;
      if (false === e6 && (h6 = this[t5]), i7 ??= r6.getPropertyOptions(t5), !((i7.hasChanged ?? f)(h6, s6) || i7.useDefault && i7.reflect && h6 === this._$Ej?.get(t5) && !this.hasAttribute(r6._$Eu(t5, i7)))) return;
      this.C(t5, s6, i7);
    }
    false === this.isUpdatePending && (this._$ES = this._$EP());
  }
  C(t5, s6, { useDefault: i7, reflect: e6, wrapped: h6 }, r6) {
    i7 && !(this._$Ej ??= /* @__PURE__ */ new Map()).has(t5) && (this._$Ej.set(t5, r6 ?? s6 ?? this[t5]), true !== h6 || void 0 !== r6) || (this._$AL.has(t5) || (this.hasUpdated || i7 || (s6 = void 0), this._$AL.set(t5, s6)), true === e6 && this._$Em !== t5 && (this._$Eq ??= /* @__PURE__ */ new Set()).add(t5));
  }
  async _$EP() {
    this.isUpdatePending = true;
    try {
      await this._$ES;
    } catch (t6) {
      Promise.reject(t6);
    }
    const t5 = this.scheduleUpdate();
    return null != t5 && await t5, !this.isUpdatePending;
  }
  scheduleUpdate() {
    return this.performUpdate();
  }
  performUpdate() {
    if (!this.isUpdatePending) return;
    if (!this.hasUpdated) {
      if (this.renderRoot ??= this.createRenderRoot(), this._$Ep) {
        for (const [t7, s7] of this._$Ep) this[t7] = s7;
        this._$Ep = void 0;
      }
      const t6 = this.constructor.elementProperties;
      if (t6.size > 0) for (const [s7, i7] of t6) {
        const { wrapped: t7 } = i7, e6 = this[s7];
        true !== t7 || this._$AL.has(s7) || void 0 === e6 || this.C(s7, void 0, i7, e6);
      }
    }
    let t5 = false;
    const s6 = this._$AL;
    try {
      t5 = this.shouldUpdate(s6), t5 ? (this.willUpdate(s6), this._$EO?.forEach((t6) => t6.hostUpdate?.()), this.update(s6)) : this._$EM();
    } catch (s7) {
      throw t5 = false, this._$EM(), s7;
    }
    t5 && this._$AE(s6);
  }
  willUpdate(t5) {
  }
  _$AE(t5) {
    this._$EO?.forEach((t6) => t6.hostUpdated?.()), this.hasUpdated || (this.hasUpdated = true, this.firstUpdated(t5)), this.updated(t5);
  }
  _$EM() {
    this._$AL = /* @__PURE__ */ new Map(), this.isUpdatePending = false;
  }
  get updateComplete() {
    return this.getUpdateComplete();
  }
  getUpdateComplete() {
    return this._$ES;
  }
  shouldUpdate(t5) {
    return true;
  }
  update(t5) {
    this._$Eq &&= this._$Eq.forEach((t6) => this._$ET(t6, this[t6])), this._$EM();
  }
  updated(t5) {
  }
  firstUpdated(t5) {
  }
};
y.elementStyles = [], y.shadowRootOptions = { mode: "open" }, y[d("elementProperties")] = /* @__PURE__ */ new Map(), y[d("finalized")] = /* @__PURE__ */ new Map(), p?.({ ReactiveElement: y }), (a.reactiveElementVersions ??= []).push("2.1.2");

// node_modules/lit-html/lit-html.js
var t2 = globalThis;
var i3 = (t5) => t5;
var s2 = t2.trustedTypes;
var e3 = s2 ? s2.createPolicy("lit-html", { createHTML: (t5) => t5 }) : void 0;
var h2 = "$lit$";
var o3 = `lit$${Math.random().toFixed(9).slice(2)}$`;
var n3 = "?" + o3;
var r3 = `<${n3}>`;
var l2 = document;
var c3 = () => l2.createComment("");
var a2 = (t5) => null === t5 || "object" != typeof t5 && "function" != typeof t5;
var u2 = Array.isArray;
var d2 = (t5) => u2(t5) || "function" == typeof t5?.[Symbol.iterator];
var f2 = "[ 	\n\f\r]";
var v = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g;
var _ = /-->/g;
var m = />/g;
var p2 = RegExp(`>|${f2}(?:([^\\s"'>=/]+)(${f2}*=${f2}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`, "g");
var g = /'/g;
var $ = /"/g;
var y2 = /^(?:script|style|textarea|title)$/i;
var x = (t5) => (i7, ...s6) => ({ _$litType$: t5, strings: i7, values: s6 });
var b2 = x(1);
var w = x(2);
var T = x(3);
var E = Symbol.for("lit-noChange");
var A = Symbol.for("lit-nothing");
var C = /* @__PURE__ */ new WeakMap();
var P = l2.createTreeWalker(l2, 129);
function V(t5, i7) {
  if (!u2(t5) || !t5.hasOwnProperty("raw")) throw Error("invalid template strings array");
  return void 0 !== e3 ? e3.createHTML(i7) : i7;
}
var N = (t5, i7) => {
  const s6 = t5.length - 1, e6 = [];
  let n6, l3 = 2 === i7 ? "<svg>" : 3 === i7 ? "<math>" : "", c6 = v;
  for (let i8 = 0; i8 < s6; i8++) {
    const s7 = t5[i8];
    let a3, u5, d3 = -1, f4 = 0;
    for (; f4 < s7.length && (c6.lastIndex = f4, u5 = c6.exec(s7), null !== u5); ) f4 = c6.lastIndex, c6 === v ? "!--" === u5[1] ? c6 = _ : void 0 !== u5[1] ? c6 = m : void 0 !== u5[2] ? (y2.test(u5[2]) && (n6 = RegExp("</" + u5[2], "g")), c6 = p2) : void 0 !== u5[3] && (c6 = p2) : c6 === p2 ? ">" === u5[0] ? (c6 = n6 ?? v, d3 = -1) : void 0 === u5[1] ? d3 = -2 : (d3 = c6.lastIndex - u5[2].length, a3 = u5[1], c6 = void 0 === u5[3] ? p2 : '"' === u5[3] ? $ : g) : c6 === $ || c6 === g ? c6 = p2 : c6 === _ || c6 === m ? c6 = v : (c6 = p2, n6 = void 0);
    const x2 = c6 === p2 && t5[i8 + 1].startsWith("/>") ? " " : "";
    l3 += c6 === v ? s7 + r3 : d3 >= 0 ? (e6.push(a3), s7.slice(0, d3) + h2 + s7.slice(d3) + o3 + x2) : s7 + o3 + (-2 === d3 ? i8 : x2);
  }
  return [V(t5, l3 + (t5[s6] || "<?>") + (2 === i7 ? "</svg>" : 3 === i7 ? "</math>" : "")), e6];
};
var S2 = class _S {
  constructor({ strings: t5, _$litType$: i7 }, e6) {
    let r6;
    this.parts = [];
    let l3 = 0, a3 = 0;
    const u5 = t5.length - 1, d3 = this.parts, [f4, v3] = N(t5, i7);
    if (this.el = _S.createElement(f4, e6), P.currentNode = this.el.content, 2 === i7 || 3 === i7) {
      const t6 = this.el.content.firstChild;
      t6.replaceWith(...t6.childNodes);
    }
    for (; null !== (r6 = P.nextNode()) && d3.length < u5; ) {
      if (1 === r6.nodeType) {
        if (r6.hasAttributes()) for (const t6 of r6.getAttributeNames()) if (t6.endsWith(h2)) {
          const i8 = v3[a3++], s6 = r6.getAttribute(t6).split(o3), e7 = /([.?@])?(.*)/.exec(i8);
          d3.push({ type: 1, index: l3, name: e7[2], strings: s6, ctor: "." === e7[1] ? I : "?" === e7[1] ? L : "@" === e7[1] ? z : H }), r6.removeAttribute(t6);
        } else t6.startsWith(o3) && (d3.push({ type: 6, index: l3 }), r6.removeAttribute(t6));
        if (y2.test(r6.tagName)) {
          const t6 = r6.textContent.split(o3), i8 = t6.length - 1;
          if (i8 > 0) {
            r6.textContent = s2 ? s2.emptyScript : "";
            for (let s6 = 0; s6 < i8; s6++) r6.append(t6[s6], c3()), P.nextNode(), d3.push({ type: 2, index: ++l3 });
            r6.append(t6[i8], c3());
          }
        }
      } else if (8 === r6.nodeType) if (r6.data === n3) d3.push({ type: 2, index: l3 });
      else {
        let t6 = -1;
        for (; -1 !== (t6 = r6.data.indexOf(o3, t6 + 1)); ) d3.push({ type: 7, index: l3 }), t6 += o3.length - 1;
      }
      l3++;
    }
  }
  static createElement(t5, i7) {
    const s6 = l2.createElement("template");
    return s6.innerHTML = t5, s6;
  }
};
function M(t5, i7, s6 = t5, e6) {
  if (i7 === E) return i7;
  let h6 = void 0 !== e6 ? s6._$Co?.[e6] : s6._$Cl;
  const o7 = a2(i7) ? void 0 : i7._$litDirective$;
  return h6?.constructor !== o7 && (h6?._$AO?.(false), void 0 === o7 ? h6 = void 0 : (h6 = new o7(t5), h6._$AT(t5, s6, e6)), void 0 !== e6 ? (s6._$Co ??= [])[e6] = h6 : s6._$Cl = h6), void 0 !== h6 && (i7 = M(t5, h6._$AS(t5, i7.values), h6, e6)), i7;
}
var R = class {
  constructor(t5, i7) {
    this._$AV = [], this._$AN = void 0, this._$AD = t5, this._$AM = i7;
  }
  get parentNode() {
    return this._$AM.parentNode;
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  u(t5) {
    const { el: { content: i7 }, parts: s6 } = this._$AD, e6 = (t5?.creationScope ?? l2).importNode(i7, true);
    P.currentNode = e6;
    let h6 = P.nextNode(), o7 = 0, n6 = 0, r6 = s6[0];
    for (; void 0 !== r6; ) {
      if (o7 === r6.index) {
        let i8;
        2 === r6.type ? i8 = new k(h6, h6.nextSibling, this, t5) : 1 === r6.type ? i8 = new r6.ctor(h6, r6.name, r6.strings, this, t5) : 6 === r6.type && (i8 = new Z(h6, this, t5)), this._$AV.push(i8), r6 = s6[++n6];
      }
      o7 !== r6?.index && (h6 = P.nextNode(), o7++);
    }
    return P.currentNode = l2, e6;
  }
  p(t5) {
    let i7 = 0;
    for (const s6 of this._$AV) void 0 !== s6 && (void 0 !== s6.strings ? (s6._$AI(t5, s6, i7), i7 += s6.strings.length - 2) : s6._$AI(t5[i7])), i7++;
  }
};
var k = class _k {
  get _$AU() {
    return this._$AM?._$AU ?? this._$Cv;
  }
  constructor(t5, i7, s6, e6) {
    this.type = 2, this._$AH = A, this._$AN = void 0, this._$AA = t5, this._$AB = i7, this._$AM = s6, this.options = e6, this._$Cv = e6?.isConnected ?? true;
  }
  get parentNode() {
    let t5 = this._$AA.parentNode;
    const i7 = this._$AM;
    return void 0 !== i7 && 11 === t5?.nodeType && (t5 = i7.parentNode), t5;
  }
  get startNode() {
    return this._$AA;
  }
  get endNode() {
    return this._$AB;
  }
  _$AI(t5, i7 = this) {
    t5 = M(this, t5, i7), a2(t5) ? t5 === A || null == t5 || "" === t5 ? (this._$AH !== A && this._$AR(), this._$AH = A) : t5 !== this._$AH && t5 !== E && this._(t5) : void 0 !== t5._$litType$ ? this.$(t5) : void 0 !== t5.nodeType ? this.T(t5) : d2(t5) ? this.k(t5) : this._(t5);
  }
  O(t5) {
    return this._$AA.parentNode.insertBefore(t5, this._$AB);
  }
  T(t5) {
    this._$AH !== t5 && (this._$AR(), this._$AH = this.O(t5));
  }
  _(t5) {
    this._$AH !== A && a2(this._$AH) ? this._$AA.nextSibling.data = t5 : this.T(l2.createTextNode(t5)), this._$AH = t5;
  }
  $(t5) {
    const { values: i7, _$litType$: s6 } = t5, e6 = "number" == typeof s6 ? this._$AC(t5) : (void 0 === s6.el && (s6.el = S2.createElement(V(s6.h, s6.h[0]), this.options)), s6);
    if (this._$AH?._$AD === e6) this._$AH.p(i7);
    else {
      const t6 = new R(e6, this), s7 = t6.u(this.options);
      t6.p(i7), this.T(s7), this._$AH = t6;
    }
  }
  _$AC(t5) {
    let i7 = C.get(t5.strings);
    return void 0 === i7 && C.set(t5.strings, i7 = new S2(t5)), i7;
  }
  k(t5) {
    u2(this._$AH) || (this._$AH = [], this._$AR());
    const i7 = this._$AH;
    let s6, e6 = 0;
    for (const h6 of t5) e6 === i7.length ? i7.push(s6 = new _k(this.O(c3()), this.O(c3()), this, this.options)) : s6 = i7[e6], s6._$AI(h6), e6++;
    e6 < i7.length && (this._$AR(s6 && s6._$AB.nextSibling, e6), i7.length = e6);
  }
  _$AR(t5 = this._$AA.nextSibling, s6) {
    for (this._$AP?.(false, true, s6); t5 !== this._$AB; ) {
      const s7 = i3(t5).nextSibling;
      i3(t5).remove(), t5 = s7;
    }
  }
  setConnected(t5) {
    void 0 === this._$AM && (this._$Cv = t5, this._$AP?.(t5));
  }
};
var H = class {
  get tagName() {
    return this.element.tagName;
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  constructor(t5, i7, s6, e6, h6) {
    this.type = 1, this._$AH = A, this._$AN = void 0, this.element = t5, this.name = i7, this._$AM = e6, this.options = h6, s6.length > 2 || "" !== s6[0] || "" !== s6[1] ? (this._$AH = Array(s6.length - 1).fill(new String()), this.strings = s6) : this._$AH = A;
  }
  _$AI(t5, i7 = this, s6, e6) {
    const h6 = this.strings;
    let o7 = false;
    if (void 0 === h6) t5 = M(this, t5, i7, 0), o7 = !a2(t5) || t5 !== this._$AH && t5 !== E, o7 && (this._$AH = t5);
    else {
      const e7 = t5;
      let n6, r6;
      for (t5 = h6[0], n6 = 0; n6 < h6.length - 1; n6++) r6 = M(this, e7[s6 + n6], i7, n6), r6 === E && (r6 = this._$AH[n6]), o7 ||= !a2(r6) || r6 !== this._$AH[n6], r6 === A ? t5 = A : t5 !== A && (t5 += (r6 ?? "") + h6[n6 + 1]), this._$AH[n6] = r6;
    }
    o7 && !e6 && this.j(t5);
  }
  j(t5) {
    t5 === A ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, t5 ?? "");
  }
};
var I = class extends H {
  constructor() {
    super(...arguments), this.type = 3;
  }
  j(t5) {
    this.element[this.name] = t5 === A ? void 0 : t5;
  }
};
var L = class extends H {
  constructor() {
    super(...arguments), this.type = 4;
  }
  j(t5) {
    this.element.toggleAttribute(this.name, !!t5 && t5 !== A);
  }
};
var z = class extends H {
  constructor(t5, i7, s6, e6, h6) {
    super(t5, i7, s6, e6, h6), this.type = 5;
  }
  _$AI(t5, i7 = this) {
    if ((t5 = M(this, t5, i7, 0) ?? A) === E) return;
    const s6 = this._$AH, e6 = t5 === A && s6 !== A || t5.capture !== s6.capture || t5.once !== s6.once || t5.passive !== s6.passive, h6 = t5 !== A && (s6 === A || e6);
    e6 && this.element.removeEventListener(this.name, this, s6), h6 && this.element.addEventListener(this.name, this, t5), this._$AH = t5;
  }
  handleEvent(t5) {
    "function" == typeof this._$AH ? this._$AH.call(this.options?.host ?? this.element, t5) : this._$AH.handleEvent(t5);
  }
};
var Z = class {
  constructor(t5, i7, s6) {
    this.element = t5, this.type = 6, this._$AN = void 0, this._$AM = i7, this.options = s6;
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  _$AI(t5) {
    M(this, t5);
  }
};
var j = { M: h2, P: o3, A: n3, C: 1, L: N, R, D: d2, V: M, I: k, H, N: L, U: z, B: I, F: Z };
var B = t2.litHtmlPolyfillSupport;
B?.(S2, k), (t2.litHtmlVersions ??= []).push("3.3.3");
var D = (t5, i7, s6) => {
  const e6 = s6?.renderBefore ?? i7;
  let h6 = e6._$litPart$;
  if (void 0 === h6) {
    const t6 = s6?.renderBefore ?? null;
    e6._$litPart$ = h6 = new k(i7.insertBefore(c3(), t6), t6, void 0, s6 ?? {});
  }
  return h6._$AI(t5), h6;
};

// node_modules/lit-element/lit-element.js
var s3 = globalThis;
var i4 = class extends y {
  constructor() {
    super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
  }
  createRenderRoot() {
    const t5 = super.createRenderRoot();
    return this.renderOptions.renderBefore ??= t5.firstChild, t5;
  }
  update(t5) {
    const r6 = this.render();
    this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(t5), this._$Do = D(r6, this.renderRoot, this.renderOptions);
  }
  connectedCallback() {
    super.connectedCallback(), this._$Do?.setConnected(true);
  }
  disconnectedCallback() {
    super.disconnectedCallback(), this._$Do?.setConnected(false);
  }
  render() {
    return E;
  }
};
i4._$litElement$ = true, i4["finalized"] = true, s3.litElementHydrateSupport?.({ LitElement: i4 });
var o4 = s3.litElementPolyfillSupport;
o4?.({ LitElement: i4 });
(s3.litElementVersions ??= []).push("4.2.2");

// hamie/frontend/design/tokens.css
var tokens_default = `/**
 * HAMIE UI 3.0 \u2014 color tokens.
 *
 * Reconstructed from design/figma/src/styles/theme.css (the only theme
 * Figma actually designed \u2014 its light-mode block is Figma Make's untouched
 * factory default, not a HAMIE decision, so light mode below is a genuine
 * native re-design of the same semantics, not a port).
 *
 * Every token prefers a real Home Assistant CSS custom property over a
 * literal value, per the "never hardcode what HA already supplies" rule.
 * Names were verified to exist in the installed hass_frontend package for
 * BOTH the HA 2025.8.0 floor and the 2026.7 current-target release before
 * use here \u2014 none are assumed from memory.
 *
 * --ha-color-fill-*-resting and --ha-color-border-* are present at the
 * 2025.8.0 floor and used directly with no fallback needed. The classic
 * vars (--primary-color, --card-background-color, --rgb-*, etc.) are
 * stable across all supported HA releases.
 */

:host {
  /* Surfaces */
  --hamie-surface-app: var(--primary-background-color);
  --hamie-surface-card: var(--card-background-color);
  --hamie-surface-sidebar: var(--sidebar-background-color);
  --hamie-surface-raised: var(--ha-color-fill-neutral-quiet-resting);
  --hamie-surface-hover: var(--ha-color-fill-neutral-normal-resting);

  /* Text */
  --hamie-text-primary: var(--primary-text-color);
  --hamie-text-secondary: var(--secondary-text-color);
  --hamie-text-disabled: var(--disabled-text-color);
  --hamie-text-sidebar: var(--sidebar-text-color);
  --hamie-text-sidebar-selected: var(--sidebar-selected-text-color);

  /* Borders / hairlines \u2014 replaces Figma's border-white/[0.04..0.08] overlay ladder */
  --hamie-border-hairline: var(--ha-color-border-quiet);
  --hamie-border-normal: var(--ha-color-border-normal);
  --hamie-border-loud: var(--ha-color-border-loud);

  /* Accent (Figma's blue-600 primary action color) */
  --hamie-accent: var(--primary-color);
  --hamie-accent-fill-quiet: var(--ha-color-fill-primary-quiet-resting);
  --hamie-accent-fill-loud: var(--ha-color-fill-primary-loud-resting);
  --hamie-accent-icon: var(--sidebar-selected-icon-color);
  --hamie-accent-on: var(--text-primary-color); /* text/icon color for use atop a loud accent fill */

  /*
   * Status semantics \u2014 Figma's \`Status\` union (App.tsx STATUS const):
   * healthy / warning / critical / info / unknown / active / offline /
   * running / idle. Each becomes a foreground color + a quiet fill,
   * matching Figma's dot+text+bg-tint Chip composition exactly.
   */
  --hamie-status-healthy: var(--success-color);
  --hamie-status-healthy-fill: var(--ha-color-fill-success-quiet-resting);
  --hamie-status-warning: var(--warning-color);
  --hamie-status-warning-fill: var(--ha-color-fill-warning-quiet-resting);
  --hamie-status-critical: var(--error-color);
  --hamie-status-critical-fill: var(--ha-color-fill-danger-quiet-resting);
  --hamie-status-info: var(--info-color);
  --hamie-status-info-fill: var(--ha-color-fill-primary-quiet-resting);
  --hamie-status-unknown: var(--disabled-text-color);
  --hamie-status-unknown-fill: var(--ha-color-fill-neutral-quiet-resting);
  --hamie-status-active: var(--info-color);
  --hamie-status-active-fill: var(--ha-color-fill-primary-quiet-resting);
  --hamie-status-offline: var(--disabled-text-color);
  --hamie-status-offline-fill: var(--ha-color-fill-neutral-quiet-resting);
  --hamie-status-running: var(--success-color);
  --hamie-status-running-fill: var(--ha-color-fill-success-quiet-resting);
  --hamie-status-idle: var(--disabled-text-color);
  --hamie-status-idle-fill: var(--ha-color-fill-neutral-quiet-resting);
  /* "Needs evidence" (maintenance-console redesign): no HA semantic
   * token maps to purple, same as the Overview activity feed's existing
   * AI-activity dot -- reuses that exact literal for consistency. */
  --hamie-status-evidence: #a78bfa;
  --hamie-status-evidence-fill: rgba(167, 139, 250, 0.16);

  /* Priority (Recommendations screen: high / medium / low) */
  --hamie-priority-high: var(--error-color);
  --hamie-priority-high-fill: var(--ha-color-fill-danger-quiet-resting);
  --hamie-priority-medium: var(--warning-color);
  --hamie-priority-medium-fill: var(--ha-color-fill-warning-quiet-resting);
  --hamie-priority-low: var(--disabled-text-color);
  --hamie-priority-low-fill: var(--ha-color-fill-neutral-quiet-resting);

  /* Destructive actions (Figma's Btn variant="danger") */
  --hamie-danger: var(--error-color);
  --hamie-danger-fill: var(--ha-color-fill-danger-quiet-resting);
  --hamie-danger-border: var(--ha-color-border-danger-normal);
}
`;

// hamie/frontend/design/typography.css
var typography_default = `/**
 * HAMIE UI 3.0 \u2014 typography tokens.
 *
 * Figma (fonts.css) loads Inter + JetBrains Mono from Google Fonts and
 * hardcodes an idiosyncratic px scale (10/11/13/22px, mixed with a few
 * Tailwind defaults). We deliberately do not port the Google Fonts import
 * or the literal px values: HA already ships a font-size/family/weight
 * system (--ha-font-*), verified present at both the HA 2025.8.0 floor and
 * the 2026.7 current-target release, and --ha-font-size-scale makes every
 * size respect the user's HA-wide font-scaling accessibility setting \u2014
 * something Figma's fixed px values cannot do. Loading a second font
 * family from Google Fonts would also fight whatever the active HA theme
 * declares. This is a "Home Assistant platform limitation" + accessibility
 * deviation per the similarity rules, not a stylistic preference.
 *
 * Post-deployment correction: the first mapping below snapped each Figma
 * size to the *nearest* HA token by raw pixel proximity (Figma's dominant
 * 11px body text landed on HA's xs=10px), which reproduced Figma's dense,
 * small-text aesthetic instead of HA's own. Real usage counted directly
 * across HA's own frontend_latest bundle tells a different story: HA's
 * single most common font-size across its entire codebase is
 * --ha-font-size-m (14px, ~204 uses), with xs (10px) the *least* common
 * of the main tiers (~62 uses) -- HA reserves its smallest sizes for
 * captions/badges, not primary content. HAMIE had it backwards: 141 of
 * its own primary-content call sites (table cells, card body text,
 * recommendation text, dialog copy) were on the old --hamie-text-micro
 * (10px), making ordinary content render at HA's least-used, caption-only
 * size. The scale below is retuned so HAMIE's dominant body-text tier
 * lands on HA's own dominant size, with a genuinely small --hamie-text-
 * caption tier introduced for the minority of call sites (uppercase
 * tracked column headers, tiny numeric badges) that legitimately should
 * stay small -- this is a token-correctness fix, not a redesign; no
 * layout, component, or visual structure changes.
 */

:host {
  /*
   * --ha-font-family-{body,code,heading} are verified present at the
   * 2025.8.0 floor, so these literal fallbacks are a last-resort safety
   * net only \u2014 they should never actually engage on a supported HA
   * version. No unverified intermediate HA variable is referenced here.
   */
  --hamie-font-body: var(--ha-font-family-body, system-ui, sans-serif);
  --hamie-font-code: var(--ha-font-family-code, monospace);
  --hamie-font-heading: var(--ha-font-family-heading, var(--hamie-font-body));

  --hamie-weight-normal: var(--ha-font-weight-normal, 400);
  --hamie-weight-medium: var(--ha-font-weight-medium, 500);
  --hamie-weight-bold: var(--ha-font-weight-bold, 700);

  /* Genuinely small text only: uppercase tracked column/section labels,
   * tiny numeric badges (e.g. "priority 3"). HA's own least-used tier --
   * reserved for captions, never primary content. */
  --hamie-text-caption: var(--ha-font-size-xs, 10px);
  /* Secondary/meta text: timestamps, helper descriptions, sub-labels
   * under a primary value. HA's own commonly-used secondary-text size. */
  --hamie-text-micro: var(--ha-font-size-s, 12px);
  /* Primary/body text -- table cells, card content, dialog copy, form
   * inputs. Matches HA's own single most common font-size across its
   * entire frontend (--ha-font-size-m, ~204 uses, its dominant choice). */
  --hamie-text-small: var(--ha-font-size-m, 14px);
  /* Headings (h1, section titles) -- one full HA step above body text now
   * that body text itself moved up to m. */
  --hamie-text-base: var(--ha-font-size-l, 16px);
  /* Figma's large metric-value size (22px) */
  --hamie-text-metric: var(--ha-font-size-2xl, 24px);
  /* Figma's HealthArc score size (text-3xl, 30px) */
  --hamie-text-display: var(--ha-font-size-3xl, 28px);

  --hamie-tracking-label: 0.05em; /* Figma's tracking-wider on uppercase labels; HA has no equivalent token */
}
`;

// hamie/frontend/design/spacing.css
var spacing_default = "/**\n * HAMIE UI 3.0 \u2014 spacing & radius tokens.\n *\n * --ha-space-* and --ha-border-radius-* were verified ABSENT from the HA\n * 2025.8.0 floor's frontend bundle (checked directly against the installed\n * hass_frontend package) and present in the 2026.7 current-target bundle \u2014\n * they were introduced by Home Assistant in a later release. Every use\n * below therefore carries an explicit var() fallback, using the exact\n * literal pixel values HA itself assigns to these tokens on newer\n * releases (also read directly out of the installed frontend bundle, not\n * guessed), so the floor lane renders identically to what the token would\n * have produced.\n *\n * Fallback values only ever apply on HA < the release that introduced\n * these tokens; on any HA that has them, the real token wins and the\n * design progressively enhances (e.g. respects the user's density theme\n * setting, if HA ever exposes one through these tokens).\n */\n\n:host {\n  --hamie-space-1: var(--ha-space-1, 4px);\n  --hamie-space-2: var(--ha-space-2, 8px);\n  --hamie-space-3: var(--ha-space-3, 12px);\n  --hamie-space-4: var(--ha-space-4, 16px);\n  --hamie-space-5: var(--ha-space-5, 20px);\n  --hamie-space-6: var(--ha-space-6, 24px);\n  --hamie-space-7: var(--ha-space-7, 28px);\n  --hamie-space-8: var(--ha-space-8, 32px);\n\n  /* Figma's fussier sub-token gaps (2px, 6px, 10px) have no HA equivalent\n   * at any scale step; kept as literals since there is nothing to map to. */\n  --hamie-space-half: 2px;\n  --hamie-space-1-5: 6px;\n  --hamie-space-2-5: 10px;\n\n  --hamie-radius-sm: var(--ha-border-radius-sm, 4px);\n  --hamie-radius-md: var(--ha-border-radius-md, 8px);\n  --hamie-radius-lg: var(--ha-border-radius-lg, 12px);\n  --hamie-radius-pill: var(--ha-border-radius-pill, 9999px);\n  --hamie-radius-circle: var(--ha-border-radius-circle, 50%);\n\n  /* Fixed layout dimensions carried over exactly from Figma (App.tsx) */\n  --hamie-sidebar-width: var(--ha-sidebar-width, 196px);\n  --hamie-content-max-narrow: 42rem;  /* Settings: max-w-2xl */\n  --hamie-content-max-medium: 56rem;  /* Recommendations: max-w-4xl */\n  --hamie-content-max-wide: 64rem;    /* Overview/Health/AI/Findings/Dependencies: max-w-5xl */\n}\n";

// hamie/frontend/design/motion.css
var motion_default = '/**\n * HAMIE UI 3.0 \u2014 motion tokens.\n *\n * Figma\'s motion is minimal: implicit Tailwind `transition-colors`\n * (150ms, default easing) on nearly every interactive element, plus one\n * explicit "stroke-dasharray 0.8s ease" on the HealthArc score fill.\n *\n * --ha-animation-duration-* was verified ABSENT at the HA 2025.8.0 floor\n * and present on 2026.7 (values read directly from the installed\n * frontend bundle: fast=.15s, normal=.25s, slow=.35s) \u2014 fallbacks below\n * use those exact real values, not guesses.\n *\n * `prefers-reduced-motion` is handled once here so every component that\n * consumes these tokens gets it for free, rather than each component\n * re-implementing the media query \u2014 required for the accessibility pass\n * regardless of Figma (which has no reduced-motion handling at all).\n */\n\n:host {\n  --hamie-motion-fast: var(--ha-animation-duration-fast, 0.15s);\n  --hamie-motion-normal: var(--ha-animation-duration-normal, 0.25s);\n  --hamie-motion-slow: var(--ha-animation-duration-slow, 0.35s);\n  --hamie-motion-ease: ease;\n}\n\n@media (prefers-reduced-motion: reduce) {\n  :host {\n    --hamie-motion-fast: 1ms;\n    --hamie-motion-normal: 1ms;\n    --hamie-motion-slow: 1ms;\n  }\n}\n';

// hamie/frontend/design/elevation.css
var elevation_default = "/**\n * HAMIE UI 3.0 \u2014 elevation tokens.\n *\n * Figma's primary elevation method is NOT shadows \u2014 it's a flat card\n * (`bg-[#1a1d24] border border-white/[0.06]`) with opacity-layered\n * backgrounds for hover/active states. Real box-shadows appear exactly\n * twice: the sidebar logo mark (`shadow-lg shadow-blue-600/30`) and the\n * chart tooltip popover (`shadow-xl`). This token file reflects that same\n * restraint \u2014 most surfaces should use --hamie-border-* from tokens.css,\n * not a shadow, to stay faithful to the flat/bordered look.\n *\n * --ha-box-shadow-* was verified ABSENT at the HA 2025.8.0 floor and\n * present on 2026.7. Its value is theme-conditional (HA defines different\n * numbers for light/dark), so no single \"real value\" fallback exists to\n * copy; the fallback below is a neutral, theme-agnostic approximation\n * used only pre-introduction of the token.\n */\n\n:host {\n  --hamie-elevation-card: none; /* cards are flat + bordered, not shadowed */\n  --hamie-elevation-popover: var(--ha-box-shadow-m, 0 3px 6px -1px rgba(0, 0, 0, 0.15), 0 8px 16px -2px rgba(0, 0, 0, 0.2));\n  --hamie-elevation-accent: var(--ha-box-shadow-s, 0 1px 2px 0 rgba(0, 0, 0, 0.1), 0 1px 3px 0 rgba(0, 0, 0, 0.15));\n}\n";

// hamie/frontend/design/index.js
var designTokens = i`
  ${r(tokens_default)}
  ${r(typography_default)}
  ${r(spacing_default)}
  ${r(motion_default)}
  ${r(elevation_default)}
`;

// hamie/frontend/format.js
function relativeTime(isoString) {
  if (!isoString) return "";
  const then = new Date(isoString).getTime();
  const diffSeconds = Math.max(0, Math.round((Date.now() - then) / 1e3));
  if (diffSeconds < 60) return "Just now";
  const minutes = Math.round(diffSeconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}
function timeOfDayGreeting(date = /* @__PURE__ */ new Date()) {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}
function safeRelativeTime(isoString, { maximumAgeDays = 365, futureSkewSeconds = 300 } = {}) {
  if (!isoString) return "Unknown";
  const timestamp = new Date(isoString).getTime();
  if (!Number.isFinite(timestamp)) return "Unknown";
  const ageMilliseconds = Date.now() - timestamp;
  if (ageMilliseconds < -futureSkewSeconds * 1e3) return "Unknown";
  if (ageMilliseconds > maximumAgeDays * 864e5) return "Unknown";
  return relativeTime(isoString);
}

// hamie/frontend/components/hamie-status.js
var LABELS = {
  healthy: "Healthy",
  warning: "Warning",
  critical: "Critical",
  info: "Info",
  unknown: "Unknown",
  active: "Active",
  offline: "Offline",
  running: "Running",
  idle: "Idle"
};
var SEVERITY_ICON = {
  critical: "mdi:alert-circle",
  warning: "mdi:alert",
  info: "mdi:information"
};
var PRIORITY_LABELS = { high: "High", medium: "Medium", low: "Low" };
var HamieStatus = class extends i4 {
  static properties = {
    status: { type: String },
    // Status value, or Severity/priority value depending on variant
    label: { type: String },
    variant: { type: String }
    // "chip" (default) | "severity" | "priority" | "dot"
  };
  static styles = i`
    :host {
      display: inline-flex;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      padding: var(--hamie-space-half) var(--hamie-space-2);
      border-radius: var(--hamie-radius-pill);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
    }
    .priority {
      display: inline-flex;
      align-items: center;
      padding: var(--hamie-space-half) var(--hamie-space-1-5);
      border-radius: var(--hamie-radius-sm);
      font-size: var(--hamie-text-caption);
      font-weight: var(--hamie-weight-bold);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
    }
    .dot-row {
      display: inline-flex;
      align-items: center;
      gap: var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .dot {
      width: 6px;
      height: 6px;
      border-radius: var(--hamie-radius-circle);
      flex-shrink: 0;
    }
    .severity {
      display: inline-flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      text-transform: capitalize;
    }
    ha-icon {
      --mdc-icon-size: 14px;
      flex-shrink: 0;
    }
  `;
  render() {
    const status = this.status || "unknown";
    if (this.variant === "severity") {
      return b2`
        <span class="severity" style="color: var(--hamie-status-${status}, var(--hamie-status-unknown))">
          <ha-icon icon=${SEVERITY_ICON[status] || "mdi:information"}></ha-icon>
          ${this.label || status}
        </span>
      `;
    }
    if (this.variant === "priority") {
      return b2`
        <span
          class="priority"
          style="background: var(--hamie-priority-${status}-fill, var(--hamie-priority-low-fill)); color: var(--hamie-priority-${status}, var(--hamie-priority-low))"
        >
          ${this.label || PRIORITY_LABELS[status] || status}
        </span>
      `;
    }
    if (this.variant === "dot") {
      return b2`
        <span class="dot-row">
          <span class="dot" style="background: var(--hamie-status-${status}, var(--hamie-status-unknown))"></span>
          ${this.label || LABELS[status] || status}
        </span>
      `;
    }
    return b2`
      <span
        class="chip"
        style="background: var(--hamie-status-${status}-fill, var(--hamie-status-unknown-fill)); color: var(--hamie-status-${status}, var(--hamie-status-unknown))"
      >
        <span class="dot" style="background: var(--hamie-status-${status}, var(--hamie-status-unknown))"></span>
        ${this.label || LABELS[status] || status}
      </span>
    `;
  }
};
if (!customElements.get("hamie-status")) {
  customElements.define("hamie-status", HamieStatus);
}

// hamie/frontend/components/hamie-sidebar.js
var HamieSidebar = class extends i4 {
  static properties = {
    items: { type: Array },
    activeId: { type: String },
    statusText: { type: String },
    statusOk: { type: Boolean },
    _advancedExpanded: { state: true }
  };
  static styles = i`
    :host {
      display: flex; flex-direction: column; width: var(--hamie-sidebar-width);
      flex-shrink: 0; height: 100%; box-sizing: border-box;
      background: var(--hamie-surface-sidebar); border-right: 1px solid var(--hamie-border-hairline);
    }
    .logo {
      display: flex; align-items: center; gap: var(--hamie-space-2-5);
      padding: var(--hamie-space-4); border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .mark {
      display: flex; align-items: center; justify-content: center; flex-shrink: 0;
      width: 28px; height: 28px; border-radius: var(--hamie-radius-md);
      background: var(--hamie-accent-fill-loud);
    }
    .name {
      color: var(--hamie-text-primary); font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium); line-height: 1;
    }
    .version {
      margin-top: 2px; color: var(--hamie-text-secondary);
      font: var(--hamie-text-caption)/1 var(--hamie-font-code);
    }
    nav {
      display: flex; flex: 1; flex-direction: column; gap: 2px;
      overflow-y: auto; padding: var(--hamie-space-3) var(--hamie-space-2);
    }
    button {
      display: flex; align-items: center; gap: var(--hamie-space-2-5);
      width: 100%; box-sizing: border-box; padding: 7px var(--hamie-space-2-5);
      border: 0; border-radius: var(--hamie-radius-md);
      color: var(--hamie-text-secondary); background: transparent; cursor: pointer;
      font: var(--hamie-weight-medium) var(--hamie-text-small)/1.3 inherit; text-align: left;
    }
    button:hover { color: var(--hamie-text-primary); background: var(--hamie-surface-hover); }
    button[aria-current="page"] { color: var(--hamie-accent); background: var(--hamie-accent-fill-quiet); }
    button:focus-visible { outline: 2px solid var(--hamie-accent); outline-offset: -2px; }
    .label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .badge {
      padding: 1px var(--hamie-space-1-5); border-radius: var(--hamie-radius-pill);
      color: var(--hamie-accent-on); background: var(--hamie-accent-fill-loud);
      font-size: var(--hamie-text-micro); font-weight: var(--hamie-weight-bold);
    }
    .children { display: grid; gap: 2px; }
    .children button { padding-left: calc(var(--hamie-space-2-5) + 24px); }
    .chevron { margin-left: auto; }
    ha-icon { --mdc-icon-size: 14px; flex-shrink: 0; }
    .footer { padding: var(--hamie-space-3); border-top: 1px solid var(--hamie-border-hairline); }
    .divider { height: 1px; margin: var(--hamie-space-2) var(--hamie-space-2-5); background: var(--hamie-border-hairline); border: 0; }
  `;
  constructor() {
    super();
    this._advancedExpanded = sessionStorage.getItem("hamieAdvancedExpanded") === "true";
  }
  updated(changed) {
    const activeIsAdvanced = (this.items || []).some((item) => item.children?.some((child) => child.id === this.activeId));
    if (changed.has("activeId") && activeIsAdvanced && !this._advancedExpanded) {
      this._advancedExpanded = true;
      sessionStorage.setItem("hamieAdvancedExpanded", "true");
    }
  }
  _onNavigate(id) {
    this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id }, bubbles: true, composed: true }));
  }
  _toggleAdvanced() {
    this._advancedExpanded = !this._advancedExpanded;
    sessionStorage.setItem("hamieAdvancedExpanded", String(this._advancedExpanded));
  }
  _renderItem(item) {
    if (!item.children) return b2`
      <button aria-current=${item.id === this.activeId ? "page" : "false"} @click=${() => this._onNavigate(item.id)}>
        <ha-icon icon=${item.icon}></ha-icon>
        <span class="label">${item.label}</span>
        ${item.badge ? b2`<span class="badge">${item.badge}</span>` : null}
      </button>`;
    return b2`
      <button aria-expanded=${String(this._advancedExpanded)} aria-controls="hamie-advanced-navigation" @click=${this._toggleAdvanced}>
        <ha-icon icon=${item.icon}></ha-icon>
        <span class="label">${item.label}</span>
        ${item.badge ? b2`<span class="badge">${item.badge}</span>` : null}
        <ha-icon class="chevron" icon=${this._advancedExpanded ? "mdi:chevron-up" : "mdi:chevron-down"}></ha-icon>
      </button>
      ${this._advancedExpanded ? b2`
        <div id="hamie-advanced-navigation" class="children" role="group" aria-label="Advanced">
          ${item.children.map((child) => b2`
            <button aria-current=${child.id === this.activeId ? "page" : "false"} @click=${() => this._onNavigate(child.id)}>
              <ha-icon icon=${child.icon}></ha-icon>
              <span class="label">${child.label}</span>
            </button>`)}
        </div>` : null}`;
  }
  render() {
    return b2`
      <div class="logo">
        <div class="mark"><ha-icon icon="mdi:shield-home"></ha-icon></div>
        <div><div class="name">HAMIE</div><div class="version"><slot name="version"></slot></div></div>
      </div>
      <nav aria-label="HAMIE sections">
        ${(this.items || []).map(
      (item) => b2`${item.dividerBefore ? b2`<hr class="divider" role="separator" />` : null}${this._renderItem(item)}`
    )}
      </nav>
      <div class="footer">
        <hamie-status variant="dot" status=${this.statusOk ? "healthy" : "warning"} label=${this.statusText}></hamie-status>
      </div>`;
  }
};
if (!customElements.get("hamie-sidebar")) {
  customElements.define("hamie-sidebar", HamieSidebar);
}

// hamie/frontend/components/hamie-empty.js
var TONE_ICON = {
  neutral: "mdi:check-circle-outline",
  positive: "mdi:check-circle",
  unavailable: "mdi:information-outline"
};
var HamieEmpty = class extends i4 {
  static properties = {
    tone: { type: String },
    // "neutral" (default) | "positive" | "unavailable"
    heading: { type: String },
    description: { type: String }
  };
  static styles = i`
    :host {
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      padding: var(--hamie-space-8) var(--hamie-space-4);
    }
    ha-icon {
      --mdc-icon-size: 24px;
      margin-bottom: var(--hamie-space-3);
    }
    :host([tone="positive"]) ha-icon {
      color: var(--hamie-status-healthy);
    }
    :host(:not([tone])) ha-icon,
    :host([tone="neutral"]) ha-icon {
      color: var(--hamie-text-secondary);
    }
    :host([tone="unavailable"]) ha-icon {
      color: var(--hamie-text-disabled);
    }
    .heading {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .description {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      max-width: 32em;
    }
  `;
  render() {
    const tone = this.tone || "neutral";
    return b2`
      <ha-icon icon=${TONE_ICON[tone]}></ha-icon>
      <p class="heading">${this.heading}</p>
      ${this.description ? b2`<p class="description">${this.description}</p>` : null}
    `;
  }
};
if (!customElements.get("hamie-empty")) {
  customElements.define("hamie-empty", HamieEmpty);
}

// hamie/frontend/errors.js
var KNOWN_CODES = {
  stale_revision: "This changed since it was loaded. Refresh and try again.",
  configuration_failed: "That configuration change could not be saved.",
  // Remediation Review Queue codes (presentation/remediation_api.py's
  // RemediationServiceError.code). Sent as `(err.code, err.message)`,
  // matching _structured_error's typed-business-error convention, not
  // the generic hamie_error + classified-text convention above -- so
  // these are matched on `code` here rather than via KNOWN_MESSAGES.
  remediation_not_found: "That recommendation or plan could not be found. Refresh the queue.",
  remediation_unsupported: "HAMIE does not support automated remediation for this recommendation yet.",
  remediation_plan_stale: "This plan has changed since it was last reviewed. Refresh and try again.",
  remediation_preview_stale: "Generate a fresh preview before approving.",
  remediation_snooze_invalid: "This proposal cannot be snoozed in its current state. Refresh the queue.",
  remediation_approval_missing: "That approval could not be found. Refresh the queue.",
  remediation_approval_invalid: "This approval is not valid for that action. Refresh and try again.",
  remediation_approval_expired: "This approval has expired. Approve again to continue.",
  remediation_approval_revoked: "This approval was revoked. Approve again to continue.",
  remediation_precondition_failed: "A safety precondition was not met, so nothing was changed.",
  remediation_backup_unavailable: "A supported backup provider is unavailable, so this proposal cannot be approved or executed.",
  remediation_lock_conflict: "Another remediation is already in progress for this target.",
  remediation_replay_conflict: "This request was already processed. Refresh to see the result.",
  remediation_execution_failed: "The remediation action failed to execute.",
  remediation_verification_failed: "HAMIE could not verify the action succeeded.",
  remediation_rolled_back: "The action failed verification and was automatically rolled back.",
  remediation_rollback_unavailable: "This verified repair can no longer be safely rolled back. Refresh its evidence.",
  remediation_rollback_failed: "The action failed and the automatic rollback also failed. Manual review is required.",
  remediation_internal_error: "The remediation request could not be completed. Try again."
};
var KNOWN_MESSAGES = {
  GroupPreviewConflictError: "This group changed since it was loaded. Refresh and try again.",
  GroupNotFoundError: "This group no longer exists. Refresh the list.",
  InvalidReviewTransitionError: "No eligible findings remain for that action. Refresh the list.",
  IdempotencyConflictError: "That action may already have been applied. Refresh to check.",
  // Real AIExecutorError codes (connectors/ai_executor.py). invalid_response,
  // schema_validation_failed, and semantic_validation_failed used to be one
  // generic bucket; they are now distinct so the message tells you whether
  // the text wasn't JSON at all, was JSON but missing/wrong fields even
  // after HAMIE's automatic repair and one corrective retry, or was
  // well-formed but rejected for containing unsafe content.
  invalid_response: "HAMIE could not parse the AI provider's response as JSON. Try again, or check that the model returns structured JSON.",
  // ai_response_truncated is distinct from invalid_response: HAMIE
  // structurally detected the response was cut off mid-value (an
  // unclosed JSON object/array), not merely malformed -- so the honest
  // fix is a token/output limit, never a generic parsing retry.
  ai_response_truncated: "The AI provider's response was cut off before it finished, likely due to an output length limit. Increase the model's maximum output length, or try again.",
  schema_validation_failed: "The AI provider's response was missing required information or used the wrong format, even after HAMIE tried to repair it and asked the model to correct it. Try again, or use a model that follows JSON instructions more closely.",
  semantic_validation_failed: "HAMIE rejected the AI provider's response because it tried to include an executable action. This is a safety guard, not a connection problem.",
  entity_not_found: "The selected AI Task entity is no longer available. Choose a different provider in Settings.",
  timeout: "The AI provider did not respond within the configured timeout.",
  unsupported_feature: "The selected AI Task entity does not support this kind of request.",
  execution_failed: "The AI request could not be completed.",
  ai_provider_not_ready: "No AI provider is configured yet. Set one up in Settings.",
  // Real AIRequestError code (operations_service.py): every eligible
  // root-cause group already has a current (non-stale) recommendation,
  // so there is genuinely nothing new for "Analyze All" to do this run --
  // never confused with a failure or with the prompt-budget-too-small
  // case below.
  ai_all_groups_current: "Every group already has a current AI recommendation. There's nothing new to analyze right now.",
  // Real AIRequestError codes (application/operations_service.py). Raised
  // by async_request_ai() before it ever contacts a connector -- never a
  // connector reachability problem, so these must never fall through to
  // the generic connector "unreachable" text below.
  scan_data_unavailable: "There's nothing to analyze yet. Run a scan, or wait for one to finish.",
  ai_request_selection_too_large: "Too many findings were selected. Choose 50 or fewer.",
  analysis_already_running: "An analysis is already running. Wait for it to finish before starting another.",
  ai_prompt_budget_exhausted: "The configured prompt size is too small to analyze any finding. Increase the maximum input characters in Settings.",
  // Real AIExecutorError code (connectors/ai_executor.py, ollama.py). The
  // selected findings' evidence -- even after HAMIE's own bounded,
  // deduplicated, priority-ordered selection -- was still too large for
  // the configured prompt budget. Distinct from invalid_response
  // (a provider response failing to parse): this failure happens before
  // the provider is ever called, so it must never be described as a
  // parsing problem.
  evidence_payload_too_large: "The selected findings' evidence is too large for the configured prompt size. Increase the maximum input characters in Settings, or analyze fewer findings.",
  // Real ConnectorTestError codes (connectors/base.py, ollama.py, ha_transport.py).
  invalid_url: "The configured address is not a valid URL.",
  unreachable: "Unable to reach the connector within the configured timeout.",
  host_not_allowed: "This host needs explicit approval before HAMIE can connect to it.",
  model_not_found: "The configured model was not found on the provider.",
  authentication_failed: "Authentication with the provider failed. Check the credential.",
  model_discovery_failed: "Could not retrieve the list of available models from the provider.",
  model_list_unavailable: "The provider did not return a usable model list.",
  provider_response_not_json: "The provider's response was not valid JSON. Check the configured address, port, and that nothing (like a proxy) is intercepting the request.",
  // Real n8n connector codes (connectors/n8n.py). Service health and
  // webhook readiness are deliberately separate facts -- a blank or
  // unreachable webhook must never read the same as n8n itself being
  // down, so these are their own namespaced codes rather than reusing
  // the generic connector codes above.
  n8n_service_unreachable: "The n8n host could not be reached.",
  n8n_service_timeout: "The n8n request exceeded the configured timeout.",
  n8n_dns_failure: "The n8n host's address could not be resolved. Check the configured host name.",
  n8n_service_connection_refused: "The n8n host refused the connection. Check the address and port.",
  n8n_authentication_failed: "n8n rejected the saved outbound credential.",
  n8n_forbidden: "n8n reached the request but rejected it as forbidden.",
  n8n_health_http_error: "n8n responded, but its health endpoint returned an unexpected status.",
  n8n_health_invalid_response: "n8n responded, but not with the expected health check format.",
  n8n_webhook_not_configured: "n8n is reachable, but the outbound webhook URL is not configured.",
  n8n_webhook_not_found: "n8n is reachable, but the configured webhook was not found.",
  n8n_webhook_method_not_allowed: "n8n is reachable and the webhook exists, but does not accept this readiness check's request method.",
  n8n_webhook_timeout: "The n8n webhook did not respond within the configured timeout.",
  n8n_webhook_unreachable: "The configured n8n webhook could not be reached.",
  n8n_webhook_readiness_unknown: "Webhook readiness cannot be safely confirmed without executing the workflow.",
  // Bare exception class names that can still legitimately surface
  // unwrapped (no .code attribute) -- a defensive fallback layer, not
  // the primary path now that real codes are preserved.
  TimeoutError: "Unable to reach the connector within the configured timeout.",
  ValueError: "The connector returned an unexpected response.",
  ClientConnectorError: "Unable to reach the connector. Check the address and that it is running.",
  ClientResponseError: "The connector returned an unexpected error response.",
  ClientError: "The connector returned an unexpected response.",
  ConnectionRefusedError: "The connector refused the connection. Check the address and port."
};
function humanizeCode(code, fallback) {
  return code && KNOWN_MESSAGES[code] || fallback;
}
function friendlyError(err, fallback = "This data is temporarily unavailable.") {
  console.error("HAMIE request failed:", err);
  const code = err?.code;
  if (code && KNOWN_CODES[code]) return KNOWN_CODES[code];
  return humanizeCode(err?.message, fallback);
}

// hamie/frontend/ha-registry.js
var cache = null;
var pending = null;
async function primeHaRegistry(hass) {
  if (cache) return cache;
  if (pending) return pending;
  if (!hass) return null;
  pending = (async () => {
    try {
      const [devices, entries, areas] = await Promise.all([
        hass.callWS({ type: "config/device_registry/list" }),
        hass.callWS({ type: "config_entries/get" }),
        hass.callWS({ type: "config/area_registry/list" })
      ]);
      cache = {
        devices: new Map((devices || []).map((item) => [item.id, item])),
        entries: new Map((entries || []).map((item) => [item.entry_id, item])),
        areas: new Map((areas || []).map((item) => [item.area_id, item]))
      };
    } catch {
      cache = { devices: /* @__PURE__ */ new Map(), entries: /* @__PURE__ */ new Map(), areas: /* @__PURE__ */ new Map() };
    } finally {
      pending = null;
    }
    return cache;
  })();
  return pending;
}
function resolveDeviceName(deviceId) {
  const device = deviceId && cache?.devices.get(deviceId);
  return device ? device.name_by_user || device.name || null : null;
}
function resolveConfigEntryTitle(configEntryId) {
  const entry = configEntryId && cache?.entries.get(configEntryId);
  return entry?.title || null;
}
function resolveAreaName(areaId) {
  const area = areaId && cache?.areas.get(areaId);
  return area?.name || null;
}
function configEntryCount() {
  return cache ? cache.entries.size : null;
}
function listDevices() {
  return cache ? [...cache.devices.values()] : [];
}
function listAreas() {
  return cache ? [...cache.areas.values()] : [];
}
function listConfigEntries() {
  return cache ? [...cache.entries.values()] : [];
}
function humanizeSlug(value) {
  return value.split("_").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}
function resolveDisplayName({ configEntryId, deviceId, integrationDomain } = {}, fallback) {
  return resolveConfigEntryTitle(configEntryId) || resolveDeviceName(deviceId) || (integrationDomain ? humanizeSlug(integrationDomain) : null) || fallback || null;
}

// hamie/frontend/grouping-reason.js
var GROUPING_REASON_LABELS = {
  "common config entry": "Same integration instance",
  "common device": "Same device",
  "common providing integration": "Same integration",
  "common integration domain": "Same integration",
  "common config entry id": "Same integration instance",
  "common device id": "Same device",
  "common entity domain": "Same entity type",
  "common area id": "Same area",
  "common source provider": "Same source",
  "common name prefix": "Similar naming",
  "common failure condition": "Same failure pattern",
  "common dependency root": "Same dependency",
  "common analyzer id": "Same analyzer",
  "common category": "Same category",
  "common severity": "Same severity"
};
function groupingReasonLabel(reason) {
  if (!reason) return "";
  if (GROUPING_REASON_LABELS[reason]) return GROUPING_REASON_LABELS[reason];
  if (reason.startsWith("common ")) return `Same ${reason.slice("common ".length)}`;
  return reason;
}

// hamie/frontend/components/hamie-page-header.js
var HamiePageHeader = class extends i4 {
  static properties = {
    heading: { type: String },
    subtitle: { type: String }
  };
  static styles = i`
    :host {
      display: block;
      margin-bottom: var(--hamie-space-5);
    }
    .row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--hamie-space-4);
      flex-wrap: wrap;
    }
    h1 {
      margin: 0;
      font-size: var(--hamie-text-metric);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      letter-spacing: -0.01em;
    }
    .subtitle {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      flex-shrink: 0;
    }
  `;
  render() {
    return b2`
      <div class="row">
        <div>
          <h1>${this.heading}</h1>
          ${this.subtitle ? b2`<p class="subtitle">${this.subtitle}</p>` : null}
        </div>
        <div class="actions"><slot name="actions"></slot></div>
      </div>
      <slot></slot>
    `;
  }
};
if (!customElements.get("hamie-page-header")) {
  customElements.define("hamie-page-header", HamiePageHeader);
}

// hamie/frontend/components/hamie-mini-meter.js
var HamieMiniMeter = class extends i4 {
  static properties = {
    label: { type: String },
    value: { type: Number },
    // 0-100, omit for "not enough data"
    tone: { type: String }
    // "healthy" | "warning" | "critical" | "unknown"
  };
  static styles = i`
    :host {
      display: block;
    }
    .row {
      display: grid;
      grid-template-columns: 90px 1fr 28px;
      align-items: center;
      gap: var(--hamie-space-2-5);
      padding: 3px 0;
    }
    .label {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .track {
      height: 5px;
      border-radius: var(--hamie-radius-pill);
      background: var(--hamie-surface-hover);
      overflow: hidden;
    }
    .fill {
      height: 100%;
      border-radius: var(--hamie-radius-pill);
    }
    .value {
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      text-align: right;
    }
    .unavailable {
      font-size: var(--hamie-text-caption);
      color: var(--hamie-text-secondary);
      font-style: italic;
    }
  `;
  render() {
    const hasValue = typeof this.value === "number" && !Number.isNaN(this.value);
    const pct = hasValue ? Math.max(0, Math.min(100, this.value)) : 0;
    const tone = this.tone || "healthy";
    return b2`
      <div class="row">
        <span class="label">${this.label}</span>
        ${hasValue ? b2`
              <span class="track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow=${pct} aria-label=${this.label}>
                <span class="fill" style="width:${pct}%; background: var(--hamie-status-${tone})"></span>
              </span>
              <span class="value">${pct}</span>
            ` : b2`<span class="unavailable" style="grid-column: 2 / -1">Not enough data</span>`}
      </div>
    `;
  }
};
if (!customElements.get("hamie-mini-meter")) {
  customElements.define("hamie-mini-meter", HamieMiniMeter);
}

// hamie/frontend/components/hamie-status-summary.js
var HamieStatusSummary = class extends i4 {
  static properties = {
    score: { type: Number },
    scoreLabel: { type: String, attribute: "score-label" },
    statusText: { type: String, attribute: "status-text" },
    tone: { type: String },
    // "healthy" | "warning" | "critical" | "unknown"
    rows: { type: Array },
    // [{ label, value, tone }] -- simple label/value rows
    dimensions: { type: Array }
    // [{ label, value, tone }] -- rendered as hamie-mini-meter
  };
  static styles = i`
    :host {
      display: block;
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg);
      background: var(--hamie-surface-card);
      padding: var(--hamie-space-5);
    }
    .layout {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-6);
      flex-wrap: wrap;
    }
    .primary {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-3);
      flex-shrink: 0;
    }
    .score-icon {
      width: 56px;
      height: 56px;
      border-radius: var(--hamie-radius-circle);
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .score-icon ha-icon {
      --mdc-icon-size: 26px;
    }
    .score-text {
      display: flex;
      align-items: baseline;
      gap: var(--hamie-space-2);
    }
    .score {
      font-size: var(--hamie-text-display);
      font-weight: var(--hamie-weight-bold);
      line-height: 1;
      letter-spacing: -0.02em;
    }
    .score-max {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
    }
    .score.unavailable {
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-secondary);
    }
    .primary-text {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .dimensions {
      flex: 1;
      min-width: 220px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 0 var(--hamie-space-5);
    }
    .score-label {
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-text-secondary);
    }
    .status-text {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
    }
    .divider {
      align-self: stretch;
      width: 1px;
      background: var(--hamie-border-hairline);
    }
    .rows {
      flex: 1;
      min-width: 200px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: var(--hamie-space-3) var(--hamie-space-5);
    }
    .metric-row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: var(--hamie-space-2);
    }
    .metric-label {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .metric-value {
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    @media (max-width: 600px) {
      .layout {
        flex-direction: column;
        align-items: stretch;
      }
      .divider {
        width: auto;
        height: 1px;
      }
    }
  `;
  render() {
    const hasScore = typeof this.score === "number" && !Number.isNaN(this.score);
    const tone = this.tone || "unknown";
    const rows = this.rows || [];
    const dimensions = this.dimensions || [];
    return b2`
      <div class="layout">
        <div class="primary">
          ${hasScore ? b2`
                <span class="score-icon" style="background: var(--hamie-status-${tone}-fill)">
                  <ha-icon icon="mdi:heart-pulse" style="color: var(--hamie-status-${tone})"></ha-icon>
                </span>
              ` : null}
          <div class="primary-text">
            <span class="score-text">
              <span class="score${hasScore ? "" : " unavailable"}" style=${hasScore ? `color: var(--hamie-status-${tone})` : ""}>
                ${hasScore ? this.score : "Health analysis pending"}
              </span>
              ${hasScore ? b2`<span class="score-max">/100</span>` : null}
            </span>
            ${this.statusText ? b2`<span class="status-text">${this.statusText}</span>` : null}
          </div>
        </div>
        ${rows.length || dimensions.length ? b2`<div class="divider"></div>` : null}
        ${dimensions.length ? b2`
              <div class="dimensions">
                ${dimensions.map(
      (dim) => b2`<hamie-mini-meter label=${dim.label} .value=${dim.value} tone=${dim.tone || "healthy"}></hamie-mini-meter>`
    )}
              </div>
            ` : rows.length ? b2`
                <div class="rows">
                  ${rows.map(
      (row) => b2`
                      <div class="metric-row">
                        <span class="metric-label">${row.label}</span>
                        <span class="metric-value" style=${row.tone ? `color: var(--hamie-status-${row.tone})` : ""}>${row.value}</span>
                      </div>
                    `
    )}
                </div>
              ` : null}
      </div>
    `;
  }
};
if (!customElements.get("hamie-status-summary")) {
  customElements.define("hamie-status-summary", HamieStatusSummary);
}

// hamie/frontend/components/hamie-action-card.js
var HamieActionCard = class extends i4 {
  static properties = {
    icon: { type: String },
    heading: { type: String },
    description: { type: String }
  };
  static styles = i`
    :host {
      display: block;
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg);
      background: linear-gradient(
        to bottom right,
        var(--hamie-accent-fill-quiet),
        var(--hamie-surface-card) 65%
      );
      padding: var(--hamie-space-5);
    }
    .layout {
      display: flex;
      align-items: flex-start;
      gap: var(--hamie-space-4);
    }
    .icon-badge {
      flex-shrink: 0;
      width: 40px;
      height: 40px;
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-accent-fill-loud);
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .icon-badge ha-icon {
      --mdc-icon-size: 20px;
      color: var(--hamie-accent-on);
    }
    .content {
      flex: 1;
      min-width: 0;
    }
    .eyebrow {
      margin: 0 0 var(--hamie-space-1);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-accent);
    }
    .heading {
      margin: 0;
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .description {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      line-height: 1.5;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-3);
    }
  `;
  render() {
    return b2`
      <div class="layout">
        ${this.icon ? b2`<div class="icon-badge"><ha-icon icon=${this.icon}></ha-icon></div>` : null}
        <div class="content">
          <p class="eyebrow">Recommended next step</p>
          <p class="heading">${this.heading}</p>
          ${this.description ? b2`<p class="description">${this.description}</p>` : null}
          <div class="actions"><slot></slot></div>
        </div>
      </div>
    `;
  }
};
if (!customElements.get("hamie-action-card")) {
  customElements.define("hamie-action-card", HamieActionCard);
}

// hamie/frontend/components/hamie-issue-row.js
var HamieIssueRow = class extends i4 {
  static properties = {
    title: { type: String },
    meta: { type: String },
    interactive: { type: Boolean, reflect: true }
  };
  static styles = i`
    :host {
      display: block;
    }
    .row {
      display: flex;
      align-items: center;
      width: 100%;
      box-sizing: border-box;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-2-5) var(--hamie-space-1);
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      text-align: left;
      border-radius: var(--hamie-radius-md);
    }
    :host([interactive]) .row {
      cursor: pointer;
    }
    :host([interactive]) .row:hover {
      background: var(--hamie-surface-hover);
    }
    .row:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: -2px;
    }
    .leading {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .leading:empty {
      display: none;
    }
    .main {
      flex: 1;
      min-width: 0;
    }
    .title {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .meta {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    ::slotted([slot="extra"]) {
      display: block;
      margin-top: 2px;
    }
    .trailing {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
    }
    /* Below phone width, trailing content (a status label + chevron,
     * routinely 20+ characters) no longer fits beside the row's main
     * content without crushing it -- drop to its own line instead of
     * shrinking text further (spec: "stacked rows", not shrunk cards). */
    @media (max-width: 480px) {
      .row {
        flex-wrap: wrap;
      }
      .trailing {
        width: 100%;
        justify-content: flex-end;
        margin-top: var(--hamie-space-1);
      }
    }
  `;
  _onClick(event) {
    if (!this.interactive) return;
    this.dispatchEvent(new CustomEvent("hamie-row-click", { bubbles: true, composed: true }));
    event.stopPropagation();
  }
  render() {
    const inner = b2`
      <span class="leading"><slot name="leading"></slot></span>
      <span class="main">
        <p class="title">${this.title}</p>
        ${this.meta ? b2`<p class="meta">${this.meta}</p>` : null}
        <slot name="extra"></slot>
      </span>
      <span class="trailing"><slot name="trailing"></slot></span>
    `;
    return this.interactive ? b2`<button type="button" class="row" @click=${this._onClick}>${inner}</button>` : b2`<div class="row">${inner}</div>`;
  }
};
if (!customElements.get("hamie-issue-row")) {
  customElements.define("hamie-issue-row", HamieIssueRow);
}

// hamie/frontend/components/hamie-donut.js
var SIZE = 120;
var STROKE = 16;
var RADIUS = (SIZE - STROKE) / 2;
var CIRCUMFERENCE = 2 * Math.PI * RADIUS;
var HamieDonut = class extends i4 {
  static properties = {
    segments: { type: Array }
    // [{ label, value, tone }]
  };
  static styles = i`
    :host {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-4);
    }
    svg {
      flex-shrink: 0;
      transform: rotate(-90deg);
    }
    .track {
      fill: none;
      stroke: var(--hamie-surface-hover);
    }
    .segment {
      fill: none;
    }
    .legend {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-1-5);
      font-size: var(--hamie-text-micro);
    }
    .legend-row {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      color: var(--hamie-text-secondary);
    }
    .swatch {
      width: 8px;
      height: 8px;
      border-radius: var(--hamie-radius-circle);
      flex-shrink: 0;
    }
    .legend-value {
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
  `;
  render() {
    const segments = (this.segments || []).filter((item) => item.value > 0);
    const total = segments.reduce((sum, item) => sum + item.value, 0);
    let offset = 0;
    const arcs = total ? segments.map((item) => {
      const fraction = item.value / total;
      const dash = fraction * CIRCUMFERENCE;
      const arc = w`
            <circle
              class="segment"
              cx=${SIZE / 2}
              cy=${SIZE / 2}
              r=${RADIUS}
              stroke="var(--hamie-status-${item.tone})"
              stroke-width=${STROKE}
              stroke-dasharray="${dash} ${CIRCUMFERENCE - dash}"
              stroke-dashoffset=${-offset}
            ></circle>
          `;
      offset += dash;
      return arc;
    }) : [];
    return b2`
      <svg viewBox="0 0 ${SIZE} ${SIZE}" width=${SIZE} height=${SIZE} role="img" aria-label="Cleanup candidate breakdown">
        <circle class="track" cx=${SIZE / 2} cy=${SIZE / 2} r=${RADIUS} stroke-width=${STROKE}></circle>
        ${arcs}
      </svg>
      <ul class="legend" style="list-style: none; margin: 0; padding: 0;">
        ${(this.segments || []).map(
      (item) => b2`
            <li class="legend-row">
              <span class="swatch" style="background: var(--hamie-status-${item.tone})"></span>
              <span class="legend-value">${item.value}</span>
              ${item.label}
            </li>
          `
    )}
      </ul>
    `;
  }
};
if (!customElements.get("hamie-donut")) {
  customElements.define("hamie-donut", HamieDonut);
}

// hamie/frontend/components/hamie-card.js
var HamieCard = class extends i4 {
  static properties = {
    padding: { type: String }
    // "none" | "sm" | "md" (default)
  };
  static styles = i`
    :host {
      display: block;
      background: var(--hamie-surface-card);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg);
    }
    :host([padding="sm"]) .content {
      padding: var(--hamie-space-3);
    }
    :host([padding="md"]) .content,
    :host(:not([padding])) .content {
      padding: var(--hamie-space-4);
    }
    :host([padding="none"]) .content {
      padding: 0;
    }
  `;
  render() {
    return b2`<div class="content"><slot></slot></div>`;
  }
};
if (!customElements.get("hamie-card")) {
  customElements.define("hamie-card", HamieCard);
}

// hamie/frontend/components/hamie-button.js
var HamieButton = class extends i4 {
  // Delegates focus to the real inner <button> -- without this, calling
  // `.focus()` on a <hamie-button> host element (e.g. to return focus to
  // a dialog's trigger after it closes) does nothing at all, since the
  // interactive element actually lives inside this component's own
  // shadow root, not on the host.
  static shadowRootOptions = { ...i4.shadowRootOptions, delegatesFocus: true };
  static properties = {
    variant: { type: String },
    // "primary" | "secondary" | "ghost" (default) | "danger"
    size: { type: String },
    // "xs" | "sm" (default) | "md"
    disabled: { type: Boolean, reflect: true }
  };
  static styles = i`
    :host {
      display: inline-flex;
    }
    button {
      display: inline-flex;
      align-items: center;
      font-family: inherit;
      font-weight: var(--hamie-weight-medium);
      cursor: pointer;
      border: 1px solid transparent;
      transition:
        background-color var(--hamie-motion-fast) var(--hamie-motion-ease),
        color var(--hamie-motion-fast) var(--hamie-motion-ease);
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.5;
    }
    button:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 2px;
    }
    /* --mdc-icon-size is how every other component in the library sizes
     * <ha-icon> (see shared-styles.js and hamie-status/hamie-empty/etc.)
     * -- kept consistent here rather than the width/height override this
     * used to have, which was the only component sizing icons that way. */
    ::slotted(ha-icon) {
      --mdc-icon-size: 0.85em;
    }

    /* Sizes */
    :host([size="xs"]) button {
      padding: var(--hamie-space-1) var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      border-radius: var(--hamie-radius-sm);
      gap: var(--hamie-space-1);
    }
    :host([size="md"]) button {
      padding: var(--hamie-space-2) var(--hamie-space-4);
      font-size: var(--hamie-text-small);
      border-radius: var(--hamie-radius-md);
      gap: var(--hamie-space-2);
    }
    :host(:not([size])) button,
    :host([size="sm"]) button {
      padding: var(--hamie-space-1-5) var(--hamie-space-2-5);
      font-size: var(--hamie-text-micro);
      border-radius: var(--hamie-radius-sm);
      gap: var(--hamie-space-1-5);
    }

    /* Variants */
    :host(:not([variant])) button,
    :host([variant="ghost"]) button {
      background: transparent;
      color: var(--hamie-text-secondary);
    }
    :host(:not([variant])) button:hover:not(:disabled),
    :host([variant="ghost"]) button:hover:not(:disabled) {
      background: var(--hamie-surface-hover);
      color: var(--hamie-text-primary);
    }

    :host([variant="primary"]) button {
      background: var(--hamie-accent-fill-loud);
      color: var(--hamie-accent-on);
    }
    :host([variant="primary"]) button:hover:not(:disabled) {
      filter: brightness(1.1);
    }

    :host([variant="secondary"]) button {
      background: var(--hamie-surface-raised);
      color: var(--hamie-text-primary);
      border-color: var(--hamie-border-normal);
    }
    :host([variant="secondary"]) button:hover:not(:disabled) {
      background: var(--hamie-surface-hover);
    }

    :host([variant="danger"]) button {
      background: var(--hamie-danger-fill);
      color: var(--hamie-danger);
      border-color: var(--hamie-danger-border);
    }
    :host([variant="danger"]) button:hover:not(:disabled) {
      filter: brightness(1.1);
    }
  `;
  render() {
    const label = this.getAttribute("aria-label");
    return b2`
      <button ?disabled=${this.disabled} aria-label=${label || A}>
        <slot></slot>
      </button>
    `;
  }
};
if (!customElements.get("hamie-button")) {
  customElements.define("hamie-button", HamieButton);
}

// hamie/frontend/components/hamie-section.js
var HamieSection = class extends i4 {
  static properties = {
    heading: { type: String },
    description: { type: String }
  };
  static styles = i`
    :host {
      display: block;
      margin-bottom: var(--hamie-space-4);
    }
    .row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
    }
    h2 {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    p {
      margin: var(--hamie-space-half) 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
  `;
  render() {
    return b2`
      <div class="row">
        <div>
          <h2>${this.heading}</h2>
          ${this.description ? b2`<p>${this.description}</p>` : null}
        </div>
        <slot name="action"></slot>
      </div>
    `;
  }
};
if (!customElements.get("hamie-section")) {
  customElements.define("hamie-section", HamieSection);
}

// hamie/frontend/components/hamie-loading.js
var HamieLoading = class extends i4 {
  static properties = {
    lines: { type: Number },
    // number of skeleton bars, default 1
    label: { type: String }
    // visually-hidden text for screen readers
  };
  static styles = i`
    :host {
      display: block;
    }
    .bar {
      height: 12px;
      border-radius: var(--hamie-radius-sm);
      background: var(--hamie-surface-raised);
      animation: hamie-pulse 1.4s var(--hamie-motion-ease) infinite;
    }
    .bar + .bar {
      margin-top: var(--hamie-space-2);
    }
    .bar:nth-child(3n + 2) {
      width: 85%;
    }
    .bar:nth-child(3n + 3) {
      width: 60%;
    }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
    }
    @keyframes hamie-pulse {
      0%,
      100% {
        opacity: 1;
      }
      50% {
        opacity: 0.4;
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .bar {
        animation: none;
      }
    }
  `;
  render() {
    const count = this.lines && this.lines > 0 ? this.lines : 1;
    return b2`
      <div role="status" aria-live="polite">
        <span class="sr-only">${this.label || "Loading"}</span>
        ${Array.from({ length: count }, () => b2`<div class="bar" aria-hidden="true"></div>`)}
      </div>
    `;
  }
};
if (!customElements.get("hamie-loading")) {
  customElements.define("hamie-loading", HamieLoading);
}

// hamie/frontend/components/hamie-progress.js
var HamieProgress = class extends i4 {
  static properties = {
    label: { type: String },
    stage: { type: String },
    value: { type: Number }
    // 0-100, omit for indeterminate
  };
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-3) var(--hamie-space-4);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-surface-raised);
    }
    .row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: var(--hamie-space-2);
      margin-bottom: var(--hamie-space-2);
    }
    .label {
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .stage {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .track {
      position: relative;
      height: 4px;
      overflow: hidden;
      border-radius: var(--hamie-radius-pill);
      background: var(--hamie-surface-hover);
    }
    .fill {
      position: absolute;
      inset: 0 auto 0 0;
      border-radius: var(--hamie-radius-pill);
      background: var(--hamie-accent);
    }
    :host(:not([value])) .fill,
    .fill.indeterminate {
      width: 40%;
      animation: hamie-progress-slide 1.2s var(--hamie-motion-ease) infinite;
    }
    @keyframes hamie-progress-slide {
      0% {
        left: -40%;
      }
      100% {
        left: 100%;
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .fill.indeterminate {
        animation: none;
        left: 0;
        width: 100%;
        opacity: 0.5;
      }
    }
  `;
  render() {
    const determinate = typeof this.value === "number" && !Number.isNaN(this.value);
    const pct = determinate ? Math.max(0, Math.min(100, this.value)) : null;
    return b2`
      <div class="row">
        <span class="label">${this.label}</span>
        ${determinate ? b2`<span class="stage">${pct}%</span>` : null}
      </div>
      ${this.stage ? b2`<p class="stage" style="margin: 0 0 var(--hamie-space-2)">${this.stage}</p>` : null}
      <div class="track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow=${determinate ? pct : ""} aria-label=${this.label || "Progress"}>
        <div class=${determinate ? "fill" : "fill indeterminate"} style=${determinate ? `width:${pct}%` : ""}></div>
      </div>
    `;
  }
};
if (!customElements.get("hamie-progress")) {
  customElements.define("hamie-progress", HamieProgress);
}

// hamie/frontend/components/hamie-disclosure.js
var uid = 0;
var HamieDisclosure = class extends i4 {
  static properties = {
    label: { type: String },
    open: { type: Boolean, reflect: true }
  };
  static styles = i`
    :host {
      display: block;
    }
    button {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      width: 100%;
      padding: var(--hamie-space-2) 0;
      border: 0;
      background: transparent;
      color: var(--hamie-text-secondary);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      cursor: pointer;
      text-align: left;
    }
    button:hover {
      color: var(--hamie-text-primary);
    }
    button:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 2px;
      border-radius: var(--hamie-radius-sm);
    }
    ha-icon {
      --mdc-icon-size: 16px;
      transition: transform var(--hamie-motion-fast) var(--hamie-motion-ease);
    }
    :host([open]) ha-icon {
      transform: rotate(180deg);
    }
    .region {
      padding-top: var(--hamie-space-2);
    }
  `;
  constructor() {
    super();
    this.open = false;
    this._id = `hamie-disclosure-${uid++}`;
  }
  _toggle() {
    this.open = !this.open;
  }
  render() {
    return b2`
      <button type="button" aria-expanded=${String(this.open)} aria-controls=${this._id} @click=${this._toggle}>
        <ha-icon icon="mdi:chevron-down"></ha-icon>
        ${this.label}
      </button>
      ${this.open ? b2`<div id=${this._id} class="region" role="region"><slot></slot></div>` : null}
    `;
  }
};
if (!customElements.get("hamie-disclosure")) {
  customElements.define("hamie-disclosure", HamieDisclosure);
}

// hamie/frontend/idempotency.js
var sequence = 0;
function idempotencyToken() {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  sequence += 1;
  const time = Date.now().toString(36);
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    const bytes = new Uint8Array(12);
    globalThis.crypto.getRandomValues(bytes);
    const random = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    return `hamie-${time}-${sequence.toString(36)}-${random}`;
  }
  return `hamie-${time}-${sequence.toString(36)}-local`;
}

// hamie/frontend/components/hamie-drawer.js
var HamieDrawer = class extends i4 {
  static properties = {
    open: { type: Boolean, reflect: true },
    wide: { type: Boolean, reflect: true },
    heading: { type: String },
    description: { type: String },
    onClose: { attribute: false },
    focusReturnTarget: { attribute: false }
  };
  static styles = i`
    :host {
      position: fixed;
      inset: 0;
      z-index: 1000;
      display: none;
    }
    :host([open]) {
      display: block;
    }
    .backdrop {
      position: absolute;
      inset: 0;
      background: rgba(0, 0, 0, 0.5);
      animation: hamie-fade-in var(--hamie-motion-normal) var(--hamie-motion-ease);
    }
    .panel {
      position: absolute;
      top: 0;
      right: 0;
      bottom: 0;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      width: min(420px, 100vw);
      color: var(--hamie-text-primary);
      background: var(--hamie-surface-card);
      border-left: 1px solid var(--hamie-border-hairline);
      box-shadow: var(--hamie-elevation-popover);
      animation: hamie-slide-in var(--hamie-motion-normal) var(--hamie-motion-ease);
    }
    :host([wide]) .panel {
      width: min(1000px, 100vw);
    }
    @keyframes hamie-fade-in {
      from {
        opacity: 0;
      }
    }
    @keyframes hamie-slide-in {
      from {
        transform: translateX(100%);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .backdrop,
      .panel {
        animation: none;
      }
    }
    header {
      display: flex;
      align-items: flex-start;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-4);
      border-bottom: 1px solid var(--hamie-border-hairline);
      flex-shrink: 0;
    }
    .heading-wrap {
      flex: 1;
      min-width: 0;
    }
    h2 {
      margin: 0;
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium);
      overflow-wrap: anywhere;
    }
    .description {
      margin: 4px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      overflow-wrap: anywhere;
    }
    .close {
      width: 32px;
      height: 32px;
      flex-shrink: 0;
      border: 0;
      border-radius: var(--hamie-radius-md);
      color: var(--hamie-text-secondary);
      background: transparent;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .close:hover {
      background: var(--hamie-surface-hover);
      color: var(--hamie-text-primary);
    }
    .close:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 2px;
    }
    .body {
      flex: 1;
      overflow-y: auto;
      padding: var(--hamie-space-4);
    }
    @media (max-width: 600px) {
      .panel {
        top: auto;
        left: 0;
        width: 100vw;
        height: min(92vh, 100%);
        border-left: 0;
        border-top: 1px solid var(--hamie-border-hairline);
        border-radius: var(--hamie-radius-lg) var(--hamie-radius-lg) 0 0;
      }
      @keyframes hamie-slide-in {
        from {
          transform: translateY(100%);
        }
      }
    }
  `;
  connectedCallback() {
    this._returnTarget = this.focusReturnTarget || this.getRootNode()?.activeElement || document.activeElement;
    super.connectedCallback();
    document.addEventListener("keydown", this._onKeyDown, true);
  }
  disconnectedCallback() {
    document.removeEventListener("keydown", this._onKeyDown, true);
    super.disconnectedCallback();
  }
  firstUpdated() {
    queueMicrotask(() => this.shadowRoot?.querySelector(".panel")?.focus());
  }
  _focusables() {
    const selector = 'button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[href],[tabindex]:not([tabindex="-1"])';
    return [...this.shadowRoot.querySelectorAll(selector), ...this.querySelectorAll(selector)].filter(
      (item) => item.getClientRects().length
    );
  }
  _onKeyDown = (event) => {
    if (!this.open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      this._close("escape");
      return;
    }
    if (event.key !== "Tab") return;
    const items = this._focusables();
    if (!items.length) return;
    const active = this.shadowRoot.activeElement || document.activeElement;
    if (event.shiftKey && active === items[0]) {
      event.preventDefault();
      items.at(-1).focus();
    } else if (!event.shiftKey && active === items.at(-1)) {
      event.preventDefault();
      items[0].focus();
    }
  };
  _close(reason) {
    this.onClose?.(reason);
    this.dispatchEvent(new CustomEvent("hamie-drawer-closed", { detail: { reason }, bubbles: true, composed: true }));
    const target = this.focusReturnTarget || this._returnTarget;
    queueMicrotask(() => target?.focus?.());
  }
  render() {
    if (!this.open) return null;
    return b2`
      <div class="backdrop" @mousedown=${(event) => event.target === event.currentTarget && this._close("backdrop")}></div>
      <section
        class="panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="hamie-drawer-title"
        tabindex="-1"
      >
        <header>
          <div class="heading-wrap">
            <h2 id="hamie-drawer-title">${this.heading}</h2>
            ${this.description ? b2`<p class="description">${this.description}</p>` : null}
          </div>
          <button class="close" type="button" aria-label="Close" @click=${() => this._close("close")}>
            <ha-icon icon="mdi:close"></ha-icon>
          </button>
        </header>
        <div class="body"><slot></slot></div>
      </section>
    `;
  }
};
if (!customElements.get("hamie-drawer")) {
  customElements.define("hamie-drawer", HamieDrawer);
}

// hamie/frontend/components/hamie-dialog.js
var HamieDialog = class extends i4 {
  static properties = {
    open: { type: Boolean, reflect: true },
    heading: { type: String },
    description: { type: String },
    cancelLabel: { type: String, attribute: "cancel-label" },
    confirmLabel: { type: String, attribute: "confirm-label" },
    destructive: { type: Boolean, reflect: true },
    busy: { type: Boolean, reflect: true },
    errorMessage: { type: String, attribute: "error-message" },
    confirmDisabled: { type: Boolean, attribute: "confirm-disabled" },
    typedConfirmationPhrase: { type: String, attribute: "typed-confirmation-phrase" },
    onConfirm: { attribute: false },
    onCancel: { attribute: false },
    onClose: { attribute: false },
    focusReturnTarget: { attribute: false },
    _typedValue: { state: true },
    _submitting: { state: true }
  };
  static styles = i`
    :host { position: fixed; inset: 0; z-index: 1000; display: none; }
    :host([open]) { display: block; }
    .backdrop {
      position: absolute; inset: 0; display: grid; place-items: center;
      box-sizing: border-box; padding: 16px; background: rgba(0, 0, 0, .62);
    }
    .dialog {
      display: flex; flex-direction: column; overflow: hidden;
      width: min(560px, calc(100vw - 32px)); max-height: calc(100vh - 32px);
      color: var(--hamie-text-primary); background: var(--hamie-surface-card);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg); box-shadow: var(--hamie-elevation-popover);
    }
    header {
      display: flex; align-items: flex-start; gap: var(--hamie-space-3);
      padding: var(--hamie-space-4); border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .heading-wrap { flex: 1; min-width: 0; }
    h2 { margin: 0; font-size: var(--hamie-text-base); }
    .description { margin: 4px 0 0; color: var(--hamie-text-secondary); }
    .close {
      width: 36px; height: 36px; border: 0; border-radius: var(--hamie-radius-md);
      color: inherit; background: transparent; cursor: pointer; font-size: 24px;
    }
    .close:hover { background: var(--hamie-surface-hover); }
    .body {
      overflow: auto; padding: var(--hamie-space-4);
      font-size: var(--hamie-text-small); color: var(--hamie-text-secondary); line-height: 1.6;
    }
    .typed { display: grid; gap: 6px; margin: 0 var(--hamie-space-4) var(--hamie-space-3); }
    .typed input {
      min-height: 40px; padding: 8px; color: inherit; background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-hairline); border-radius: var(--hamie-radius-md);
    }
    .error {
      margin: 0 var(--hamie-space-4) var(--hamie-space-3); padding: var(--hamie-space-2);
      color: var(--hamie-status-critical); background: var(--hamie-status-critical-fill);
      border-radius: var(--hamie-radius-md);
    }
    footer {
      display: flex; align-items: center; justify-content: flex-end; gap: var(--hamie-space-2);
      padding: var(--hamie-space-3) var(--hamie-space-4);
      border-top: 1px solid var(--hamie-border-hairline);
    }
    footer button {
      min-width: 92px; min-height: 40px; padding: 8px 14px; cursor: pointer;
      color: var(--hamie-text-primary); background: transparent;
      border: 1px solid var(--hamie-border-hairline); border-radius: var(--hamie-radius-md);
    }
    footer .confirm {
      color: var(--hamie-accent-on); background: var(--hamie-accent-fill-loud); border-color: transparent;
    }
    :host([destructive]) footer .confirm { background: var(--hamie-status-critical); }
    button:disabled, input:disabled { opacity: .48; cursor: not-allowed; }
    button:focus-visible, input:focus-visible { outline: 2px solid var(--hamie-accent); outline-offset: 2px; }
    @media (max-width: 600px) {
      .backdrop { align-items: end; padding: 0; }
      .dialog { width: 100vw; max-height: 92vh; border-radius: var(--hamie-radius-lg) var(--hamie-radius-lg) 0 0; }
      footer { flex-direction: column-reverse; }
      footer button { width: 100%; }
    }
  `;
  constructor() {
    super();
    this.open = false;
    this.cancelLabel = "";
    this.confirmLabel = "";
    this._typedValue = "";
    this._submitting = false;
  }
  connectedCallback() {
    this._returnTarget = this.focusReturnTarget || this.getRootNode()?.activeElement || document.activeElement;
    super.connectedCallback();
    document.addEventListener("keydown", this._onKeyDown, true);
  }
  disconnectedCallback() {
    document.removeEventListener("keydown", this._onKeyDown, true);
    super.disconnectedCallback();
  }
  firstUpdated() {
    queueMicrotask(() => this.shadowRoot?.querySelector(".dialog")?.focus());
  }
  _focusables() {
    const selector = 'button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[href],[tabindex]:not([tabindex="-1"])';
    return [...this.shadowRoot.querySelectorAll(selector), ...this.querySelectorAll(selector)].filter((item) => item.getClientRects().length);
  }
  _onKeyDown = (event) => {
    if (!this.open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      this._cancel("escape");
      return;
    }
    if (event.key !== "Tab") return;
    const items = this._focusables();
    if (!items.length) return;
    const active = this.shadowRoot.activeElement || document.activeElement;
    if (event.shiftKey && active === items[0]) {
      event.preventDefault();
      items.at(-1).focus();
    } else if (!event.shiftKey && active === items.at(-1)) {
      event.preventDefault();
      items[0].focus();
    }
  };
  _emit(name, detail) {
    this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
  }
  _cancel(reason) {
    if (this.busy || this._submitting) return;
    this.onCancel?.(reason);
    this.onClose?.(reason);
    this._emit("hamie-cancel", { reason });
    this._emit("hamie-dialog-closed", { reason });
    const target = this.focusReturnTarget || this._returnTarget;
    queueMicrotask(() => target?.focus?.());
  }
  _confirmDisabled() {
    return this.busy || this._submitting || this.confirmDisabled || this.typedConfirmationPhrase && this._typedValue !== this.typedConfirmationPhrase;
  }
  async _confirm() {
    if (this._confirmDisabled()) return;
    this._submitting = true;
    this.requestUpdate();
    try {
      if (this.onConfirm) await this.onConfirm();
      this._emit("hamie-confirm");
    } finally {
      this._submitting = false;
      this.requestUpdate();
    }
  }
  render() {
    if (!this.open) return null;
    const ownedActions = this.cancelLabel || this.confirmLabel;
    return b2`
      <div class="backdrop" @mousedown=${(event) => event.target === event.currentTarget && this._cancel("backdrop")}>
        <section class="dialog" role="dialog" aria-modal="true"
          aria-labelledby="hamie-title" aria-describedby="hamie-body" tabindex="-1"
          @mousedown=${(event) => event.stopPropagation()}>
          <header>
            <div class="heading-wrap">
              <h2 id="hamie-title">${this.heading}</h2>
              ${this.description ? b2`<p class="description">${this.description}</p>` : null}
            </div>
            <button class="close" type="button" aria-label="Close"
              ?disabled=${this.busy || this._submitting}
              @click=${() => this._cancel("close")}>&times;</button>
          </header>
          <div id="hamie-body" class="body"><slot></slot></div>
          ${this.typedConfirmationPhrase ? b2`
            <label class="typed">
              <span>Type <code>${this.typedConfirmationPhrase}</code> to continue</span>
              <input .value=${this._typedValue}
                ?disabled=${this.busy || this._submitting}
                @input=${(event) => this._typedValue = event.target.value}>
            </label>` : null}
          ${this.errorMessage ? b2`<p class="error" role="alert">${this.errorMessage}</p>` : null}
          ${ownedActions ? b2`
            <footer>
              ${this.cancelLabel ? b2`<button type="button"
                ?disabled=${this.busy || this._submitting}
                @click=${() => this._cancel("cancel")}>${this.cancelLabel}</button>` : null}
              ${this.confirmLabel ? b2`<button class="confirm" type="button"
                ?disabled=${this._confirmDisabled()} @click=${this._confirm}>
                ${this.busy || this._submitting ? "Working\u2026" : this.confirmLabel}</button>` : null}
            </footer>` : b2`
            <footer>
              <slot name="secondary-action"></slot>
              <slot name="primary-action"></slot>
            </footer>`}
        </section>
      </div>
    `;
  }
};
if (!customElements.get("hamie-dialog")) {
  customElements.define("hamie-dialog", HamieDialog);
}

// hamie/frontend/components/hamie-cleanup-review.js
var CLASSIFICATION_TAB = {
  blocked_dependency: "protected",
  blocked_uncertain: "needs_evidence",
  manual_review: "needs_evidence",
  parent_integration_failure: "integration_issue"
};
var TABS = [
  { id: "ready", label: "Safe to disable" },
  { id: "protected", label: "Protected" },
  { id: "needs_evidence", label: "Needs evidence" },
  { id: "integration_issue", label: "Integration issues" }
];
function humanizeEntityId(entityId) {
  const slug = entityId.split(".").slice(1).join(".");
  return slug.split(/[_.]/).filter(Boolean).map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}
var HamieCleanupReview = class extends i4 {
  static properties = {
    hass: { attribute: false },
    open: { type: Boolean },
    summary: { attribute: false },
    _tab: { state: true },
    _expandedBatch: { state: true },
    _workItems: { state: true },
    _batches: { state: true },
    _busy: { state: true },
    _actionError: { state: true },
    _pendingDisable: { state: true }
  };
  static styles = i`
    :host {
      display: contents;
    }
    .summary-row {
      display: flex;
      flex-wrap: wrap;
      gap: var(--hamie-space-5);
      padding-bottom: var(--hamie-space-4);
      margin-bottom: var(--hamie-space-4);
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .stat {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .stat strong {
      font-size: var(--hamie-text-metric);
      font-weight: var(--hamie-weight-bold);
      color: var(--hamie-text-primary);
    }
    .stat span {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .tabs {
      display: flex;
      gap: var(--hamie-space-1);
      margin-bottom: var(--hamie-space-4);
      border-bottom: 1px solid var(--hamie-border-hairline);
      overflow-x: auto;
    }
    .tabs button {
      background: none;
      border: 0;
      border-bottom: 2px solid transparent;
      padding: var(--hamie-space-2) var(--hamie-space-3);
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      cursor: pointer;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .tabs button[aria-selected="true"] {
      color: var(--hamie-text-primary);
      border-bottom-color: var(--hamie-accent);
      font-weight: var(--hamie-weight-medium);
    }
    .group-row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-3) 0;
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .group-row:last-child {
      border-bottom: none;
    }
    .group-title {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .group-meta {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      max-width: 60ch;
    }
    .group-actions {
      display: flex;
      gap: var(--hamie-space-2);
      flex-shrink: 0;
      align-items: center;
    }
    .members {
      margin: var(--hamie-space-2) 0 var(--hamie-space-3);
      padding-left: var(--hamie-space-4);
      border-left: 2px solid var(--hamie-border-hairline);
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-1-5);
    }
    .member-row {
      display: flex;
      align-items: baseline;
      gap: var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
    }
    .member-row .name {
      color: var(--hamie-text-primary);
    }
    .member-row .id {
      color: var(--hamie-text-secondary);
      font-family: var(--hamie-font-code);
    }
    .members-more {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .action-error {
      margin-bottom: var(--hamie-space-3);
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
      font-size: var(--hamie-text-small);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
  `;
  willUpdate(changed) {
    if (changed.has("summary") && this.summary) {
      this._workItems = [...this.summary.persisted_maintenance_work_items || []];
      this._batches = [...this.summary.batches || []];
      this._tab = this._defaultTab();
      this._expandedBatch = null;
      this._actionError = null;
    }
  }
  _defaultTab() {
    const readyCount = (this._batches || []).filter(
      (batch) => batch.remediation_plan_id && !batch.auto_executed
    ).length;
    if (readyCount > 0) return "ready";
    const buckets = this._bucketCounts();
    return TABS.find((tab) => tab.id !== "ready" && buckets[tab.id] > 0)?.id || "ready";
  }
  _bucketCounts() {
    const counts = { protected: 0, needs_evidence: 0, integration_issue: 0 };
    for (const item of this._workItems || []) {
      const tab = CLASSIFICATION_TAB[item.classification];
      if (tab && item.lifecycle_state !== "completed") counts[tab] += 1;
    }
    return counts;
  }
  _itemsForTab(tab) {
    return (this._workItems || []).filter(
      (item) => CLASSIFICATION_TAB[item.classification] === tab && item.lifecycle_state !== "completed"
    );
  }
  _readyBatches() {
    return (this._batches || []).filter((batch) => batch.remediation_plan_id && !batch.auto_executed);
  }
  _entityLabel(entityId) {
    const friendly = this.hass?.states?.[entityId]?.attributes?.friendly_name;
    return friendly || humanizeEntityId(entityId);
  }
  async _decide(item, decision) {
    if (!this.hass || this._busy) return;
    this._busy = item.work_item_id;
    this._actionError = null;
    try {
      const updated = await this.hass.callWS({
        type: "hamie/maintenance/decide",
        work_item_id: item.work_item_id,
        decision
      });
      if (decision === "keep") {
        this._workItems = this._workItems.filter((entry) => entry.work_item_id !== item.work_item_id);
      } else {
        this._workItems = this._workItems.map(
          (entry) => entry.work_item_id === item.work_item_id ? updated : entry
        );
      }
      this.dispatchEvent(new CustomEvent("hamie-data-changed", { bubbles: true, composed: true }));
    } catch (err) {
      this._actionError = friendlyError(err, "That decision could not be recorded.");
    } finally {
      this._busy = null;
    }
  }
  async _gatherEvidence(item) {
    if (!this.hass || this._busy) return;
    this._busy = item.work_item_id;
    this._actionError = null;
    try {
      const result = await this.hass.callWS({
        type: "hamie/remediation/gather_evidence",
        work_item_id: item.work_item_id
      });
      if (result.resolved) {
        this._workItems = this._workItems.filter((entry) => entry.work_item_id !== item.work_item_id);
      }
      this.dispatchEvent(new CustomEvent("hamie-data-changed", { bubbles: true, composed: true }));
    } catch (err) {
      this._actionError = friendlyError(err, "Evidence could not be gathered.");
    } finally {
      this._busy = null;
    }
  }
  _openDisable(batch) {
    this._pendingDisable = { batch, step: "confirm" };
  }
  _cancelDisable() {
    this._pendingDisable = null;
  }
  async _confirmDisable() {
    if (!this.hass || !this._pendingDisable) return;
    const { batch } = this._pendingDisable;
    this._busy = batch.remediation_plan_id;
    this._actionError = null;
    try {
      const preview = await this.hass.callWS({
        type: "hamie/remediation/preview/generate",
        remediation_plan_id: batch.remediation_plan_id,
        idempotency_token: idempotencyToken()
      });
      const approval = await this.hass.callWS({
        type: "hamie/remediation/approve",
        remediation_plan_id: batch.remediation_plan_id,
        plan_fingerprint: preview.plan_fingerprint,
        preview_digest: preview.preview_digest,
        destructive_acknowledged: false,
        backup_acknowledged: false,
        warnings_acknowledged: [],
        idempotency_token: idempotencyToken()
      });
      await this.hass.callWS({
        type: "hamie/remediation/execute",
        remediation_plan_id: batch.remediation_plan_id,
        approval_id: approval.approval_id,
        idempotency_token: idempotencyToken(),
        confirmed: true
      });
      this._batches = this._batches.map(
        (entry) => entry.remediation_plan_id === batch.remediation_plan_id ? { ...entry, auto_executed: true, execution_succeeded: true } : entry
      );
      this._pendingDisable = null;
      this.dispatchEvent(new CustomEvent("hamie-data-changed", { bubbles: true, composed: true }));
    } catch (err) {
      this._actionError = friendlyError(err, "That batch could not be disabled.");
      this._pendingDisable = null;
    } finally {
      this._busy = null;
    }
  }
  _renderReady() {
    const ready = this._readyBatches();
    if (!ready.length) {
      return b2`<hamie-empty tone="positive" heading="Nothing new to disable" description="No batches are currently awaiting approval."></hamie-empty>`;
    }
    return ready.map((batch) => {
      const expanded = this._expandedBatch === batch.remediation_plan_id;
      const members = batch.entity_ids || [];
      const shown = expanded ? members.slice(0, 100) : [];
      return b2`
        <div class="group-row" style="flex-direction: column; align-items: stretch">
          <div class="group-row" style="border: none; padding: 0">
            <div>
              <p class="group-title">${batch.batch_label}</p>
              <p class="group-meta">
                ${batch.entity_count} entit${batch.entity_count === 1 ? "y" : "ies"} — no dependencies were found in the sources HAMIE checked. Disabled entities remain in Home Assistant's registry and can be re-enabled later.
              </p>
            </div>
            <div class="group-actions">
              <hamie-button
                variant="ghost"
                size="xs"
                @click=${() => this._expandedBatch = expanded ? null : batch.remediation_plan_id}
              >
                ${expanded ? "Collapse" : `Review ${batch.entity_count}`}
              </hamie-button>
              <hamie-button
                variant="primary"
                size="sm"
                ?disabled=${this._busy === batch.remediation_plan_id}
                @click=${() => this._openDisable(batch)}
              >
                Disable ${batch.entity_count}
              </hamie-button>
            </div>
          </div>
          ${expanded ? b2`
                <div class="members">
                  ${shown.map(
        (entityId) => b2`
                      <div class="member-row">
                        <span class="name">${this._entityLabel(entityId)}</span>
                        <span class="id">${entityId}</span>
                      </div>
                    `
      )}
                  ${members.length > shown.length ? b2`<span class="members-more">+${members.length - shown.length} more</span>` : null}
                </div>
              ` : null}
        </div>
      `;
    });
  }
  _renderWorkItems(tab) {
    const items = this._itemsForTab(tab);
    if (!items.length) {
      return b2`<hamie-empty tone="positive" heading="Nothing here" description="No items in this category right now."></hamie-empty>`;
    }
    return items.map((item) => {
      const busy = this._busy === item.work_item_id;
      return b2`
        <div class="group-row">
          <div>
            <p class="group-title">${item.title}</p>
            <p class="group-meta">
              ${item.entity_count} entit${item.entity_count === 1 ? "y" : "ies"} — ${item.reason}
              ${item.missing_evidence?.length ? b2` Not yet checked: ${item.missing_evidence.join(", ")}.` : null}
            </p>
          </div>
          <div class="group-actions">
            ${tab !== "protected" ? b2`<hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._gatherEvidence(item)}>Gather Evidence</hamie-button>` : null}
            <hamie-button variant="ghost" size="xs" ?disabled=${busy} @click=${() => this._decide(item, "unsure")}>Unsure</hamie-button>
            <hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._decide(item, "keep")}>Keep</hamie-button>
          </div>
        </div>
      `;
    });
  }
  render() {
    if (!this.summary) return null;
    const buckets = this._bucketCounts();
    const readyBatches = this._readyBatches();
    const readyEntityTotal = readyBatches.reduce((sum, batch) => sum + batch.entity_count, 0);
    const heading = readyEntityTotal > 0 ? `${readyEntityTotal} candidate${readyEntityTotal === 1 ? "" : "s"} ready for review` : buckets.protected + buckets.needs_evidence + buckets.integration_issue > 0 ? "Investigation needed" : "No maintenance needed";
    return b2`
      <hamie-drawer
        wide
        .open=${this.open}
        heading="Cleanup review"
        description=${heading}
        .onClose=${() => this.dispatchEvent(new CustomEvent("hamie-cleanup-review-closed", { bubbles: true, composed: true }))}
      >
        ${this._actionError ? b2`
              <div class="action-error" role="alert">
                <span>${this._actionError}</span>
                <hamie-button variant="ghost" size="xs" aria-label="Dismiss" @click=${() => this._actionError = null}>
                  <ha-icon icon="mdi:close"></ha-icon>
                </hamie-button>
              </div>
            ` : null}

        <div class="summary-row">
          <div class="stat"><strong>${readyEntityTotal}</strong><span>Safe to disable</span></div>
          <div class="stat"><strong>${buckets.protected}</strong><span>Protected</span></div>
          <div class="stat"><strong>${buckets.needs_evidence}</strong><span>Need evidence</span></div>
          ${buckets.integration_issue ? b2`<div class="stat"><strong>${buckets.integration_issue}</strong><span>Integration issues</span></div>` : null}
        </div>

        <div class="tabs" role="tablist">
          ${TABS.filter((tab) => tab.id !== "integration_issue" || buckets.integration_issue > 0).map((tab) => {
      const count = tab.id === "ready" ? readyBatches.length : buckets[tab.id];
      return b2`
              <button role="tab" aria-selected=${this._tab === tab.id} @click=${() => this._tab = tab.id}>
                ${tab.label} (${count})
              </button>
            `;
    })}
        </div>

        ${this._tab === "ready" ? this._renderReady() : this._renderWorkItems(this._tab)}
      </hamie-drawer>

      ${this._pendingDisable ? b2`
            <hamie-dialog
              open
              heading="Disable ${this._pendingDisable.batch.entity_count} entities?"
              description="These entities will remain in Home Assistant's entity registry but will no longer load normally. This is reversible -- re-enable them any time."
              confirm-label="Disable ${this._pendingDisable.batch.entity_count} entities"
              ?busy=${this._busy === this._pendingDisable.batch.remediation_plan_id}
              .onConfirm=${() => this._confirmDisable()}
              .onCancel=${() => this._cancelDisable()}
            ></hamie-dialog>
          ` : null}
    `;
  }
};
if (!customElements.get("hamie-cleanup-review")) {
  customElements.define("hamie-cleanup-review", HamieCleanupReview);
}

// hamie/frontend/views/hamie-view-overview.js
var CONNECTOR_ICON = {
  ollama: "mdi:brain",
  n8n: "mdi:sitemap-outline",
  mcp: "mdi:server-network-outline",
  hkg: "mdi:graph-outline"
};
var CONNECTOR_STATUS_TONE = {
  healthy: "healthy",
  degraded: "warning",
  error: "critical",
  disabled: "offline",
  unknown: "unknown"
};
var CONNECTOR_STATUS_LABEL = {
  healthy: "Healthy",
  degraded: "Degraded",
  error: "Offline",
  disabled: "Disabled",
  unknown: "Checking\u2026"
};
var HamieViewOverview = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _overview: { state: true },
    _reviewQueue: { state: true },
    _security: { state: true },
    _scheduler: { state: true },
    _error: { state: true },
    _scanning: { state: true },
    _cleanupRunning: { state: true },
    _cleanupSummary: { state: true },
    _cleanupError: { state: true },
    _registryReady: { state: true },
    _reviewOpen: { state: true }
  };
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .stack {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-4);
    }
    .grid-top {
      display: grid;
      grid-template-columns: 3fr 2fr;
      gap: var(--hamie-space-4);
      align-items: stretch;
    }
    .grid-bottom {
      display: grid;
      grid-template-columns: 3fr 2fr;
      gap: var(--hamie-space-4);
      align-items: start;
    }
    @media (max-width: 1100px) {
      .grid-top,
      .grid-bottom {
        grid-template-columns: 1fr;
      }
    }
    .cleanup-panel {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
      height: 100%;
      box-sizing: border-box;
    }
    .cleanup-panel-primary {
      display: flex;
      align-items: baseline;
      gap: var(--hamie-space-2);
    }
    .cleanup-panel-value {
      font-size: var(--hamie-text-display);
      font-weight: var(--hamie-weight-bold);
      color: var(--hamie-status-healthy);
      line-height: 1;
    }
    .cleanup-panel-label {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
    }
    .cleanup-panel-explainer {
      margin: 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.5;
    }
    .type-badge {
      padding: 0 var(--hamie-space-1-5);
      border-radius: var(--hamie-radius-sm);
      background: var(--hamie-surface-raised);
      color: var(--hamie-text-secondary);
      font-size: var(--hamie-text-caption);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
    }
    .issue-count {
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-bold);
      color: var(--hamie-text-primary);
    }
    .issue-count-label {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .banner {
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
      font-size: var(--hamie-text-small);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .attention {
      padding: var(--hamie-space-3) var(--hamie-space-4);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg);
    }
    .attention-stats {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: var(--hamie-space-5);
      margin-top: var(--hamie-space-2);
    }
    .attention-stat {
      display: flex;
      align-items: baseline;
      gap: var(--hamie-space-1-5);
      background: none;
      border: 0;
      padding: 0;
      font: inherit;
      color: inherit;
      cursor: default;
    }
    button.attention-stat {
      cursor: pointer;
      border-radius: var(--hamie-radius-sm);
    }
    button.attention-stat:hover {
      color: var(--hamie-accent);
    }
    button.attention-stat:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 3px;
    }
    button.attention-stat:disabled {
      cursor: default;
      opacity: 0.6;
    }
    .attention-hint {
      margin: var(--hamie-space-2) 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .attention-value {
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-bold);
      color: var(--hamie-text-primary);
    }
    .attention-value.strong {
      color: var(--hamie-accent);
    }
    .attention-value.critical {
      color: var(--hamie-status-critical);
    }
    .attention-label {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .top-issues-list {
      display: flex;
      flex-direction: column;
    }
    .top-issues-list > * + * {
      border-top: 1px solid var(--hamie-border-hairline);
    }
    .issue-icon {
      width: 32px;
      height: 32px;
      border-radius: var(--hamie-radius-md);
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--hamie-surface-raised);
    }
    .issue-icon ha-icon {
      --mdc-icon-size: 16px;
      color: var(--hamie-text-secondary);
    }
    .cleanup-result {
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg);
      padding: var(--hamie-space-4);
    }
    .cleanup-result-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .cleanup-result-heading {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .cleanup-result-sub {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .cleanup-detail-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: var(--hamie-space-3);
      margin-top: var(--hamie-space-3);
    }
    .cleanup-detail-tile .value {
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .cleanup-detail-tile .label {
      font-size: var(--hamie-text-caption);
      color: var(--hamie-text-secondary);
    }
    .connectors-row {
      display: flex;
      flex-wrap: wrap;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-2);
    }
    .connector-chip {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      padding: var(--hamie-space-1-5) var(--hamie-space-3);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-pill);
      font-size: var(--hamie-text-micro);
      background: none;
      color: inherit;
      font-family: inherit;
      cursor: pointer;
    }
    .connector-chip:hover {
      border-color: var(--hamie-accent);
    }
    .connector-chip:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 2px;
    }
    .connector-chip[data-disabled] {
      opacity: 0.55;
    }
    .connector-chip ha-icon {
      --mdc-icon-size: 14px;
    }
    @media (max-width: 700px) {
      .connectors-row {
        display: none;
      }
    }
    .hamie-health-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: var(--hamie-space-3);
    }
    .hamie-health-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-2);
      padding: var(--hamie-space-2) 0;
      border-bottom: 1px solid var(--hamie-border-hairline);
      font-size: var(--hamie-text-small);
    }
    .hamie-health-row:last-child {
      border-bottom: none;
    }
    .hamie-health-label {
      color: var(--hamie-text-secondary);
    }
    .hamie-health-value {
      color: var(--hamie-text-primary);
      text-align: right;
    }
    .pending-note {
      font-size: var(--hamie-text-caption);
      color: var(--hamie-text-secondary);
      font-style: italic;
    }
  `;
  connectedCallback() {
    super.connectedCallback();
    this._load();
    this._onLiveUpdate = () => this._load();
    window.addEventListener("hamie-live-update", this._onLiveUpdate);
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("hamie-live-update", this._onLiveUpdate);
  }
  async _load() {
    if (!this.hass) return;
    try {
      const [overview, reviewQueue, security, scheduler] = await Promise.all([
        this.hass.callWS({ type: "hamie/explorer/overview" }),
        this.hass.callWS({ type: "hamie/remediation/queue/list", offset: 0, limit: 5 }).catch(() => null),
        this.hass.callWS({ type: "hamie/security/findings" }).catch(() => null),
        this.hass.callWS({ type: "hamie/scheduler/status" }).catch(() => null)
      ]);
      this._overview = overview;
      this._reviewQueue = reviewQueue;
      this._security = security;
      this._scheduler = scheduler;
      this._error = null;
      primeHaRegistry(this.hass).then(() => {
        this._registryReady = true;
      });
    } catch (err) {
      this._error = friendlyError(err, "Overview data is temporarily unavailable.");
    }
  }
  _onViewGroups() {
    this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "groups" }, bubbles: true, composed: true }));
  }
  _onViewReviewQueue(status) {
    this.dispatchEvent(
      new CustomEvent("hamie-navigate", { detail: { id: "remediation", status }, bubbles: true, composed: true })
    );
  }
  async _onScanNow() {
    if (!this.hass) return;
    this._scanning = true;
    try {
      await this.hass.callService("hamie", "scan", {});
      await this._load();
      this.dispatchEvent(new CustomEvent("hamie-data-changed", { bubbles: true, composed: true }));
    } catch (err) {
      this._error = friendlyError(err, "The scan could not be completed.");
    } finally {
      this._scanning = false;
    }
  }
  async _onCleanUp() {
    if (!this.hass || this._cleanupRunning) return;
    this._cleanupRunning = true;
    this._cleanupError = null;
    this._cleanupSummary = null;
    try {
      this._cleanupSummary = await this.hass.callWS({ type: "hamie/cleanup/run" });
      await this._load();
      this.dispatchEvent(new CustomEvent("hamie-data-changed", { bubbles: true, composed: true }));
      const hasReviewableWork = (this._cleanupSummary.batches || []).some((batch) => batch.remediation_plan_id && !batch.auto_executed) || (this._cleanupSummary.persisted_maintenance_work_items || []).some((item) => item.lifecycle_state !== "completed");
      if (hasReviewableWork) this._reviewOpen = true;
    } catch (err) {
      this._cleanupError = friendlyError(err, "Clean up could not be completed.");
    } finally {
      this._cleanupRunning = false;
    }
  }
  _entityCount() {
    return this.hass?.states ? Object.keys(this.hass.states).length : null;
  }
  _activeAutomationCount() {
    if (!this.hass?.states) return null;
    return Object.values(this.hass.states).filter(
      (state) => state.entity_id.startsWith("automation.") && state.state === "on"
    ).length;
  }
  _totalAutomationCount() {
    if (!this.hass?.states) return null;
    return Object.values(this.hass.states).filter((state) => state.entity_id.startsWith("automation.")).length;
  }
  // Real, already-configured Home Assistant integration count (distinct
  // config entries), primed via the same registry fetch used for group
  // display-name resolution -- null (rendered as "—") until that
  // primes, never a placeholder number.
  _integrationsCount() {
    return configEntryCount();
  }
  // Automation Health: the real fraction of this installation's own
  // automation.* entities that are currently enabled/active, from
  // hass.states directly -- not "broken reference" detection (HAMIE has
  // no per-scan dependency capture cheap enough to run on every scan at
  // 6,500-entity scale), but a real, always-available, honestly-labeled
  // proxy for the same underlying question.
  _automationHealth() {
    const total = this._totalAutomationCount();
    const active = this._activeAutomationCount();
    if (!total) return null;
    return Math.round(100 * active / total);
  }
  // Security Health: derived from the real hamie/security/findings
  // count already fetched for this same page -- each real finding costs
  // 20 points, floor 0. A simple, deterministic, documented formula,
  // never a fabricated score.
  _securityHealth() {
    if (!this._security) return null;
    return Math.max(0, 100 - 20 * this._security.total);
  }
  // Deterministic single "what should I do next" choice from real,
  // already-loaded state -- never a second, independent priority
  // heuristic duplicating the classifier; this only reads counts the
  // classifier/queue service already produced.
  _nextAction(overview, queueCounts, workItems, hasScanned, cleanupAnalyzed, cleanupEverRan) {
    const readyToExecute = queueCounts.ready_to_execute || 0;
    if (readyToExecute > 0) {
      return {
        icon: "mdi:rocket-launch-outline",
        heading: `${readyToExecute} approved fix${readyToExecute === 1 ? "" : "es"} ${readyToExecute === 1 ? "is" : "are"} ready`,
        description: "These were reviewed and approved and are waiting to run.",
        actionLabel: "Execute",
        onAction: () => this._onViewReviewQueue("ready_to_execute")
      };
    }
    const safeCleanup = (queueCounts.ready_for_review || 0) + (queueCounts.awaiting_approval || 0);
    if (safeCleanup > 0) {
      return {
        icon: "mdi:broom",
        heading: `${safeCleanup} item${safeCleanup === 1 ? "" : "s"} appear${safeCleanup === 1 ? "s" : ""} safe to disable`,
        description: "No local Home Assistant dependencies were found for these.",
        actionLabel: "Review cleanup",
        onAction: () => this._onViewReviewQueue("ready_for_review")
      };
    }
    const needsEvidence = workItems.filter((item) => item.lifecycle_state === "needs_evidence").length;
    if (needsEvidence > 0) {
      return {
        icon: "mdi:magnify-scan",
        heading: `${needsEvidence} item${needsEvidence === 1 ? "" : "s"} need${needsEvidence === 1 ? "s" : ""} more evidence`,
        description: "HAMIE couldn't fully verify these are safe to touch yet.",
        actionLabel: "Gather evidence",
        onAction: () => this._onViewReviewQueue()
      };
    }
    if ((overview.open_findings || 0) > 0 && !cleanupAnalyzed) {
      if (cleanupEverRan) {
        return {
          icon: "mdi:refresh",
          heading: "Maintenance evidence changed",
          description: "Home Assistant changed since the last cleanup analysis.",
          actionLabel: this._cleanupRunning ? "Analyzing\u2026" : "Refresh cleanup",
          onAction: () => this._onCleanUp()
        };
      }
      return {
        icon: "mdi:broom",
        heading: `${overview.open_findings} finding${overview.open_findings === 1 ? "" : "s"} ${overview.open_findings === 1 ? "hasn't" : "haven't"} been analyzed for cleanup yet`,
        description: "Clean Up classifies every open finding and proposes what's safe to disable.",
        actionLabel: this._cleanupRunning ? "Analyzing\u2026" : "Clean Up",
        onAction: () => this._onCleanUp()
      };
    }
    if (!hasScanned) {
      return {
        icon: "mdi:magnify",
        heading: "Run your first scan",
        description: "HAMIE hasn't scanned this Home Assistant installation yet.",
        actionLabel: this._scanning ? "Scanning\u2026" : "Scan now",
        onAction: () => this._onScanNow()
      };
    }
    return null;
  }
  _renderCleanupResult() {
    const summary = this._cleanupSummary;
    const safeCleanup = summary.actionable_candidate_count || 0;
    const autoDisabled = summary.entities_auto_disabled || 0;
    const workItems = summary.maintenance_work_items || [];
    const counts = summary.classification_counts || {};
    const hasReviewableWork = safeCleanup > 0 || autoDisabled > 0 || workItems.length > 0;
    const heading = autoDisabled > 0 ? `${autoDisabled} entit${autoDisabled === 1 ? "y" : "ies"} disabled automatically` : safeCleanup > 0 ? "Cleanup review ready" : workItems.length > 0 ? "Investigation needed" : "No maintenance needed";
    return b2`
      <div class="cleanup-result">
        <div class="cleanup-result-row">
          <div>
            <p class="cleanup-result-heading">${heading}</p>
            <p class="cleanup-result-sub">
              ${summary.total_findings_considered} finding${summary.total_findings_considered === 1 ? "" : "s"} analyzed
            </p>
          </div>
          ${hasReviewableWork ? b2`<hamie-button variant="primary" size="sm" @click=${() => this._reviewOpen = true}>Review</hamie-button>` : b2`<hamie-button variant="ghost" size="xs" @click=${() => this._cleanupSummary = null}>Dismiss</hamie-button>`}
        </div>
        <hamie-disclosure label="Details">
          <div class="cleanup-detail-grid">
            <div class="cleanup-detail-tile"><div class="value">${safeCleanup}</div><div class="label">Safe candidates</div></div>
            <div class="cleanup-detail-tile"><div class="value">${counts.blocked_dependency || 0}</div><div class="label">Protected</div></div>
            <div class="cleanup-detail-tile"><div class="value">${counts.blocked_uncertain || 0}</div><div class="label">Needs evidence</div></div>
            <div class="cleanup-detail-tile"><div class="value">${counts.transient_issue || 0}</div><div class="label">Transient</div></div>
            <div class="cleanup-detail-tile"><div class="value">${(counts.expected_behavior || 0) + (counts.already_clean || 0)}</div><div class="label">Expected</div></div>
            <div class="cleanup-detail-tile"><div class="value">${(counts.manual_review || 0) + (counts.parent_integration_failure || 0)}</div><div class="label">Manual review</div></div>
          </div>
          ${summary.dependency_unscanned_sources?.length ? b2`<p class="cleanup-result-sub" style="margin-top: var(--hamie-space-3)">
                Not checked: ${summary.dependency_unscanned_sources.join(", ")}.
              </p>` : null}
        </hamie-disclosure>
      </div>
    `;
  }
  _groupDisplayName(group) {
    const facets = group.facets || {};
    return resolveDisplayName(
      {
        configEntryId: facets.config_entry_id?.[0],
        deviceId: facets.device_id?.[0],
        integrationDomain: facets.integration_domain?.[0]
      },
      group.title
    );
  }
  render() {
    if (this._error) {
      return b2`<hamie-empty tone="unavailable" heading="Overview data is unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._overview) {
      return b2`<hamie-loading .lines=${4}></hamie-loading>`;
    }
    const overview = this._overview;
    const entities = this._entityCount();
    const automations = this._activeAutomationCount();
    const health = overview.availability_health;
    const hasScanned = Boolean(overview.last_scan);
    const hasHealth = health !== null && health !== void 0;
    const operational = overview.operational_health;
    const hasOperational = operational !== null && operational !== void 0;
    const operationalHealthy = hasOperational && operational >= 90;
    const tone = !hasScanned || !hasOperational ? "unknown" : operationalHealthy ? "healthy" : operational >= 70 ? "warning" : "critical";
    const queueCounts = this._reviewQueue?.section_counts || {};
    const workItems = this._reviewQueue?.maintenance_work_items || [];
    const safeCleanup = (queueCounts.ready_for_review || 0) + (queueCounts.awaiting_approval || 0) + (queueCounts.ready_to_execute || 0);
    const protectedCount = workItems.filter((item) => item.lifecycle_state === "dependency_blocked").length;
    const needsEvidenceCount = workItems.filter((item) => item.lifecycle_state === "needs_evidence").length;
    const hasMaintenanceDebt = safeCleanup + needsEvidenceCount + protectedCount + (overview.open_findings || 0) > 0;
    const cleanupAnalyzed = Boolean(this._reviewQueue?.last_cleanup_scan_id) && this._reviewQueue.last_cleanup_scan_id === overview.last_scan_id;
    const healthWord = !hasScanned ? "not yet scanned" : !hasOperational ? "of unknown health" : !operationalHealthy ? "in need of attention" : hasMaintenanceDebt ? "mostly healthy" : "healthy";
    const scanClause = hasScanned ? `last scan completed ${relativeTime(overview.last_scan)}` : "no scan has completed yet";
    const statusText = !hasScanned || !hasOperational ? "Your home's health is not yet known" : operationalHealthy ? hasMaintenanceDebt ? "Your home is mostly healthy" : "Your home is healthy" : "Your home needs attention";
    const connectors = overview.connectors || [];
    const dimensionTone = (value) => value == null ? "unknown" : value >= 90 ? "healthy" : value >= 70 ? "warning" : "critical";
    const dimensions = [
      { label: "Operational", value: overview.operational_health, tone: dimensionTone(overview.operational_health) },
      { label: "Maintenance", value: hasHealth ? health : null, tone: dimensionTone(hasHealth ? health : null) },
      { label: "Registry", value: overview.registry_cleanliness, tone: dimensionTone(overview.registry_cleanliness) },
      { label: "Automation", value: this._automationHealth(), tone: dimensionTone(this._automationHealth()) },
      { label: "Security", value: this._securityHealth(), tone: dimensionTone(this._securityHealth()) }
    ];
    const nextAction = this._nextAction(
      overview,
      queueCounts,
      workItems,
      hasScanned,
      cleanupAnalyzed,
      Boolean(this._reviewQueue?.last_cleanup_scan_id)
    );
    const topIssues = (overview.highest_priority_incidents || []).slice(0, 5);
    const integrations = this._integrationsCount();
    const cleanupSegments = [
      { label: "Safe to disable", value: safeCleanup, tone: "healthy" },
      { label: "Protected", value: protectedCount, tone: "info" },
      { label: "Needs evidence", value: needsEvidenceCount, tone: "evidence" },
      { label: "Blocked", value: queueCounts.failed || 0, tone: "warning" }
    ];
    const cleanupTotal = cleanupSegments.reduce((sum, item) => sum + item.value, 0);
    return b2`
      <div class="stack">
        <hamie-page-header
          heading=${timeOfDayGreeting()}
          subtitle="Your home is ${healthWord} — ${scanClause}${entities != null ? ` \xB7 ${entities.toLocaleString()} entities` : ""}${automations != null ? ` \xB7 ${automations} automations` : ""}${integrations != null ? ` \xB7 ${integrations} integrations` : ""}"
        >
          <div slot="actions">
            <hamie-button variant="secondary" size="sm" ?disabled=${this._scanning} @click=${this._onScanNow}>
              <ha-icon icon="mdi:refresh"></ha-icon> ${this._scanning ? "Scanning\u2026" : "Scan"}
            </hamie-button>
            <hamie-button variant="primary" size="sm" ?disabled=${this._cleanupRunning} @click=${this._onCleanUp}>
              <ha-icon icon="mdi:broom"></ha-icon> ${this._cleanupRunning ? "Analyzing\u2026" : "Clean Up"}
            </hamie-button>
          </div>
          ${connectors.length ? b2`
                <div class="connectors-row">
                  ${connectors.map((connector) => {
      const status = connector.enabled ? connector.status : "disabled";
      const token = CONNECTOR_STATUS_TONE[status] || "unknown";
      const statusLabel = CONNECTOR_STATUS_LABEL[status] || status;
      const label = connector.enabled ? `${connector.connector_id}: ${statusLabel}${connector.latency_ms != null ? ` \xB7 ${connector.latency_ms} ms` : ""}` : `${connector.connector_id}: Disabled`;
      return b2`
                      <button
                        type="button"
                        class="connector-chip"
                        ?data-disabled=${!connector.enabled}
                        title=${label}
                        aria-label=${label}
                        @click=${() => this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "connectors" }, bubbles: true, composed: true }))}
                      >
                        <ha-icon icon=${CONNECTOR_ICON[connector.connector_id] || "mdi:puzzle-outline"} style="color: var(--hamie-status-${token})"></ha-icon>
                        ${connector.connector_id}
                        ${connector.enabled ? b2`<hamie-status variant="dot" status=${token} label=${statusLabel}></hamie-status>` : null}
                      </button>
                    `;
    })}
                </div>
              ` : null}
        </hamie-page-header>

        ${this._cleanupError ? b2`
              <div class="banner">
                <span>${this._cleanupError}</span>
                <hamie-button variant="ghost" size="xs" @click=${() => this._cleanupError = null}>Dismiss</hamie-button>
              </div>
            ` : null}
        ${this._cleanupRunning ? b2`<hamie-progress label="Cleaning analysis" stage="Checking dependencies…"></hamie-progress>` : null}
        ${this._cleanupSummary && !this._cleanupRunning ? this._renderCleanupResult() : null}

        <div class="grid-top">
          <hamie-status-summary
            .score=${hasHealth ? health : void 0}
            score-label="Home Health"
            status-text=${statusText}
            tone=${tone}
            .dimensions=${dimensions}
          ></hamie-status-summary>

          ${nextAction ? b2`
                <hamie-action-card icon=${nextAction.icon} heading=${nextAction.heading} description=${nextAction.description}>
                  <hamie-button variant="primary" size="sm" @click=${nextAction.onAction}>${nextAction.actionLabel}</hamie-button>
                </hamie-action-card>
              ` : null}
        </div>

        <div class="attention">
          <hamie-section heading="Needs attention"></hamie-section>
          <div class="attention-stats">
            <button type="button" class="attention-stat" @click=${() => this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "incidents" }, bubbles: true, composed: true }))}>
              <span class="attention-value">${overview.active_incidents || 0}</span>
              <span class="attention-label">incidents</span>
            </button>
            <button
              type="button"
              class="attention-stat"
              ?disabled=${!cleanupAnalyzed}
              @click=${() => this._onViewReviewQueue("ready_for_review")}
            >
              <span class="attention-value strong">${cleanupAnalyzed ? safeCleanup : "\u2014"}</span>
              <span class="attention-label">safe cleanup</span>
            </button>
            <button
              type="button"
              class="attention-stat"
              ?disabled=${!cleanupAnalyzed}
              @click=${() => this._onViewReviewQueue()}
            >
              <span class="attention-value">${cleanupAnalyzed ? protectedCount : "\u2014"}</span>
              <span class="attention-label">protected</span>
            </button>
            <button
              type="button"
              class="attention-stat"
              ?disabled=${!cleanupAnalyzed}
              @click=${() => this._onViewReviewQueue()}
            >
              <span class="attention-value">${cleanupAnalyzed ? needsEvidenceCount : "\u2014"}</span>
              <span class="attention-label">need more evidence</span>
            </button>
            <span class="attention-stat">
              <span class="attention-value ${overview.critical_findings ? "critical" : ""}">${overview.critical_findings || 0}</span>
              <span class="attention-label">critical</span>
            </span>
          </div>
          ${!cleanupAnalyzed && overview.open_findings > 0 ? b2`<p class="attention-hint">${overview.open_findings} finding${overview.open_findings === 1 ? "" : "s"} haven't been classified for cleanup yet -- run Clean Up to see safe/protected/needs-evidence counts.</p>` : null}
        </div>

        <hamie-card padding="md">
          <hamie-section
            heading="HAMIE health"
            description="HAMIE's own scan and evidence-source status -- separate from your home's health above."
          ></hamie-section>
          <div class="hamie-health-grid">
            <div>
              <div class="hamie-health-row">
                <span class="hamie-health-label">Last scan</span>
                <span class="hamie-health-value">${overview.last_scan ? relativeTime(overview.last_scan) : "Never"}</span>
              </div>
              <div class="hamie-health-row">
                <span class="hamie-health-label">Next scan</span>
                <span class="hamie-health-value">
                  ${this._scheduler?.auto_scan_enabled ? this._scheduler.next_scan_seconds != null ? `In ${Math.max(0, Math.round(this._scheduler.next_scan_seconds / 60))} min` : "Pending first scan" : "Automatic scanning is off"}
                </span>
              </div>
              <div class="hamie-health-row">
                <span class="hamie-health-label">Scan coverage</span>
                <span class="hamie-health-value">${overview.coverage || "unknown"}</span>
              </div>
              ${this._scheduler?.last_scan_error_summary ? b2`
                    <div class="hamie-health-row">
                      <span class="hamie-health-label">Last scan error</span>
                      <span class="hamie-health-value" style="color: var(--hamie-status-critical)">${this._scheduler.last_scan_error_summary}</span>
                    </div>
                  ` : null}
            </div>
            <div>
              <div class="hamie-health-row">
                <span class="hamie-health-label">Temporal (recorder) evidence</span>
                <span class="hamie-health-value"><hamie-status variant="dot" status="unknown" label="Pending activation"></hamie-status></span>
              </div>
              <div class="hamie-health-row">
                <span class="hamie-health-label">Source-definition index</span>
                <span class="hamie-health-value"><hamie-status variant="dot" status="unknown" label="Pending activation"></hamie-status></span>
              </div>
              <div class="hamie-health-row">
                <span class="hamie-health-label">Duplicate/migration index</span>
                <span class="hamie-health-value"><hamie-status variant="dot" status="unknown" label="Pending activation"></hamie-status></span>
              </div>
              <p class="pending-note">
                These three evidence sources exist in HAMIE's installed code but are not yet wired into a running scan or served by any command -- shown honestly as pending rather than omitted.
              </p>
            </div>
          </div>
        </hamie-card>

        <div class="grid-bottom">
          <div>
            <hamie-section heading="Top issues"></hamie-section>
            ${topIssues.length === 0 ? b2`<hamie-empty tone="positive" heading="No issues found"></hamie-empty>` : b2`
                  <div class="top-issues-list">
                    ${topIssues.map((incident) => {
      const status = ["p0", "p1"].includes(incident.priority) ? "critical" : incident.priority === "p2" ? "warning" : "info";
      return b2`
                        <hamie-issue-row
                          interactive
                          title=${incident.title}
                          meta="${incident.evidence_status.replaceAll("_", " ")}"
                          @hamie-row-click=${() => this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "incidents" }, bubbles: true, composed: true }))}
                        >
                          <span slot="leading" class="issue-icon"><ha-icon icon="mdi:alert-decagram-outline"></ha-icon></span>
                          <span slot="extra" class="issue-count">${incident.affected_subject_count}</span>
                          <span slot="extra" class="issue-count-label">affected</span>
                          <hamie-status slot="trailing" status=${status} label=${incident.priority.toUpperCase()}></hamie-status>
                          <ha-icon slot="trailing" icon="mdi:chevron-right"></ha-icon>
                        </hamie-issue-row>
                      `;
    })}
                  </div>
                  <hamie-button variant="ghost" size="xs" @click=${() => this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "incidents" }, bubbles: true, composed: true }))}>
                    View all ${overview.active_incidents ?? topIssues.length} incidents <ha-icon icon="mdi:arrow-right"></ha-icon>
                  </hamie-button>
                `}
          </div>

          <hamie-card padding="md">
            <div class="cleanup-panel">
              <hamie-section heading="Cleanup candidates"></hamie-section>
              ${!cleanupAnalyzed ? b2`
                    <div class="cleanup-panel-primary">
                      <span class="cleanup-panel-value">—</span>
                      <span class="cleanup-panel-label">Not analyzed</span>
                    </div>
                    <p class="cleanup-panel-explainer">Run Clean Up to classify current maintenance findings.</p>
                    <hamie-button variant="primary" size="sm" ?disabled=${this._cleanupRunning} @click=${this._onCleanUp}>
                      ${this._cleanupRunning ? "Analyzing\u2026" : "Clean Up"}
                    </hamie-button>
                  ` : b2`
                    <div class="cleanup-panel-primary">
                      <span class="cleanup-panel-value">${safeCleanup}</span>
                      <span class="cleanup-panel-label">Safe to disable</span>
                    </div>
                    ${cleanupTotal > 0 ? b2`<hamie-donut .segments=${cleanupSegments}></hamie-donut>` : null}
                    <p class="cleanup-panel-explainer">
                      ${safeCleanup > 0 ? "These entities appear unused and can be disabled without impacting your automations or dashboards." : needsEvidenceCount > 0 ? `No safe cleanup candidates found. ${needsEvidenceCount} item${needsEvidenceCount === 1 ? "" : "s"} need more evidence before HAMIE can recommend a change.` : "No safe cleanup candidates found. HAMIE found no cleanup work requiring your attention."}
                    </p>
                    <hamie-button variant="secondary" size="sm" @click=${() => this._onViewReviewQueue()}>
                      Go to Review Queue <ha-icon icon="mdi:arrow-right"></ha-icon>
                    </hamie-button>
                  `}
            </div>
          </hamie-card>
        </div>
      </div>

      <hamie-cleanup-review
        .hass=${this.hass}
        .open=${Boolean(this._reviewOpen)}
        .summary=${this._cleanupSummary}
        @hamie-cleanup-review-closed=${() => this._reviewOpen = false}
        @hamie-data-changed=${() => this._load()}
      ></hamie-cleanup-review>
    `;
  }
};
if (!customElements.get("hamie-view-overview")) {
  customElements.define("hamie-view-overview", HamieViewOverview);
}

// hamie/frontend/findings-status.js
function realFindingStatus(item) {
  if (item.lifecycle === "resolved") return "resolved";
  if (item.review_state === "snoozed") return "snoozed";
  return "open";
}
function findingStatusToken(item) {
  const status = realFindingStatus(item);
  if (status === "resolved") return { status: "healthy", label: "resolved" };
  if (status === "snoozed") return { status: "idle", label: "snoozed" };
  const openColor = item.severity === "warning" || item.severity === "critical" ? item.severity : "info";
  return { status: openColor, label: "open" };
}
function groupFindingsBy(items, field, { fallbackLabel = "Unknown" } = {}) {
  const groups = /* @__PURE__ */ new Map();
  for (const item of items) {
    const key = item[field] || fallbackLabel;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  return [...groups.entries()].map(([key, groupItems]) => {
    const hasCritical = groupItems.some((i7) => i7.severity === "critical");
    const hasWarning = groupItems.some((i7) => i7.severity === "warning");
    const status = hasCritical ? "critical" : hasWarning ? "warning" : "info";
    return { key, count: groupItems.length, status };
  });
}

// hamie/frontend/components/hamie-input.js
var HamieInput = class extends i4 {
  static properties = {
    value: { type: String },
    placeholder: { type: String },
    icon: { type: String },
    // mdi:* icon name
    type: { type: String },
    // "text" (default) | "password" | "url"
    disabled: { type: Boolean, reflect: true }
  };
  static styles = i`
    :host {
      display: block;
      position: relative;
    }
    ha-icon {
      position: absolute;
      left: var(--hamie-space-2-5);
      top: 50%;
      transform: translateY(-50%);
      --mdc-icon-size: 12px;
      color: var(--hamie-text-secondary);
      pointer-events: none;
    }
    input {
      width: 100%;
      box-sizing: border-box;
      font-family: inherit;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
      background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-normal);
      border-radius: var(--hamie-radius-md);
      padding: var(--hamie-space-1-5) var(--hamie-space-3);
      transition: border-color var(--hamie-motion-fast) var(--hamie-motion-ease);
    }
    :host([icon]) input {
      padding-left: calc(var(--hamie-space-2-5) + 12px + var(--hamie-space-1-5));
    }
    input::placeholder {
      color: var(--hamie-text-secondary);
    }
    input:focus {
      outline: none;
      border-color: var(--hamie-accent);
    }
    input:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  `;
  _onInput(event) {
    this.value = event.target.value;
    this.dispatchEvent(
      new CustomEvent("hamie-input", {
        detail: { value: this.value },
        bubbles: true,
        composed: true
      })
    );
  }
  render() {
    return b2`
      ${this.icon ? b2`<ha-icon icon=${this.icon}></ha-icon>` : null}
      <input
        type=${this.type || "text"}
        .value=${this.value || ""}
        placeholder=${this.placeholder || ""}
        ?disabled=${this.disabled}
        @input=${this._onInput}
      />
    `;
  }
};
if (!customElements.get("hamie-input")) {
  customElements.define("hamie-input", HamieInput);
}

// hamie/frontend/components/hamie-select.js
var HamieSelect = class extends i4 {
  static properties = {
    value: { type: String },
    options: { type: Array },
    // [{ value, label }]
    disabled: { type: Boolean, reflect: true }
  };
  static styles = i`
    :host {
      display: block;
    }
    select {
      width: 100%;
      box-sizing: border-box;
      font-family: inherit;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
      background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-normal);
      border-radius: var(--hamie-radius-md);
      padding: var(--hamie-space-1-5) var(--hamie-space-2-5);
      cursor: pointer;
    }
    select:focus {
      outline: none;
      border-color: var(--hamie-accent);
    }
    select:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  `;
  _onChange(event) {
    this.value = event.target.value;
    this.dispatchEvent(
      new CustomEvent("hamie-change", {
        detail: { value: this.value },
        bubbles: true,
        composed: true
      })
    );
  }
  render() {
    return b2`
      <select .value=${this.value || ""} ?disabled=${this.disabled} @change=${this._onChange}>
        ${(this.options || []).map(
      (opt) => b2`<option value=${opt.value} ?selected=${opt.value === this.value}>${opt.label}</option>`
    )}
      </select>
    `;
  }
};
if (!customElements.get("hamie-select")) {
  customElements.define("hamie-select", HamieSelect);
}

// hamie/frontend/views/hamie-view-findings.js
var QUICK_FILTERS = [
  { id: "all", label: "All" },
  { id: "actionable", label: "Actionable", key: "repairability", value: "Potentially safe to disable" },
  { id: "protected", label: "Protected", key: "classification", value: "Referenced entity" },
  { id: "needs_evidence", label: "Needs evidence", key: "repairability", value: "Needs more evidence" },
  { id: "transient", label: "Transient", key: "classification", value: "Transient unavailable" }
];
var PAGE_SIZE = 25;
var PAGE_SIZE_MAX = 100;
var SORT_OPTIONS = [
  ["priority", "Priority"],
  ["severity", "Severity"],
  ["dependency_risk", "Dependency risk"],
  ["affected_objects", "Affected objects"],
  ["confidence", "Confidence"],
  ["age", "Age"],
  ["recurrence", "Recurrence"],
  ["newness", "Newness"],
  ["group_size", "Group size"],
  ["user_priority", "User priority"],
  ["ai_advisory_priority", "AI advisory priority"]
].map(([value, label]) => ({ value, label }));
var GROUP_BY_OPTIONS = [
  ["integration", "Integration"],
  ["config_entry", "Config entry"],
  ["device", "Device"],
  ["category", "Category"],
  ["duration", "Duration"],
  ["repairability", "Repairability"],
  ["dependency_status", "Dependency status"],
  ["proposed_action", "Proposed action"]
].map(([value, label]) => ({ value, label }));
var SEVERITY_OPTIONS = ["info", "warning", "critical"];
var LIFECYCLE_OPTIONS = ["open", "resolved"];
var REVIEW_STATE_OPTIONS = ["new", "acknowledged", "snoozed", "retained", "dismissed"];
var DEPENDENCY_RISK_OPTIONS = ["low", "medium", "high", "critical"];
var AI_STATE_OPTIONS = ["none", "new", "acknowledged", "rejected", "retained", "expired", "stale"];
var GROUP_ACTIONS = [
  { id: "acknowledge", label: "Acknowledge", icon: "mdi:check-circle-outline" },
  { id: "snooze", label: "Snooze", icon: "mdi:clock-outline" },
  { id: "retain", label: "Retain", icon: "mdi:shield-check-outline" },
  { id: "dismiss", label: "Dismiss", icon: "mdi:close-circle-outline" },
  { id: "suppress", label: "Suppress", icon: "mdi:eye-off-outline" }
];
function withBlank(values) {
  return [{ value: "", label: "Any" }, ...values.map((value) => ({ value, label: value }))];
}
function formatDuration(seconds) {
  if (seconds == null) return null;
  if (seconds < 60) return "under a minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}
var HamieViewFindings = class extends i4 {
  static properties = {
    hass: { attribute: false },
    focusFindingId: { type: String },
    focusGroupId: { type: String },
    focusGroupTitle: { type: String },
    _items: { state: true },
    _total: { state: true },
    _error: { state: true },
    _quickFilter: { state: true },
    _search: { state: true },
    _sort: { state: true },
    _advancedOpen: { state: true },
    _advanced: { state: true },
    _offset: { state: true },
    _openCount: { state: true },
    _snoozedCount: { state: true },
    _resolvedCount: { state: true },
    _detailItem: { state: true },
    _pending: { state: true },
    _reason: { state: true },
    _actionError: { state: true },
    _busy: { state: true },
    _scanStatus: { state: true },
    _coverage: { state: true },
    _classificationCounts: { state: true },
    _groupingCounts: { state: true },
    _groupBy: { state: true },
    _registryReady: { state: true },
    _grouped: { state: true }
  };
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .toolbar {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-3);
      flex-wrap: wrap;
    }
    .search {
      width: 240px;
    }
    .filters {
      display: flex;
      align-items: center;
      gap: 2px;
      padding: var(--hamie-space-1);
      background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-md);
    }
    .filters button {
      padding: var(--hamie-space-1) var(--hamie-space-2-5);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      border-radius: var(--hamie-radius-sm);
      border: none;
      background: transparent;
      color: var(--hamie-text-secondary);
      cursor: pointer;
      font-family: inherit;
    }
    .filters button[aria-pressed="true"] {
      background: var(--hamie-accent-fill-loud);
      color: var(--hamie-accent-on);
    }
    .advanced-panel {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-hairline);
    }
    @media (max-width: 870px) {
      .advanced-panel {
        grid-template-columns: 1fr;
      }
    }
    .field label {
      display: block;
      font-size: var(--hamie-text-caption);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-text-secondary);
      margin-bottom: var(--hamie-space-1);
    }
    .advanced-actions {
      grid-column: 1 / -1;
      display: flex;
      gap: var(--hamie-space-2);
    }
    .entity {
      font-family: var(--hamie-font-code);
      font-size: var(--hamie-text-caption);
      color: var(--hamie-text-secondary);
    }
    .row-status {
      display: flex;
      align-items: baseline;
      gap: var(--hamie-space-1-5);
    }
    .pager {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--hamie-space-2-5) var(--hamie-space-1);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .list {
      display: flex;
      flex-direction: column;
    }
    .list > * + * {
      border-top: 1px solid var(--hamie-border-hairline);
    }
    .group-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-2) var(--hamie-space-4);
      background: var(--hamie-surface-raised);
      border-top: 1px solid var(--hamie-border-hairline);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-secondary);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
    }
    .group-header:first-child {
      border-top: none;
    }
    .group-header-count {
      text-transform: none;
      letter-spacing: normal;
      font-weight: var(--hamie-weight-medium);
    }
    .summary-line {
      margin: 0 0 var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .group-strip {
      display: flex;
      flex-wrap: wrap;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-2);
    }
    .summary-chip {
      padding: var(--hamie-space-1) var(--hamie-space-2);
      border-radius: var(--hamie-radius-sm);
      background: var(--hamie-surface-raised);
      color: var(--hamie-text-secondary);
      font-size: var(--hamie-text-micro);
    }
    .action-error {
      margin-bottom: var(--hamie-space-3);
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
      font-size: var(--hamie-text-small);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .drawer-eyebrow {
      margin: 0 0 var(--hamie-space-1);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .drawer-section {
      margin-bottom: var(--hamie-space-4);
    }
    .drawer-section h3 {
      margin: 0 0 var(--hamie-space-1-5);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-text-secondary);
    }
    .drawer-section p {
      margin: 0 0 var(--hamie-space-1);
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
      line-height: 1.5;
    }
    .drawer-actions {
      display: flex;
      gap: var(--hamie-space-2);
      flex-wrap: wrap;
      margin-top: var(--hamie-space-3);
    }
    .detail-meta {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.8;
    }
    .detail-list {
      margin: 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
  `;
  constructor() {
    super();
    this._quickFilter = "all";
    this._search = "";
    this._sort = "priority";
    this._advanced = {};
    this._offset = 0;
    this._groupBy = "integration";
    this._grouped = true;
  }
  connectedCallback() {
    super.connectedCallback();
    this._load();
    primeHaRegistry(this.hass).then(() => {
      this._registryReady = true;
    });
  }
  _buildFilters() {
    if (this.focusFindingId) return {};
    if (this.focusGroupId) return { group_id: this.focusGroupId };
    const filters = { ...this._advanced };
    const quick = QUICK_FILTERS.find((item) => item.id === this._quickFilter);
    if (quick?.key) filters[quick.key] = quick.value;
    return filters;
  }
  async _load() {
    if (!this.hass) return;
    try {
      if (this.focusFindingId) {
        const result2 = await this.hass.callWS({
          type: "hamie/explorer/findings",
          search: "",
          filters: {},
          sort: "priority",
          offset: 0,
          limit: PAGE_SIZE_MAX
        });
        this._items = result2.items.filter((item) => item.finding_id === this.focusFindingId);
        this._total = this._items.length;
        this._error = null;
        return;
      }
      const filters = this._buildFilters();
      const [result, openTotal, snoozedTotal, resolvedTotal, overview] = await Promise.all([
        this.hass.callWS({
          type: "hamie/explorer/findings",
          search: this._search,
          filters,
          sort: this._sort,
          offset: this._offset,
          limit: PAGE_SIZE
        }),
        this.hass.callWS({ type: "hamie/explorer/findings", search: "", filters: { lifecycle: "open" }, sort: "priority", offset: 0, limit: 1 }),
        this.hass.callWS({ type: "hamie/explorer/findings", search: "", filters: { lifecycle: "open", review_state: "snoozed" }, sort: "priority", offset: 0, limit: 1 }),
        this.hass.callWS({ type: "hamie/explorer/findings", search: "", filters: { lifecycle: "resolved" }, sort: "priority", offset: 0, limit: 1 }),
        this.hass.callWS({ type: "hamie/explorer/overview" })
      ]);
      this._items = result.items;
      this._classificationCounts = result.classification_counts || {};
      this._groupingCounts = result.grouping_counts || {};
      this._total = result.total;
      this._snoozedCount = snoozedTotal.total;
      this._openCount = openTotal.total - snoozedTotal.total;
      this._resolvedCount = resolvedTotal.total;
      this._scanStatus = overview.scan_status;
      this._coverage = overview.coverage;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Findings are temporarily unavailable.");
    }
  }
  _setQuickFilter(id) {
    this._quickFilter = id;
    this._offset = 0;
    this._load();
  }
  _onSearchInput(event) {
    this._search = event.detail.value;
  }
  _onSearchApply() {
    this._offset = 0;
    this._load();
  }
  _updateAdvanced(key, value) {
    this._advanced = { ...this._advanced, [key]: value };
  }
  _applyAdvanced() {
    this._offset = 0;
    this._load();
  }
  _clearAdvanced() {
    this._advanced = {};
    this._sort = "priority";
    this._offset = 0;
    this._load();
  }
  _nextPage() {
    this._offset += PAGE_SIZE;
    this._load();
  }
  _previousPage() {
    this._offset = Math.max(0, this._offset - PAGE_SIZE);
    this._load();
  }
  _clearFocus() {
    this.focusFindingId = null;
    this.focusGroupId = null;
    this.focusGroupTitle = null;
    this._offset = 0;
    this._load();
  }
  _onViewDependencyGraph(findingId, entityId) {
    this._detailItem = null;
    this.dispatchEvent(
      new CustomEvent("hamie-navigate-dependencies", { detail: { findingId, entityId }, bubbles: true, composed: true })
    );
  }
  async _onGroupAction(group_id, action) {
    if (!this.hass) return;
    this._actionError = null;
    this._busy = true;
    try {
      const preview = await this.hass.callWS({ type: "hamie/group/preview", group_id, action });
      if (preview.count === 0) {
        this._actionError = `No eligible findings for "${GROUP_ACTIONS.find((item) => item.id === action)?.label}" in this group.`;
        return;
      }
      this._reason = "";
      this._pending = { group_id, action, preview };
      this._detailItem = null;
    } catch (err) {
      this._actionError = friendlyError(err, "That action could not be started.");
    } finally {
      this._busy = false;
    }
  }
  _cancelPending() {
    this._pending = null;
    this._reason = "";
  }
  async _confirmPending() {
    if (!this.hass || !this._pending) return;
    const { action, preview } = this._pending;
    this._busy = true;
    try {
      if (action === "suppress") {
        await this.hass.callWS({
          type: "hamie/group/suppress",
          preview,
          idempotency_token: idempotencyToken(),
          reason: this._reason.trim()
        });
      } else {
        await this.hass.callWS({ type: "hamie/group/apply", preview, idempotency_token: idempotencyToken() });
      }
      this._pending = null;
      this._reason = "";
      await this._load();
    } catch (err) {
      this._actionError = friendlyError(err, "That action could not be applied.");
    } finally {
      this._busy = false;
    }
  }
  render() {
    if (this._error) {
      return b2`<hamie-empty tone="unavailable" heading="Findings are unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._items) {
      return b2`<hamie-loading .lines=${5}></hamie-loading>`;
    }
    const neverScanned = !this.focusFindingId && !this.focusGroupId && this._scanStatus === "never_run";
    const failedWithNothingRetained = !this.focusFindingId && !this.focusGroupId && this._scanStatus === "failed" && this._coverage === "unknown";
    if (neverScanned || failedWithNothingRetained) {
      return b2`
        <hamie-empty
          tone=${neverScanned ? "neutral" : "unavailable"}
          heading=${neverScanned ? "No scan has completed yet" : "The latest scan failed"}
          description=${neverScanned ? "Run a scan to see findings here." : "No previous results are available yet. Run a scan to try again."}
        ></hamie-empty>
      `;
    }
    return b2`
      <hamie-page-header heading="Findings" subtitle="${this._openCount ?? "\u2014"} open · ${this._snoozedCount ?? "\u2014"} snoozed · ${this._resolvedCount ?? "\u2014"} resolved"></hamie-page-header>

      ${this._actionError ? b2`
            <div class="action-error">
              <span>${this._actionError}</span>
              <hamie-button variant="ghost" size="xs" @click=${() => this._actionError = null}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          ` : null}

      ${this.focusFindingId || this.focusGroupId ? b2`
            <div style="display: flex; align-items: center; justify-content: space-between; gap: var(--hamie-space-3); margin-bottom: var(--hamie-space-3); padding: var(--hamie-space-2-5) var(--hamie-space-3); border-radius: var(--hamie-radius-md); background: var(--hamie-surface-raised)">
              <span style="font-size: var(--hamie-text-micro); color: var(--hamie-text-secondary)">
                ${this.focusGroupId ? `Showing findings in group: ${this.focusGroupTitle || this.focusGroupId}.` : "Showing one finding from Recommendations."}
              </span>
              <hamie-button variant="ghost" size="xs" @click=${this._clearFocus}>Show all findings</hamie-button>
            </div>
          ` : b2`
            <div class="toolbar">
              <hamie-input
                class="search"
                placeholder="Search entities or issues…"
                icon="mdi:magnify"
                .value=${this._search}
                @hamie-input=${this._onSearchInput}
                @keydown=${(event) => event.key === "Enter" && this._onSearchApply()}
              ></hamie-input>
              <div class="filters">
                ${QUICK_FILTERS.map(
      (filter) => b2`
                    <button aria-pressed=${filter.id === this._quickFilter ? "true" : "false"} @click=${() => this._setQuickFilter(filter.id)}>
                      ${filter.label}
                    </button>
                  `
    )}
              </div>
              <hamie-button variant="ghost" size="sm" @click=${() => this._advancedOpen = !this._advancedOpen}>
                <ha-icon icon="mdi:tune-variant"></ha-icon> ${this._advancedOpen ? "Hide filters" : "More filters"}
              </hamie-button>
              <hamie-button variant="ghost" size="sm" @click=${() => this._grouped = !this._grouped}>
                <ha-icon icon=${this._grouped ? "mdi:view-agenda-outline" : "mdi:folder-multiple-outline"}></ha-icon>
                ${this._grouped ? "Flat list" : "Group by system"}
              </hamie-button>
            </div>

            <hamie-disclosure label="Breakdown">
              <p class="summary-line">
                ${Object.entries(this._classificationCounts || {}).map(([label, count]) => `${count} ${label}`).join(" \xB7 ") || "No breakdown available"}
              </p>
              <div style="display:flex; align-items:center; gap: var(--hamie-space-2); margin-bottom: var(--hamie-space-1)">
                <span class="summary-line" style="margin:0">Group by</span>
                <hamie-select
                  .options=${GROUP_BY_OPTIONS}
                  .value=${this._groupBy}
                  @hamie-change=${(event) => this._groupBy = event.detail.value}
                ></hamie-select>
              </div>
              <div class="group-strip" aria-label="Selected grouping summary">
                ${(this._groupingCounts?.[this._groupBy] || []).map(
      (group) => b2`<span class="summary-chip"><strong>${group.count}</strong> ${group.label}</span>`
    )}
              </div>
            </hamie-disclosure>

            ${this._advancedOpen ? b2`
                  <div class="advanced-panel">
                    <div class="field">
                      <label>Sort</label>
                      <hamie-select .options=${SORT_OPTIONS} .value=${this._sort} @hamie-change=${(e6) => this._sort = e6.detail.value}></hamie-select>
                    </div>
                    <div class="field">
                      <label>Severity</label>
                      <hamie-select .options=${withBlank(SEVERITY_OPTIONS)} .value=${this._advanced.severity || ""} @hamie-change=${(e6) => this._updateAdvanced("severity", e6.detail.value)}></hamie-select>
                    </div>
                    <div class="field">
                      <label>Lifecycle</label>
                      <hamie-select .options=${withBlank(LIFECYCLE_OPTIONS)} .value=${this._advanced.lifecycle || ""} @hamie-change=${(e6) => this._updateAdvanced("lifecycle", e6.detail.value)}></hamie-select>
                    </div>
                    <div class="field">
                      <label>Category</label>
                      <hamie-input .value=${this._advanced.category || ""} @hamie-input=${(e6) => this._updateAdvanced("category", e6.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Analyzer ID</label>
                      <hamie-input .value=${this._advanced.analyzer || ""} @hamie-input=${(e6) => this._updateAdvanced("analyzer", e6.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Integration domain</label>
                      <hamie-input .value=${this._advanced.integration || ""} @hamie-input=${(e6) => this._updateAdvanced("integration", e6.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Device ID</label>
                      <hamie-input .value=${this._advanced.device || ""} @hamie-input=${(e6) => this._updateAdvanced("device", e6.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Area ID</label>
                      <hamie-input .value=${this._advanced.area || ""} @hamie-input=${(e6) => this._updateAdvanced("area", e6.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Review state</label>
                      <hamie-select .options=${withBlank(REVIEW_STATE_OPTIONS)} .value=${this._advanced.review_state || ""} @hamie-change=${(e6) => this._updateAdvanced("review_state", e6.detail.value)}></hamie-select>
                    </div>
                    <div class="field">
                      <label>Dependency risk</label>
                      <hamie-select .options=${withBlank(DEPENDENCY_RISK_OPTIONS)} .value=${this._advanced.dependency_risk || ""} @hamie-change=${(e6) => this._updateAdvanced("dependency_risk", e6.detail.value)}></hamie-select>
                    </div>
                    <div class="field">
                      <label>Safe to remove</label>
                      <hamie-select .options=${[{ value: "", label: "Any" }, { value: "true", label: "Safe" }, { value: "false", label: "Not safe" }]} .value=${this._advanced.safe_to_remove || ""} @hamie-change=${(e6) => this._updateAdvanced("safe_to_remove", e6.detail.value)}></hamie-select>
                    </div>
                    <div class="field">
                      <label>AI recommendation state</label>
                      <hamie-select .options=${withBlank(AI_STATE_OPTIONS)} .value=${this._advanced.ai_recommendation_state || ""} @hamie-change=${(e6) => this._updateAdvanced("ai_recommendation_state", e6.detail.value)}></hamie-select>
                    </div>
                    <div class="field">
                      <label>First seen from (aware ISO)</label>
                      <hamie-input .value=${this._advanced.first_seen_from || ""} @hamie-input=${(e6) => this._updateAdvanced("first_seen_from", e6.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>First seen to (aware ISO)</label>
                      <hamie-input .value=${this._advanced.first_seen_to || ""} @hamie-input=${(e6) => this._updateAdvanced("first_seen_to", e6.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Last seen from (aware ISO)</label>
                      <hamie-input .value=${this._advanced.last_seen_from || ""} @hamie-input=${(e6) => this._updateAdvanced("last_seen_from", e6.detail.value)}></hamie-input>
                    </div>
                    <div class="field">
                      <label>Last seen to (aware ISO)</label>
                      <hamie-input .value=${this._advanced.last_seen_to || ""} @hamie-input=${(e6) => this._updateAdvanced("last_seen_to", e6.detail.value)}></hamie-input>
                    </div>
                    <div class="advanced-actions">
                      <hamie-button variant="primary" size="sm" @click=${this._applyAdvanced}>Apply</hamie-button>
                      <hamie-button variant="ghost" size="sm" @click=${this._clearAdvanced}>Clear</hamie-button>
                    </div>
                  </div>
                ` : null}
          `}

      <hamie-card padding="none">
        ${this._items.length === 0 ? b2`
              <hamie-empty
                tone=${this.focusFindingId ? "unavailable" : "positive"}
                heading=${this.focusFindingId ? "That finding isn't in the current page of results" : this.focusGroupId ? "No findings currently belong to this group" : "No findings match this filter"}
                description=${this.focusFindingId ? "It may have been resolved, or it's outside the highest-priority page currently loaded." : ""}
              ></hamie-empty>
            ` : this._grouped && !this.focusFindingId && !this.focusGroupId ? this._renderGroupedList(this._items) : b2`
                <div class="list">
                  ${this._items.map((item) => this._renderRow(item))}
                </div>
              `}
      </hamie-card>
      ${!this.focusFindingId && this._items.length ? b2`
            <div class="pager">
              <hamie-button variant="ghost" size="xs" ?disabled=${this._offset === 0} @click=${this._previousPage}>Previous</hamie-button>
              <span>${this._total === 0 ? 0 : this._offset + 1}–${Math.min(this._offset + PAGE_SIZE, this._total)} of ${this._total}</span>
              <hamie-button variant="ghost" size="xs" ?disabled=${this._offset + PAGE_SIZE >= this._total} @click=${this._nextPage}>Next</hamie-button>
            </div>
          ` : null}

      ${this._detailItem ? this._renderDetailDrawer(this._detailItem) : null}
      ${this._pending ? this._renderConfirmDialog() : null}
    `;
  }
  // Groups the current findings page by real `integration` (falling
  // back to the finding's `category` when `integration` is unset, then
  // "Other"). Every group's own findings are still real
  // `hamie/explorer/findings` rows -- this only changes visual
  // clustering of the already-fetched page, never a second fetch.
  _renderGroupedList(items) {
    const groups = /* @__PURE__ */ new Map();
    for (const item of items) {
      const key = item.integration || item.category || "Other";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    const sorted = [...groups.entries()].sort(([a3], [b3]) => a3.localeCompare(b3));
    return b2`
      ${sorted.map(
      ([name, groupItems]) => b2`
          <div class="group-header">
            <span>${name}</span>
            <span class="group-header-count">${groupItems.length} finding${groupItems.length === 1 ? "" : "s"}</span>
          </div>
          <div class="list">${groupItems.map((item) => this._renderRow(item))}</div>
        `
    )}
    `;
  }
  _renderRow(item) {
    const status = findingStatusToken(item);
    const duration = formatDuration(item.duration_seconds);
    const areaName = resolveAreaName(item.area) || item.area;
    const locationLine = [item.integration, areaName].filter(Boolean).join(" \xB7 ");
    return b2`
      <hamie-issue-row
        interactive
        title=${item.friendly_name || item.entity_id}
        @hamie-row-click=${() => this._detailItem = item}
      >
        ${item.severity === "critical" ? b2`<hamie-status slot="leading" variant="severity" status="critical"></hamie-status>` : null}
        <span slot="extra" class="entity">${item.entity_id}</span>
        <span slot="extra" class="row-status">
          <hamie-status status=${status.status} label=${realFindingStatus(item) === "open" ? duration ? `Unavailable ${duration}` : "Open" : status.label}></hamie-status>
          ${locationLine ? b2`<span style="color: var(--hamie-text-secondary); font-size: var(--hamie-text-micro)">${locationLine}</span>` : null}
        </span>
        <span slot="trailing" style="font-size: var(--hamie-text-micro); color: var(--hamie-text-secondary)">${item.repairability}</span>
        <ha-icon slot="trailing" icon="mdi:chevron-right"></ha-icon>
      </hamie-issue-row>
    `;
  }
  // Detail drawer taxonomy per the Issues spec: Summary / Impact /
  // Evidence / Dependencies / History / Recommendation / Technical
  // Details (collapsed by default). Every field rendered below is the
  // same real `hamie/explorer/findings` per-finding data the drawer
  // already fetched before this pass -- only the section grouping
  // changed; Evidence/History/AI explanations move OUT of the old
  // single "Technical details" catch-all into their own named sections
  // (the spec names them explicitly), and Technical Details keeps only
  // genuinely raw/internal identifiers.
  _renderDetailDrawer(item) {
    const dependency = item.dependency || {};
    return b2`
      <hamie-drawer open heading=${item.friendly_name || item.entity_id} description=${item.entity_id} @hamie-drawer-closed=${() => this._detailItem = null}>
        <div class="drawer-section">
          <h3>Summary</h3>
          <p>${item.recommendation}</p>
          <p class="detail-meta">
            Device: ${item.device || "Unknown"} · Integration: ${item.integration || "Unknown"}<br />
            Classification: ${item.classification} · Repairability: ${item.repairability}
          </p>
        </div>

        <div class="drawer-section">
          <h3>Impact</h3>
          <p>${dependency.rationale || item.recommendation}</p>
          <p class="detail-meta">
            Severity: ${item.severity} · Duration: ${formatDuration(item.duration_seconds) || "Unknown"}<br />
            Occurrences: ${item.occurrence_count ?? "Unknown"} · Dependency risk: ${item.dependency_risk || "Unknown"}
          </p>
        </div>

        <div class="drawer-section">
          <h3>Evidence</h3>
          ${item.evidence?.length ? b2`
                <ul class="detail-list">
                  ${item.evidence.map((e6) => b2`<li>${e6.kind} · ${e6.predicate} = ${e6.value} · ${e6.source} @ ${e6.source_revision}</li>`)}
                </ul>
              ` : b2`<p class="detail-meta">No attributed evidence recorded for this finding.</p>`}
        </div>

        <div class="drawer-section">
          <h3>Dependencies</h3>
          <p>
            ${dependency.coverage === "complete" ? "Checked" : "Check incomplete"} ·
            Referenced by ${dependency.count ?? 0} object${dependency.count === 1 ? "" : "s"}
          </p>
          ${dependency.referenced_by?.length ? b2`<p style="font-size: var(--hamie-text-micro); color: var(--hamie-text-secondary)">${dependency.referenced_by.join(", ")}</p>` : null}
          <div class="drawer-actions">
            <hamie-button variant="secondary" size="sm" @click=${() => this._onViewDependencyGraph(item.finding_id, item.entity_id)}>
              View dependency graph
            </hamie-button>
          </div>
        </div>

        <div class="drawer-section">
          <h3>History</h3>
          ${item.audit_history?.length ? b2`
                <ul class="detail-list">
                  ${item.audit_history.map((e6) => b2`<li>${relativeTime(e6.at)} · ${e6.event} · ${e6.actor}</li>`)}
                </ul>
              ` : b2`<p class="detail-meta">No HAMIE audit history recorded for this finding yet.</p>`}
        </div>

        <div class="drawer-section">
          <h3>Recommendation</h3>
          <p>${item.recommendation}</p>
          ${item.ai_explanations?.length ? b2`
                <p class="detail-meta"><strong>AI advisory explanations</strong></p>
                <ul class="detail-list">
                  ${item.ai_explanations.map((e6) => b2`<li>${e6.summary} · ${e6.stale ? `stale: ${(e6.stale_reasons || []).join(", ")}` : e6.review_state}</li>`)}
                </ul>
              ` : null}
          ${item.group_id ? b2`
                <div class="drawer-actions">
                  ${GROUP_ACTIONS.map(
      (action) => b2`
                      <hamie-button variant="ghost" size="xs" ?disabled=${this._busy} @click=${() => this._onGroupAction(item.group_id, action.id)}>
                        <ha-icon icon=${action.icon}></ha-icon> ${action.label} group
                      </hamie-button>
                    `
    )}
                </div>
              ` : null}
        </div>

        <hamie-disclosure label="Technical details">
          <p class="detail-meta">
            Finding ID: ${item.finding_id}<br />
            Config entry: ${item.config_entry || "unknown"}<br />
            Area: ${item.area || "unknown"}<br />
            Lifecycle: ${item.lifecycle} · Review: ${item.review_state} · Suppression: ${item.suppression_state} · Confidence: ${item.confidence}<br />
            Current state: ${item.current_state}<br />
            First seen: ${relativeTime(item.first_seen)} · Last seen: ${relativeTime(item.last_seen)} · Occurrences: ${item.occurrence_count}<br />
            Dependency safe to remove: ${String(dependency.safe_to_remove)}
          </p>
        </hamie-disclosure>
      </hamie-drawer>
    `;
  }
  _renderConfirmDialog() {
    const action = GROUP_ACTIONS.find((item) => item.id === this._pending.action);
    return b2`
      <hamie-dialog
        open
        heading="${action?.label} group findings?"
        cancel-label="Cancel"
        .confirmLabel=${action?.label || "Confirm"}
        .destructive=${["dismiss", "suppress"].includes(this._pending.action)}
        .busy=${!!this._busy}
        .errorMessage=${this._actionError || ""}
        .confirmDisabled=${this._pending.action === "suppress" && !this._reason?.trim()}
        .onConfirm=${() => this._confirmPending()}
        .onCancel=${() => this._cancelPending()}
      >
        <p>
          ${action?.label} exactly ${this._pending.preview.count} finding${this._pending.preview.count === 1 ? "" : "s"}
          in this finding's group.
          ${this._pending.action === "snooze" ? "They will be snoozed for exactly 24 hours." : ""}
          ${this._pending.action === "suppress" ? "They will be hidden from default views, not deleted." : ""}
          Home Assistant objects will not be changed.
        </p>
        ${this._pending.action === "suppress" ? b2`
              <div class="field">
                <label>Reason (required)</label>
                <hamie-input placeholder="Why is this being suppressed?" .value=${this._reason} @hamie-input=${(e6) => this._reason = e6.detail.value}></hamie-input>
              </div>
            ` : null}
      </hamie-dialog>
    `;
  }
};
if (!customElements.get("hamie-view-findings")) {
  customElements.define("hamie-view-findings", HamieViewFindings);
}

// hamie/frontend/views/hamie-view-incidents.js
var PRIORITY_TONE = {
  p0: "critical",
  p1: "critical",
  p2: "warning",
  p3: "info",
  info: "unknown"
};
var EVIDENCE_LABEL = {
  verified: "Verified",
  strongly_inferred: "Strongly inferred",
  possible: "Possible",
  insufficient_evidence: "Needs evidence",
  not_a_problem: "Not a problem"
};
var HamieViewIncidents = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _result: { state: true },
    _error: { state: true },
    _search: { state: true },
    _busyId: { state: true }
  };
  static styles = i`
    :host { display: block; padding: var(--hamie-space-5); max-width: var(--hamie-content-max-wide); }
    .stack { display: grid; gap: var(--hamie-space-4); }
    .toolbar { display: flex; gap: var(--hamie-space-3); align-items: end; }
    hamie-input { flex: 1; }
    .incident { display: grid; gap: var(--hamie-space-3); }
    .title-row { display: flex; gap: var(--hamie-space-2); align-items: center; flex-wrap: wrap; }
    h3 { margin: 0; font-size: var(--hamie-text-title); }
    .meta { color: var(--hamie-text-secondary); font-size: var(--hamie-text-small); }
    .root { margin: 0; line-height: 1.5; }
    .label { color: var(--hamie-text-secondary); font-size: var(--hamie-text-caption); text-transform: uppercase; letter-spacing: .04em; }
    .actions { display: flex; flex-wrap: wrap; gap: var(--hamie-space-2); }
    .error { color: var(--hamie-status-critical); }
    @media (max-width: 600px) { .toolbar { align-items: stretch; flex-direction: column; } }
  `;
  constructor() {
    super();
    this._result = null;
    this._error = null;
    this._search = "";
    this._busyId = null;
    this._onLiveUpdate = () => this._load();
  }
  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("hamie-live-update", this._onLiveUpdate);
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("hamie-live-update", this._onLiveUpdate);
  }
  updated(changed) {
    if (changed.has("hass") && this.hass) this._load();
  }
  async _load() {
    if (!this.hass) return;
    try {
      this._result = await this.hass.callWS({
        type: "hamie/incidents/list",
        lifecycle: "active",
        search: this._search,
        limit: 100
      });
      this._error = null;
    } catch (error) {
      this._error = friendlyError(error);
    }
  }
  async _setLifecycle(incident, lifecycle) {
    this._busyId = incident.incident_id;
    try {
      await this.hass.callWS({
        type: "hamie/incidents/lifecycle",
        incident_id: incident.incident_id,
        lifecycle,
        expected_revision: incident.content_revision,
        idempotency_token: crypto.randomUUID()
      });
      await this._load();
      this.dispatchEvent(new CustomEvent("hamie-data-changed", { bubbles: true, composed: true }));
    } catch (error) {
      this._error = friendlyError(error);
    } finally {
      this._busyId = null;
    }
  }
  _openFinding(incident) {
    const findingId = incident.finding_ids?.[0];
    if (!findingId) return;
    this.dispatchEvent(new CustomEvent("hamie-navigate-finding", {
      detail: { findingId },
      bubbles: true,
      composed: true
    }));
  }
  render() {
    const items = this._result?.items || [];
    return b2`
      <div class="stack">
        <hamie-page-header
          heading="Incidents"
          subtitle="Root-cause engineering problems, reduced from raw findings by deterministic evidence."
        ></hamie-page-header>
        <div class="toolbar">
          <hamie-input
            placeholder="Search incidents"
            .value=${this._search}
            @hamie-input=${(event) => {
      this._search = event.detail.value;
    }}
          ></hamie-input>
          <hamie-button variant="secondary" @click=${this._load}>Search</hamie-button>
        </div>
        ${this._error ? b2`<p class="error">${this._error}</p>` : null}
        ${!this._result ? b2`<hamie-loading label="Loading incidents"></hamie-loading>` : items.length === 0 ? b2`<hamie-empty heading="No active incidents" description="Run a scan to refresh deterministic evidence."></hamie-empty>` : items.map((incident) => b2`
                <hamie-card padding="md">
                  <article class="incident">
                    <div class="title-row">
                      <hamie-status status=${PRIORITY_TONE[incident.priority] || "unknown"} label=${incident.priority.toUpperCase()}></hamie-status>
                      <h3>${incident.title}</h3>
                    </div>
                    <div class="meta">
                      ${EVIDENCE_LABEL[incident.evidence_status] || incident.evidence_status}
                      · ${Math.round(incident.confidence * 100)}% confidence
                      · ${incident.affected_subject_count} affected object${incident.affected_subject_count === 1 ? "" : "s"}
                      · ${incident.lifecycle}
                    </div>
                    <div>
                      <div class="label">Root cause</div>
                      <p class="root">${incident.root_cause}</p>
                    </div>
                    <div>
                      <div class="label">Evidence</div>
                      <p class="root">${incident.hypotheses?.[0]?.rationale || "No supporting rationale captured."}</p>
                    </div>
                    <div>
                      <div class="label">Affected systems</div>
                      <p class="root">${incident.affected_systems?.length ? incident.affected_systems.join(", ") : "No system mapping captured."}</p>
                    </div>
                    <div>
                      <div class="label">Recommended next step</div>
                      <p class="root">${incident.recommended_next_step}</p>
                    </div>
                    <div class="actions">
                      <hamie-button size="sm" variant="secondary" ?disabled=${this._busyId === incident.incident_id} @click=${() => this._setLifecycle(incident, "investigating")}>Investigate deeper</hamie-button>
                      <hamie-button size="sm" variant="secondary" ?disabled=${this._busyId === incident.incident_id} @click=${() => this._setLifecycle(incident, "confirmed")}>Confirm root cause</hamie-button>
                      <hamie-button size="sm" variant="ghost" @click=${() => this._openFinding(incident)}>View raw evidence</hamie-button>
                      <hamie-button size="sm" variant="ghost" ?disabled=${this._busyId === incident.incident_id} @click=${() => this._setLifecycle(incident, "ignored")}>Ignore</hamie-button>
                      <hamie-button size="sm" variant="ghost" ?disabled=${this._busyId === incident.incident_id} @click=${() => this._setLifecycle(incident, "dismissed")}>Dismiss</hamie-button>
                    </div>
                  </article>
                </hamie-card>
              `)}
      </div>
    `;
  }
};
if (!customElements.get("hamie-view-incidents")) {
  customElements.define("hamie-view-incidents", HamieViewIncidents);
}

// hamie/frontend/components/hamie-entity-identity.js
var DOMAIN_ICON = {
  automation: "mdi:robot-outline",
  script: "mdi:script-text-outline",
  scene: "mdi:palette-outline",
  sensor: "mdi:eye-outline",
  binary_sensor: "mdi:toggle-switch-outline",
  light: "mdi:lightbulb-outline",
  switch: "mdi:toggle-switch-off-outline",
  climate: "mdi:thermostat",
  camera: "mdi:cctv",
  cover: "mdi:blinds-horizontal",
  lock: "mdi:lock-outline",
  media_player: "mdi:cast",
  device_tracker: "mdi:map-marker-outline"
};
function domainOf(entityId) {
  if (!entityId || typeof entityId !== "string") return null;
  const dot = entityId.indexOf(".");
  return dot > 0 ? entityId.slice(0, dot) : null;
}
var HamieEntityIdentity = class extends i4 {
  static properties = {
    name: { type: String },
    entityId: { type: String, attribute: "entity-id" },
    integration: { type: String },
    icon: { type: String },
    // explicit mdi:* override; otherwise derived from entityId's domain
    compact: { type: Boolean, reflect: true }
  };
  static styles = i`
    :host {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2-5);
      min-width: 0;
    }
    .icon-badge {
      flex-shrink: 0;
      width: 28px;
      height: 28px;
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-surface-raised);
      display: flex;
      align-items: center;
      justify-content: center;
    }
    :host([compact]) .icon-badge {
      width: 22px;
      height: 22px;
    }
    .icon-badge ha-icon {
      --mdc-icon-size: 14px;
      color: var(--hamie-text-secondary);
    }
    .text {
      min-width: 0;
    }
    .name {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .meta {
      margin: 1px 0 0;
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      overflow: hidden;
    }
    .entity-id {
      font-family: var(--hamie-font-code);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .badge {
      flex-shrink: 0;
      padding: 0 var(--hamie-space-1-5);
      border-radius: var(--hamie-radius-sm);
      background: var(--hamie-surface-raised);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      font-size: var(--hamie-text-caption);
    }
  `;
  render() {
    const domain = domainOf(this.entityId);
    const icon = this.icon || DOMAIN_ICON[domain] || "mdi:help-box-outline";
    return b2`
      <span class="icon-badge"><ha-icon icon=${icon}></ha-icon></span>
      <span class="text">
        <p class="name">${this.name || this.entityId || "Unknown"}</p>
        <span class="meta">
          ${this.entityId ? b2`<span class="entity-id">${this.entityId}</span>` : null}
          ${this.integration ? b2`<span class="badge">${this.integration}</span>` : null}
        </span>
      </span>
    `;
  }
};
if (!customElements.get("hamie-entity-identity")) {
  customElements.define("hamie-entity-identity", HamieEntityIdentity);
}

// hamie/frontend/components/hamie-confidence-indicator.js
var LEVEL_TONE = { high: "healthy", medium: "warning", low: "critical" };
var LEVEL_LABEL = { high: "High confidence", medium: "Medium confidence", low: "Low confidence" };
var EFFECT_ICON = { supports: "mdi:plus-circle-outline", weakens: "mdi:minus-circle-outline" };
var HamieConfidenceIndicator = class extends i4 {
  static properties = {
    level: { type: String },
    // "high" | "medium" | "low" | unset
    factors: { type: Array }
    // optional [{ code, effect, rationale }]
  };
  static styles = i`
    :host {
      display: block;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      padding: var(--hamie-space-half) var(--hamie-space-2);
      border-radius: var(--hamie-radius-pill);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
    }
    .dot {
      width: 6px;
      height: 6px;
      border-radius: var(--hamie-radius-circle);
      flex-shrink: 0;
    }
    ul {
      margin: var(--hamie-space-1-5) 0 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
    ha-icon {
      --mdc-icon-size: 12px;
      vertical-align: -1px;
    }
  `;
  render() {
    const level = this.level || "unknown";
    const tone = LEVEL_TONE[level] || "unknown";
    const label = LEVEL_LABEL[level] || "Confidence unknown";
    return b2`
      <span class="pill" style="background: var(--hamie-status-${tone}-fill); color: var(--hamie-status-${tone})">
        <span class="dot" style="background: var(--hamie-status-${tone})"></span>
        ${label}
      </span>
      ${this.factors?.length ? b2`
            <ul>
              ${this.factors.map(
      (item) => b2`
                  <li>
                    <ha-icon icon=${EFFECT_ICON[item.effect] || "mdi:circle-small"}></ha-icon>
                    ${item.rationale || item.code}
                  </li>
                `
    )}
            </ul>
          ` : null}
    `;
  }
};
if (!customElements.get("hamie-confidence-indicator")) {
  customElements.define("hamie-confidence-indicator", HamieConfidenceIndicator);
}

// hamie/frontend/components/hamie-evidence-panel.js
var HamieEvidencePanel = class extends i4 {
  static properties = {
    for: { type: Array },
    against: { type: Array }
  };
  static styles = i`
    :host {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: var(--hamie-space-4);
    }
    @media (max-width: 600px) {
      :host {
        grid-template-columns: 1fr;
      }
    }
    .column h4 {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      margin: 0 0 var(--hamie-space-1-5);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
    }
    .column.for h4 {
      color: var(--hamie-status-healthy);
    }
    .column.against h4 {
      color: var(--hamie-status-warning);
    }
    ha-icon {
      --mdc-icon-size: 14px;
    }
    ul {
      margin: 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
      line-height: 1.6;
    }
    .empty {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      font-style: italic;
    }
  `;
  _column(tone, heading, icon, items) {
    return b2`
      <div class="column ${tone}">
        <h4><ha-icon icon=${icon}></ha-icon> ${heading}</h4>
        ${items?.length ? b2`<ul>${items.map((item) => b2`<li>${item}</li>`)}</ul>` : b2`<p class="empty">None recorded</p>`}
      </div>
    `;
  }
  render() {
    return b2`
      ${this._column("for", "Evidence for", "mdi:check-circle-outline", this.for)}
      ${this._column("against", "Evidence against", "mdi:alert-circle-outline", this.against)}
    `;
  }
};
if (!customElements.get("hamie-evidence-panel")) {
  customElements.define("hamie-evidence-panel", HamieEvidencePanel);
}

// hamie/frontend/components/hamie-review-item.js
var RISK_TONE = { low: "healthy", medium: "warning", high: "critical", unknown: "unknown" };
var HamieReviewItem = class extends i4 {
  static properties = {
    name: { type: String },
    entityId: { type: String, attribute: "entity-id" },
    integration: { type: String },
    recommendation: { type: String },
    confidenceLevel: { type: String, attribute: "confidence-level" },
    confidenceFactors: { type: Array, attribute: false },
    risk: { type: String },
    // "low" | "medium" | "high" | "unknown"
    evidenceFor: { type: Array, attribute: false },
    evidenceAgainst: { type: Array, attribute: false },
    externalConsumerNote: { type: String, attribute: "external-consumer-note" }
  };
  static styles = i`
    :host {
      display: block;
    }
    .head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-3);
    }
    .badges {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
    }
    .recommendation {
      margin: 0 0 var(--hamie-space-3);
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
      line-height: 1.6;
    }
    .risk-pill {
      display: inline-flex;
      align-items: center;
      padding: var(--hamie-space-half) var(--hamie-space-2);
      border-radius: var(--hamie-radius-sm);
      font-size: var(--hamie-text-caption);
      font-weight: var(--hamie-weight-bold);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
    }
    .external-note {
      margin: var(--hamie-space-3) 0 0;
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-evidence-fill);
      color: var(--hamie-text-primary);
      font-size: var(--hamie-text-micro);
      display: flex;
      align-items: flex-start;
      gap: var(--hamie-space-2);
    }
    .external-note ha-icon {
      --mdc-icon-size: 14px;
      color: var(--hamie-status-evidence);
      flex-shrink: 0;
      margin-top: 1px;
    }
    .actions {
      display: flex;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-3);
    }
  `;
  render() {
    const risk = this.risk || "unknown";
    const riskTone = RISK_TONE[risk] || "unknown";
    return b2`
      <hamie-card padding="md">
        <div class="head">
          <hamie-entity-identity name=${this.name || ""} entity-id=${this.entityId || ""} integration=${this.integration || ""}></hamie-entity-identity>
          <span class="badges">
            <span class="risk-pill" style="background: var(--hamie-status-${riskTone}-fill); color: var(--hamie-status-${riskTone})">
              Risk: ${risk}
            </span>
          </span>
        </div>

        ${this.recommendation ? b2`<p class="recommendation">${this.recommendation}</p>` : null}

        <hamie-confidence-indicator level=${this.confidenceLevel || ""} .factors=${this.confidenceFactors || []}></hamie-confidence-indicator>

        <hamie-disclosure label="Evidence">
          <hamie-evidence-panel .for=${this.evidenceFor || []} .against=${this.evidenceAgainst || []}></hamie-evidence-panel>
        </hamie-disclosure>

        ${this.externalConsumerNote ? b2`
              <p class="external-note">
                <ha-icon icon="mdi:account-question-outline"></ha-icon>
                ${this.externalConsumerNote}
              </p>
            ` : null}

        <div class="actions"><slot name="actions"></slot></div>
      </hamie-card>
    `;
  }
};
if (!customElements.get("hamie-review-item")) {
  customElements.define("hamie-review-item", HamieReviewItem);
}

// hamie/frontend/views/hamie-view-review.js
var RISK_TONE_MAP = { low: "low", medium: "medium", high: "high", critical: "high" };
var CATEGORIES = [
  {
    id: "confirmed_orphans",
    label: "Confirmed Orphans",
    icon: "mdi:file-question-outline",
    description: "Entities with no known references and a complete dependency scan.",
    source: "live_findings",
    filters: { classification: "Persistently unavailable", repairability: "Potentially safe to disable", lifecycle: "open" },
    recommendation: "No local Home Assistant object references this entity and its dependency scan is complete. Consider disabling it."
  },
  {
    id: "unavailable_but_used",
    label: "Unavailable But Used",
    icon: "mdi:link-variant-off",
    description: "Unavailable, but at least one automation, script, or dashboard still references it.",
    source: "live_findings",
    filters: { classification: "Referenced entity", lifecycle: "open" },
    recommendation: "This entity is currently unavailable but is still referenced elsewhere. Repair the source, do not disable it."
  },
  {
    id: "duplicate_migration",
    label: "Duplicate / Migration",
    icon: "mdi:content-duplicate",
    description: "Suffix-duplicate entities (e.g. foo / foo_2) from a device re-pair or a partial rename, or a case no single rule could classify confidently.",
    source: "live_findings",
    // Two server-side queries merged: LIKELY_MIGRATION_LEFTOVER /
    // ACTIVE_OLD_ID_WITH_NEW_SIBLING (recommendation_kind
    // "investigate") and AMBIGUOUS_DUPLICATE_GROUP
    // (recommendation_kind "review_duplicate"). Excludes
    // LIKELY_DISTINCT_ENTITIES ("no_action" -- cleared, not a pending
    // decision) and BROKEN_REFERENCE_TO_OLD_SIBLING ("repair" -- its
    // own tab below).
    filtersList: [
      { category: "duplicate_migration", recommendation_kind: "investigate" },
      { category: "duplicate_migration", recommendation_kind: "review_duplicate" }
    ],
    recommendation: "A suffix-duplicate group needs a human look. Confirm which member is genuinely still in use before disabling any sibling."
  },
  {
    id: "insufficient_evidence",
    label: "Insufficient Evidence",
    icon: "mdi:magnify-scan",
    description: "HAMIE could not fully verify these are safe to touch.",
    source: "live_findings",
    filters: { repairability: "Needs more evidence", lifecycle: "open" },
    recommendation: "The dependency scan for this entity is incomplete. Gather more evidence before deciding."
  },
  {
    id: "protected_dormant",
    label: "Protected Dormant",
    icon: "mdi:shield-check-outline",
    description: "Inactive, but a real dependency was found -- protected from cleanup.",
    source: "maintenance_work_items",
    lifecycleState: "dependency_blocked",
    recommendation: "A real local dependency was found for this group. Keep it; do not disable or remove."
  },
  {
    id: "broken_reference",
    label: "Broken Reference",
    icon: "mdi:link-off",
    description: "An automation, script, or dashboard points at an old entity id that no longer resolves.",
    source: "live_findings",
    filters: { category: "duplicate_migration", recommendation_kind: "repair" },
    recommendation: "A disabled or unavailable entity still has a live reference pointing at it. Update the referencing automation, script, or dashboard to point at the active sibling."
  }
];
function evidenceForAgainst(category, item) {
  const dependency = item.dependency || {};
  const evidenceFor = [];
  const evidenceAgainst = [];
  if (category.id === "confirmed_orphans") {
    evidenceFor.push("Dependency scan complete: no references found");
    evidenceFor.push(`Repairability: ${item.repairability}`);
    if (item.first_seen) evidenceFor.push(`Persistently unavailable since ${relativeTime(item.first_seen)}`);
  } else if (category.id === "unavailable_but_used") {
    evidenceFor.push(`Referenced by ${dependency.count ?? "at least one"} object${dependency.count === 1 ? "" : "s"}`);
    if (dependency.referenced_by?.length) evidenceFor.push(`Referencing objects: ${dependency.referenced_by.join(", ")}`);
  } else if (category.id === "insufficient_evidence") {
    evidenceAgainst.push("Dependency scan is incomplete for this entity");
    if (dependency.unresolved_references?.length) {
      evidenceAgainst.push(`Unresolved references: ${dependency.unresolved_references.join(", ")}`);
    }
  } else if (category.id === "protected_dormant") {
    evidenceFor.push("Currently inactive/unavailable");
    evidenceAgainst.push(item.reason || "A real local dependency was found for this group");
  } else if (category.id === "duplicate_migration") {
    evidenceFor.push(item.recommended_next_action || item.recommendation);
    if (item.recommendation_kind === "review_duplicate") {
      evidenceAgainst.push("No single classification rule matched confidently -- confirm by hand.");
    }
  } else if (category.id === "broken_reference") {
    evidenceAgainst.push(item.recommended_next_action || item.recommendation);
  }
  if (category.id !== "insufficient_evidence") {
    if (dependency.coverage && dependency.coverage !== "complete") {
      evidenceAgainst.push("Dependency scan coverage is incomplete");
    }
    if (item.confidence && item.confidence !== "high") {
      evidenceAgainst.push(`Confidence is ${item.confidence}, not high -- verify manually`);
    }
  }
  return { evidenceFor, evidenceAgainst };
}
function externalConsumerNote(item) {
  const dependency = item.dependency || {};
  if (dependency.coverage && dependency.coverage !== "complete") {
    return "Dependency scan incomplete -- external consumers (dashboards, scripts, or connectors HAMIE could not reach) cannot be fully ruled out.";
  }
  if ((dependency.count ?? 0) > 0) {
    return `Referenced by ${dependency.count} known object(s) inside this Home Assistant installation. HAMIE cannot see dashboards or automations outside this installation (e.g. a separate remote instance).`;
  }
  return null;
}
var HamieViewReview = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _activeId: { state: true },
    _data: { state: true },
    // { [categoryId]: items[] | null }
    _error: { state: true }
  };
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: var(--hamie-space-2);
      margin-bottom: var(--hamie-space-4);
    }
    .tab {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      padding: var(--hamie-space-1-5) var(--hamie-space-3);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-pill);
      background: var(--hamie-surface-raised);
      color: var(--hamie-text-secondary);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      cursor: pointer;
      font-family: inherit;
    }
    .tab[aria-pressed="true"] {
      background: var(--hamie-accent-fill-loud);
      color: var(--hamie-accent-on);
      border-color: transparent;
    }
    .tab .count {
      opacity: 0.85;
    }
    ha-icon {
      --mdc-icon-size: 14px;
    }
    .category-description {
      margin: 0 0 var(--hamie-space-4);
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
    }
    .list {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
    }
    .pending-banner {
      display: flex;
      align-items: flex-start;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-4);
      border-radius: var(--hamie-radius-lg);
      border: 1px dashed var(--hamie-border-normal);
      background: var(--hamie-surface-raised);
      color: var(--hamie-text-secondary);
      font-size: var(--hamie-text-small);
      line-height: 1.6;
    }
    .pending-banner ha-icon {
      --mdc-icon-size: 20px;
      color: var(--hamie-status-evidence);
      flex-shrink: 0;
    }
  `;
  constructor() {
    super();
    this._activeId = CATEGORIES[0].id;
    this._data = {};
  }
  connectedCallback() {
    super.connectedCallback();
    this._loadAll();
    this._onLiveUpdate = () => this._loadAll();
    window.addEventListener("hamie-live-update", this._onLiveUpdate);
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("hamie-live-update", this._onLiveUpdate);
  }
  async _loadAll() {
    if (!this.hass) return;
    try {
      const liveCategories = CATEGORIES.filter((cat) => cat.source === "live_findings");
      const queries = liveCategories.map((cat) => cat.filtersList || [cat.filters]);
      const flatQueries = queries.flat();
      const [findingsResults, queue] = await Promise.all([
        Promise.all(
          flatQueries.map(
            (filters) => this.hass.callWS({
              type: "hamie/explorer/findings",
              search: "",
              filters,
              sort: "priority",
              offset: 0,
              limit: 25
            })
          )
        ),
        this.hass.callWS({ type: "hamie/remediation/queue/list", offset: 0, limit: 1 })
      ]);
      const data = {};
      let index = 0;
      for (const cat of CATEGORIES) {
        if (cat.source === "live_findings") {
          const count = (cat.filtersList || [cat.filters]).length;
          const merged = findingsResults.slice(index, index + count).flatMap((r6) => r6.items);
          index += count;
          const seen = /* @__PURE__ */ new Set();
          data[cat.id] = merged.filter((item) => {
            if (seen.has(item.finding_id)) return false;
            seen.add(item.finding_id);
            return true;
          });
        } else if (cat.source === "maintenance_work_items") {
          data[cat.id] = (queue.maintenance_work_items || []).filter(
            (item) => item.lifecycle_state === cat.lifecycleState
          );
        } else {
          data[cat.id] = [];
        }
      }
      this._data = data;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Review data is temporarily unavailable.");
    }
  }
  _onViewFinding(findingId) {
    this.dispatchEvent(new CustomEvent("hamie-navigate-finding", { detail: { findingId }, bubbles: true, composed: true }));
  }
  _onOpenReviewQueue() {
    this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "remediation" }, bubbles: true, composed: true }));
  }
  _renderFindingItem(category, item) {
    const { evidenceFor, evidenceAgainst } = evidenceForAgainst(category, item);
    return b2`
      <hamie-review-item
        name=${item.friendly_name || item.entity_id}
        entity-id=${item.entity_id}
        integration=${item.integration || ""}
        recommendation=${category.recommendation}
        confidence-level=${item.confidence || ""}
        risk=${RISK_TONE_MAP[item.dependency_risk] || "unknown"}
        .evidenceFor=${evidenceFor}
        .evidenceAgainst=${evidenceAgainst}
        external-consumer-note=${externalConsumerNote(item) || ""}
      >
        <hamie-button slot="actions" variant="secondary" size="xs" @click=${() => this._onViewFinding(item.finding_id)}>
          View in Issues
        </hamie-button>
      </hamie-review-item>
    `;
  }
  _renderWorkItem(category, item) {
    const evidenceFor = ["Currently inactive/unavailable"];
    const evidenceAgainst = [item.reason];
    if (item.missing_evidence?.length) evidenceAgainst.push(`Missing evidence: ${item.missing_evidence.join(", ")}`);
    return b2`
      <hamie-review-item
        name=${item.title}
        entity-id=${(item.affected_entity_ids || [])[0] || ""}
        integration=""
        recommendation=${category.recommendation}
        confidence-level=${item.confidence || ""}
        risk=${RISK_TONE_MAP[item.risk] || "unknown"}
        .evidenceFor=${evidenceFor}
        .evidenceAgainst=${evidenceAgainst}
        external-consumer-note=${item.entity_count > 1 ? `Affects ${item.entity_count} entities.` : ""}
      >
        <hamie-button slot="actions" variant="secondary" size="xs" @click=${() => this._onOpenReviewQueue()}>
          Open in Review Queue
        </hamie-button>
      </hamie-review-item>
    `;
  }
  render() {
    if (this._error) {
      return b2`<hamie-empty tone="unavailable" heading="Review is unavailable" description=${this._error}></hamie-empty>`;
    }
    const loaded = Object.keys(this._data).length === CATEGORIES.length;
    if (!loaded) {
      return b2`<hamie-loading .lines=${5}></hamie-loading>`;
    }
    const active = CATEGORIES.find((cat) => cat.id === this._activeId);
    const items = this._data[active.id] || [];
    return b2`
      <hamie-page-header heading="Review" subtitle="Human-judgment triage, separate from Issues -- recommendations only, no destructive actions."></hamie-page-header>

      <div class="tabs" role="tablist">
        ${CATEGORIES.map(
      (cat) => b2`
            <button
              type="button"
              class="tab"
              role="tab"
              aria-pressed=${cat.id === this._activeId ? "true" : "false"}
              @click=${() => this._activeId = cat.id}
            >
              <ha-icon icon=${cat.icon}></ha-icon>
              ${cat.label}
              <span class="count">${cat.source === "pending" ? "\u2014" : (this._data[cat.id] || []).length}</span>
            </button>
          `
    )}
      </div>

      <p class="category-description">${active.description}</p>

      ${active.source === "pending" ? b2`
            <div class="pending-banner">
              <ha-icon icon="mdi:progress-clock"></ha-icon>
              <span>
                <strong>Pending activation.</strong> ${active.pendingReason}
                This category is deliberately shown as empty rather than approximated, so it is never mistaken for "HAMIE checked and found none."
              </span>
            </div>
          ` : items.length === 0 ? b2`<hamie-empty tone="positive" heading="Nothing in this category right now"></hamie-empty>` : b2`
              <div class="list">
                ${items.map(
      (item) => active.source === "maintenance_work_items" ? this._renderWorkItem(active, item) : this._renderFindingItem(active, item)
    )}
              </div>
            `}
    `;
  }
};
if (!customElements.get("hamie-view-review")) {
  customElements.define("hamie-view-review", HamieViewReview);
}

// hamie/frontend/views/hamie-view-search.js
var KINDS = [
  { id: "all", label: "All" },
  { id: "entities", label: "Entities & Issues" },
  { id: "groups", label: "Groups" },
  { id: "devices", label: "Devices" },
  { id: "areas", label: "Areas" },
  { id: "integrations", label: "Integrations" }
];
var RESULT_LIMIT = 20;
var HamieViewSearch = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _query: { state: true },
    _kind: { state: true },
    _results: { state: true },
    // { entities: [], groups: [], devices: [], areas: [], integrations: [] } | null
    _searching: { state: true },
    _error: { state: true },
    _registryReady: { state: true }
  };
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .toolbar {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-4);
    }
    .search-input {
      max-width: 480px;
    }
    .kinds {
      display: flex;
      flex-wrap: wrap;
      gap: 2px;
      padding: var(--hamie-space-1);
      background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-md);
      width: fit-content;
    }
    .kinds button {
      padding: var(--hamie-space-1) var(--hamie-space-2-5);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      border-radius: var(--hamie-radius-sm);
      border: none;
      background: transparent;
      color: var(--hamie-text-secondary);
      cursor: pointer;
      font-family: inherit;
    }
    .kinds button[aria-pressed="true"] {
      background: var(--hamie-accent-fill-loud);
      color: var(--hamie-accent-on);
    }
    .group {
      margin-bottom: var(--hamie-space-5);
    }
    .group h2 {
      margin: 0 0 var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-text-secondary);
    }
    .list {
      display: flex;
      flex-direction: column;
    }
    .list > * + * {
      border-top: 1px solid var(--hamie-border-hairline);
    }
    .entity-id {
      font-family: var(--hamie-font-code);
      font-size: var(--hamie-text-caption);
      color: var(--hamie-text-secondary);
    }
  `;
  constructor() {
    super();
    this._query = "";
    this._kind = "all";
    this._results = null;
  }
  connectedCallback() {
    super.connectedCallback();
    primeHaRegistry(this.hass).then(() => this._registryReady = true);
  }
  _onInput(event) {
    this._query = event.detail.value;
  }
  async _onSearch() {
    if (!this.hass) return;
    const query = this._query.trim();
    if (!query) {
      this._results = null;
      return;
    }
    this._searching = true;
    this._error = null;
    try {
      const wantEntities = this._kind === "all" || this._kind === "entities";
      const wantGroups = this._kind === "all" || this._kind === "groups";
      const [findings, groups] = await Promise.all([
        wantEntities ? this.hass.callWS({ type: "hamie/explorer/findings", search: query, filters: {}, sort: "priority", offset: 0, limit: RESULT_LIMIT }) : Promise.resolve({ items: [] }),
        wantGroups ? this.hass.callWS({ type: "hamie/explorer/groups", search: query, offset: 0, limit: RESULT_LIMIT }) : Promise.resolve({ items: [] })
      ]);
      const lowered = query.toLowerCase();
      const wantDevices = this._kind === "all" || this._kind === "devices";
      const wantAreas = this._kind === "all" || this._kind === "areas";
      const wantIntegrations = this._kind === "all" || this._kind === "integrations";
      this._results = {
        entities: findings.items,
        groups: groups.items,
        devices: wantDevices ? listDevices().filter((item) => (item.name_by_user || item.name || "").toLowerCase().includes(lowered)).slice(0, RESULT_LIMIT) : [],
        areas: wantAreas ? listAreas().filter((item) => (item.name || "").toLowerCase().includes(lowered)).slice(0, RESULT_LIMIT) : [],
        integrations: wantIntegrations ? listConfigEntries().filter((item) => (item.title || item.domain || "").toLowerCase().includes(lowered)).slice(0, RESULT_LIMIT) : []
      };
    } catch (err) {
      this._error = friendlyError(err, "Search is temporarily unavailable.");
    } finally {
      this._searching = false;
    }
  }
  _onViewFinding(findingId) {
    this.dispatchEvent(new CustomEvent("hamie-navigate-finding", { detail: { findingId }, bubbles: true, composed: true }));
  }
  _onViewGroup(groupId, groupTitle) {
    this.dispatchEvent(
      new CustomEvent("hamie-navigate-findings-group", { detail: { groupId, groupTitle }, bubbles: true, composed: true })
    );
  }
  _hasAnyResults() {
    const r6 = this._results;
    return r6 && (r6.entities.length || r6.groups.length || r6.devices.length || r6.areas.length || r6.integrations.length);
  }
  render() {
    return b2`
      <hamie-page-header heading="Search" subtitle="Find entities, issues, groups, devices, areas, and integrations."></hamie-page-header>

      <div class="toolbar">
        <hamie-input
          class="search-input"
          icon="mdi:magnify"
          placeholder="Search HAMIE and Home Assistant…"
          .value=${this._query}
          @hamie-input=${this._onInput}
          @keydown=${(event) => event.key === "Enter" && this._onSearch()}
        ></hamie-input>
        <div class="kinds" role="tablist">
          ${KINDS.map(
      (kind) => b2`
              <button
                type="button"
                role="tab"
                aria-pressed=${kind.id === this._kind ? "true" : "false"}
                @click=${() => {
        this._kind = kind.id;
        if (this._query.trim()) this._onSearch();
      }}
              >
                ${kind.label}
              </button>
            `
    )}
          <hamie-button variant="primary" size="sm" ?disabled=${this._searching} @click=${this._onSearch}>
            ${this._searching ? "Searching\u2026" : "Search"}
          </hamie-button>
        </div>
      </div>

      ${this._error ? b2`<hamie-empty tone="unavailable" heading="Search is unavailable" description=${this._error}></hamie-empty>` : null}

      ${!this._error && this._results === null ? b2`<hamie-empty tone="neutral" heading="Search for anything in your home" description="Entities, findings, groups, devices, areas, or integrations."></hamie-empty>` : null}

      ${this._searching ? b2`<hamie-loading .lines=${4}></hamie-loading>` : null}

      ${!this._error && !this._searching && this._results !== null ? this._hasAnyResults() ? b2`
              ${this._results.entities.length ? b2`
                    <div class="group">
                      <h2>Entities &amp; Issues (${this._results.entities.length})</h2>
                      <hamie-card padding="none">
                        <div class="list">
                          ${this._results.entities.map(
      (item) => b2`
                              <hamie-issue-row interactive title=${item.friendly_name || item.entity_id} @hamie-row-click=${() => this._onViewFinding(item.finding_id)}>
                                <span slot="extra" class="entity-id">${item.entity_id}</span>
                                <hamie-status slot="trailing" status=${item.severity} variant="severity"></hamie-status>
                                <ha-icon slot="trailing" icon="mdi:chevron-right"></ha-icon>
                              </hamie-issue-row>
                            `
    )}
                        </div>
                      </hamie-card>
                    </div>
                  ` : null}
              ${this._results.groups.length ? b2`
                    <div class="group">
                      <h2>Groups (${this._results.groups.length})</h2>
                      <hamie-card padding="none">
                        <div class="list">
                          ${this._results.groups.map(
      (item) => b2`
                              <hamie-issue-row
                                interactive
                                title=${item.title}
                                meta="${item.member_count} member${item.member_count === 1 ? "" : "s"}"
                                @hamie-row-click=${() => this._onViewGroup(item.group_id, item.title)}
                              >
                                <hamie-status slot="trailing" status=${item.critical_count > 0 ? "critical" : item.warning_count > 0 ? "warning" : "info"} label="Priority ${item.priority}"></hamie-status>
                                <ha-icon slot="trailing" icon="mdi:chevron-right"></ha-icon>
                              </hamie-issue-row>
                            `
    )}
                        </div>
                      </hamie-card>
                    </div>
                  ` : null}
              ${this._results.devices.length ? b2`
                    <div class="group">
                      <h2>Devices (${this._results.devices.length})</h2>
                      <hamie-card padding="none">
                        <div class="list">
                          ${this._results.devices.map(
      (item) => b2`
                              <hamie-issue-row title=${item.name_by_user || item.name || item.id} meta=${resolveAreaName(item.area_id) || "No area"}>
                                <ha-icon slot="leading" icon="mdi:chip"></ha-icon>
                              </hamie-issue-row>
                            `
    )}
                        </div>
                      </hamie-card>
                    </div>
                  ` : null}
              ${this._results.areas.length ? b2`
                    <div class="group">
                      <h2>Areas (${this._results.areas.length})</h2>
                      <hamie-card padding="none">
                        <div class="list">
                          ${this._results.areas.map(
      (item) => b2`
                              <hamie-issue-row title=${item.name}>
                                <ha-icon slot="leading" icon="mdi:floor-plan"></ha-icon>
                              </hamie-issue-row>
                            `
    )}
                        </div>
                      </hamie-card>
                    </div>
                  ` : null}
              ${this._results.integrations.length ? b2`
                    <div class="group">
                      <h2>Integrations (${this._results.integrations.length})</h2>
                      <hamie-card padding="none">
                        <div class="list">
                          ${this._results.integrations.map(
      (item) => b2`
                              <hamie-issue-row title=${item.title || item.domain} meta=${item.domain}>
                                <ha-icon slot="leading" icon="mdi:puzzle-outline"></ha-icon>
                              </hamie-issue-row>
                            `
    )}
                        </div>
                      </hamie-card>
                    </div>
                  ` : null}
            ` : b2`<hamie-empty tone="neutral" heading="No results for &ldquo;${this._query}&rdquo;"></hamie-empty>` : null}
    `;
  }
};
if (!customElements.get("hamie-view-search")) {
  customElements.define("hamie-view-search", HamieViewSearch);
}

// hamie/frontend/components/hamie-problem-card.js
var HamieProblemCard = class extends i4 {
  static properties = {
    priority: { type: String },
    // "high" | "medium" | "low" | unset (badge omitted)
    heading: { type: String },
    body: { type: String },
    actionLabel: { type: String },
    category: { type: String },
    dismissible: { type: Boolean }
  };
  static styles = i`
    :host {
      display: block;
    }
    .row {
      display: flex;
      align-items: flex-start;
      gap: var(--hamie-space-3);
    }
    hamie-status[variant="priority"] {
      margin-top: 2px;
      flex-shrink: 0;
    }
    .body {
      flex: 1;
      min-width: 0;
    }
    .title {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .text {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-3);
    }
    .category {
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-secondary);
      background: var(--hamie-surface-raised);
      padding: var(--hamie-space-half) var(--hamie-space-2);
      border-radius: var(--hamie-radius-sm);
    }
    .dismiss {
      flex-shrink: 0;
      margin-top: 2px;
      background: none;
      border: none;
      cursor: pointer;
      color: var(--hamie-text-secondary);
      padding: 0;
    }
    .dismiss:hover {
      color: var(--hamie-text-primary);
    }
    ha-icon {
      --mdc-icon-size: 14px;
    }
    ::slotted([slot="details"]) {
      margin-top: var(--hamie-space-2);
    }
  `;
  _onDismiss() {
    this.dispatchEvent(new CustomEvent("hamie-dismiss", { bubbles: true, composed: true }));
  }
  _onAction() {
    this.dispatchEvent(new CustomEvent("hamie-action", { bubbles: true, composed: true }));
  }
  render() {
    return b2`
      <hamie-card padding="md">
        <div class="row">
          ${this.priority ? b2`<hamie-status variant="priority" status=${this.priority}></hamie-status>` : null}
          <div class="body">
            <p class="title">${this.heading}</p>
            <p class="text">${this.body}</p>
            <slot name="details"></slot>
            <div class="actions">
              ${this.actionLabel ? b2`
                    <hamie-button variant="primary" size="xs" @click=${this._onAction}>
                      ${this.actionLabel} <ha-icon icon="mdi:arrow-right"></ha-icon>
                    </hamie-button>
                  ` : null}
              ${this.category ? b2`<span class="category">${this.category}</span>` : null}
            </div>
          </div>
          ${this.dismissible ? b2`
                <button class="dismiss" @click=${this._onDismiss} aria-label="Dismiss">
                  <ha-icon icon="mdi:close"></ha-icon>
                </button>
              ` : null}
        </div>
      </hamie-card>
    `;
  }
};
if (!customElements.get("hamie-problem-card")) {
  customElements.define("hamie-problem-card", HamieProblemCard);
}

// hamie/frontend/views/hamie-view-recommendations.js
var PAGE_SIZE2 = 25;
var HamieViewRecommendations = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _items: { state: true },
    _total: { state: true },
    _offset: { state: true },
    _error: { state: true },
    _analyzing: { state: true },
    _analysisError: { state: true },
    // Analyze-only failure; keeps existing recommendations visible
    _ollamaStatus: { state: true },
    _analysis: { state: true },
    _capability: { state: true },
    _probing: { state: true }
  };
  static styles = i`
    .capability {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      align-items: baseline;
      font-size: 0.85rem;
      color: var(--secondary-text-color, #666);
    }
    .capability strong {
      font-weight: 600;
      color: var(--primary-text-color, #212121);
    }
    .capability-failed {
      flex-basis: 100%;
      margin-top: 0.25rem;
      color: var(--error-color, #c62828);
    }
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-medium);
      box-sizing: border-box;
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      flex-shrink: 0;
    }
    .meta {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .list {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-2-5);
    }
    .confidence {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .details-list {
      margin: 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
    .pager {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--hamie-space-3) 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .analysis-error {
      margin-bottom: var(--hamie-space-4);
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
      font-size: var(--hamie-text-small);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
  `;
  constructor() {
    super();
    this._offset = 0;
  }
  connectedCallback() {
    super.connectedCallback();
    this._load();
  }
  async _load() {
    if (!this.hass) return;
    try {
      const [result, connectors, overview] = await Promise.all([
        this.hass.callWS({
          type: "hamie/recommendations/list",
          offset: this._offset,
          limit: PAGE_SIZE2
        }),
        // Only needed to tell a genuine "nothing to report" empty result
        // apart from "every analysis attempt has been failing" -- both
        // produce an identical empty recommendations list on their own.
        this.hass.callWS({ type: "hamie/connectors/status" }).catch(() => []),
        // The authoritative analysis state. Deriving it here from an empty
        // list plus a healthy connector is exactly how this page came to
        // show "412 incidents", "evidence is too large" and "All clear"
        // together: the provider was healthy, the payload was too large,
        // and the list endpoint cannot tell "nothing is wrong" apart from
        // "nothing was looked at".
        this.hass.callWS({ type: "hamie/explorer/overview" }).catch(() => null)
      ]);
      this._items = result.items;
      this._total = result.total;
      this._ollamaStatus = connectors.find((item) => item.connector_id === "ollama") ?? null;
      this._analysis = overview?.analysis ?? null;
      this._capability = overview?.capability ?? null;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Recommendations are temporarily unavailable.");
    }
  }
  // Zero recommendations is only genuinely "All clear" when it does not
  // also mean "the AI connector has been failing". Only an actual
  // error/degraded connector status counts -- "disabled" or "healthy"
  // (AI simply hasn't run, or last ran fine) both still mean "All clear".
  // The backend decides whether "All clear" is honest. This method only
  // renders that decision -- it must never re-derive it.
  _allClearPermitted() {
    if (!this._analysis) return false;
    return this._analysis.all_clear_permitted === true;
  }
  _analysisIncompleteDescription() {
    const a3 = this._analysis;
    if (!a3) {
      return "HAMIE could not determine whether analysis has covered this scan.";
    }
    const parts = [];
    if (a3.eligible_total) {
      parts.push(`${a3.analyzed_total} of ${a3.eligible_total} findings analyzed`);
    }
    if (a3.groups_total) {
      parts.push(`${a3.groups_analyzed} of ${a3.groups_total} root-cause groups`);
    }
    if (a3.high_priority_unanalyzed) {
      parts.push(`${a3.high_priority_unanalyzed} high-priority incident(s) not analyzed`);
    }
    if (a3.failed_groups) parts.push(`${a3.failed_groups} group(s) failed`);
    const counts = parts.length ? ` (${parts.join(", ")})` : "";
    return `${a3.reason}${counts}. Zero recommendations here does not mean nothing is wrong.`;
  }
  _analysisHeading() {
    switch (this._analysis?.state) {
      case "not_analyzed":
        return "Not analyzed yet";
      case "analyzing":
        return "Analysis running";
      case "failed":
        return "Analysis failed";
      case "stale":
        return "Analysis out of date";
      case "provider_unavailable":
        return "AI provider unavailable";
      default:
        return "Analysis incomplete";
    }
  }
  _ollamaFailureDescription() {
    const status = this._ollamaStatus;
    if (!status || status.status !== "error" && status.status !== "degraded") {
      return null;
    }
    return humanizeCode(
      status.error_code,
      "HAMIE's AI provider has been failing to return a usable analysis. Review Connectors for details."
    );
  }
  _nextPage() {
    this._offset += PAGE_SIZE2;
    this._load();
  }
  _previousPage() {
    this._offset = Math.max(0, this._offset - PAGE_SIZE2);
    this._load();
  }
  // A failed analysis (parse/schema/provider/duplicate-request rejection,
  // or genuinely nothing eligible to analyze) must never make already-
  // loaded, still-valid recommendations disappear -- only the page's own
  // initial load failing does that. This mirrors the exact banner pattern
  // House Health/Intelligence already use for the same reason.
  _reportAnalysisFailure(err, fallback) {
    const message = friendlyError(err, fallback);
    if (this._items) {
      this._analysisError = message;
    } else {
      this._error = message;
    }
  }
  async _onAnalyzeHighestPriority() {
    if (!this.hass) return;
    this._analyzing = true;
    this._analysisError = null;
    try {
      const groups = await this.hass.callWS({ type: "hamie/explorer/groups", search: "", offset: 0, limit: 1 });
      if (groups.items?.length) {
        await this.hass.callWS({ type: "hamie/ai/analyze", group_ids: [groups.items[0].group_id] });
        await this._load();
      }
    } catch (err) {
      this._reportAnalysisFailure(err, "That analysis could not be started.");
    } finally {
      this._analyzing = false;
    }
  }
  // Capability is measured by the backend. This renders the measurement --
  // it never infers "probably fine" from the connector being reachable,
  // which is the mistake that produced a healthy connector alongside zero
  // usable recommendations.
  _capabilitySummary() {
    const c6 = this._capability;
    if (!c6) return null;
    const verdict = c6.result?.verdict ?? c6.gate?.verdict ?? "unknown";
    const model = c6.model || "no model configured";
    const permitted = c6.analysis_permitted === true;
    const failed = c6.gate?.failed_dimensions ?? [];
    const probed = c6.result?.probed_at ? new Date(c6.result.probed_at).toLocaleString() : "never";
    return { verdict, model, permitted, failed, probed, reason: c6.gate?.reason ?? "" };
  }
  async _onProbeCapability() {
    if (!this.hass) return;
    this._probing = true;
    this._analysisError = null;
    try {
      await this.hass.callWS({ type: "hamie/ai/capability/probe" });
      await this._load();
    } catch (err) {
      this._reportAnalysisFailure(err, "The capability probe could not be completed.");
    } finally {
      this._probing = false;
    }
  }
  async _onAnalyzeScanSummary() {
    if (!this.hass) return;
    this._analyzing = true;
    this._analysisError = null;
    try {
      await this.hass.callWS({ type: "hamie/ai/analyze" });
      await this._load();
    } catch (err) {
      this._reportAnalysisFailure(err, "There's nothing for HAMIE to analyze right now.");
    } finally {
      this._analyzing = false;
    }
  }
  async _onDismiss(recommendationId) {
    if (!this.hass) return;
    try {
      await this.hass.callWS({ type: "hamie/ai/review", recommendation_id: recommendationId, state: "rejected" });
      this._items = this._items.filter((item) => item.recommendation_id !== recommendationId);
    } catch (err) {
      this._error = friendlyError(err, "That recommendation could not be dismissed.");
    }
  }
  _onViewFinding(findingId) {
    this.dispatchEvent(
      new CustomEvent("hamie-navigate-finding", { detail: { findingId }, bubbles: true, composed: true })
    );
  }
  _onReviewQueue() {
    this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "remediation" }, bubbles: true, composed: true }));
  }
  render() {
    if (this._error) {
      return b2`<hamie-empty tone="unavailable" heading="Recommendations are unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._items) {
      return b2`<hamie-loading .lines=${3}></hamie-loading>`;
    }
    return b2`
      <hamie-page-header
        heading="Recommendations"
        subtitle="${this._total > 0 ? `${this._total} recommendation${this._total === 1 ? "" : "s"} from HAMIE` : "No recommendations at this time"}"
      >
        <div slot="actions" class="header-actions">
          <hamie-button variant="secondary" size="sm" ?disabled=${this._analyzing} @click=${this._onAnalyzeHighestPriority}>
            Analyze Highest Priority
          </hamie-button>
          <hamie-button variant="secondary" size="sm" ?disabled=${this._analyzing} @click=${this._onAnalyzeScanSummary}>
            ${this._analyzing ? "Analyzing\u2026" : "Analyze Scan Summary"}
          </hamie-button>
          <hamie-button variant="ghost" size="sm" ?disabled=${this._probing} @click=${this._onProbeCapability}>
            ${this._probing ? "Probing\u2026" : "Probe model"}
          </hamie-button>
        </div>
      </hamie-page-header>

      ${(() => {
      const c6 = this._capabilitySummary();
      if (!c6) return null;
      return b2`
          <hamie-card padding="sm">
            <div class="capability" role="status">
              <strong>Model</strong> ${c6.model}
              &middot; <strong>Capability</strong> ${c6.verdict}
              &middot; <strong>Analysis</strong> ${c6.permitted ? "permitted" : "blocked"}
              &middot; <strong>Last probed</strong> ${c6.probed}
              ${c6.failed.length ? b2`<div class="capability-failed">Failing: ${c6.failed.join(", ")}</div>` : null}
              ${!c6.permitted && c6.reason ? b2`<div class="capability-failed">${c6.reason}</div>` : null}
            </div>
          </hamie-card>
        `;
    })()}

      ${this._analysisError ? b2`
            <div class="analysis-error" role="alert">
              <span>${this._analysisError}</span>
              <hamie-button variant="ghost" size="xs" aria-label="Dismiss" @click=${() => this._analysisError = null}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          ` : null}

      ${this._items.length === 0 ? this._ollamaFailureDescription() ? b2`
              <hamie-card padding="md">
                <hamie-empty
                  tone="unavailable"
                  heading="Recent analysis failed"
                  description=${this._ollamaFailureDescription()}
                ></hamie-empty>
              </hamie-card>
            ` : !this._allClearPermitted() ? b2`
              <hamie-card padding="md">
                <hamie-empty
                  tone="unavailable"
                  heading=${this._analysisHeading()}
                  description=${this._analysisIncompleteDescription()}
                ></hamie-empty>
              </hamie-card>
            ` : b2`
              <hamie-card padding="md">
                <hamie-empty
                  tone="positive"
                  heading="All clear"
                  description="Your home is running optimally. HAMIE has no recommendations."
                ></hamie-empty>
              </hamie-card>
            ` : b2`
            <div class="list">
              ${this._items.map((item) => {
      const findingId = item.finding_ids?.[0];
      const dismissible = item.review_state === "new" && !item.stale;
      const stateLabel = item.status || item.review_state;
      const coverage = item.coverage || {};
      return b2`
                  <hamie-problem-card
                    heading=${item.summary}
                    body=${item.probable_causes?.[0] || ""}
                    actionLabel=${findingId ? "View evidence" : ""}
                    ?dismissible=${dismissible}
                    @hamie-action=${() => findingId && this._onViewFinding(findingId)}
                    @hamie-dismiss=${() => this._onDismiss(item.recommendation_id)}
                  >
                    <div slot="details">
                      <p class="meta">
                        <strong>Evidence:</strong> ${item.finding_ids?.length || 0} affected finding${item.finding_ids?.length === 1 ? "" : "s"} ·
                        last observed ${safeRelativeTime(item.evidence_last_observed_at)}
                      </p>
                      <p class="meta">
                        <strong>Recommended action:</strong>
                        ${item.proposed_repair_plan?.[0] || item.recommended_checks?.[0] || "Gather more evidence"}
                      </p>
                      <span class="confidence">
                        Confidence: ${item.confidence} · Risk: ${item.risk || "Unknown"} · Status: ${stateLabel}
                      </span>

                      <hamie-disclosure label="Details">
                        <p class="meta">
                          <strong>Why it matters:</strong>
                          ${item.risk_notes?.[0] || "Impact is not yet confirmed; inspect the current evidence before deciding."}
                        </p>
                        <p class="meta">
                          <strong>Root cause:</strong>
                          ${item.confidence === "high" ? "Likely" : "Unknown"} — ${item.probable_causes?.[0] || "More evidence is required"}
                        </p>
                        <p class="meta">
                          <strong>Dependencies checked:</strong> AI advisories do not determine dependency completeness.
                          Inspect the deterministic dependency decision before any proposal.
                        </p>
                        <p class="meta">
                          <strong>Execution capability:</strong> Advisory only. Executable proposals, when eligible, appear separately in Review Queue.
                        </p>
                        <p class="meta">
                          Generated: ${safeRelativeTime(item.generated_at)} ·
                          Evidence observed: ${safeRelativeTime(item.evidence_last_observed_at)}
                        </p>
                        <p class="meta">
                          Coverage: ${coverage.coverage || "unknown"} ·
                          ${coverage.selected_findings ?? item.finding_ids?.length ?? 0} selected ·
                          ${coverage.groups_analyzed ?? item.group_ids?.length ?? 0} root-cause groups analyzed ·
                          ${coverage.skipped_findings ?? 0} deferred
                        </p>
                        <p class="meta">
                          Why selected: ${coverage.selection_reason || "Selected from the highest-impact current evidence"} ·
                          Repairability: ${item.repairability || "Advisory only"}
                        </p>
                        ${item.recommended_checks?.length ? b2`<ul class="details-list">${item.recommended_checks.map((check) => b2`<li>${check}</li>`)}</ul>` : null}
                        ${item.proposed_repair_plan?.length ? b2`
                              <p class="meta"><strong>Non-executing plan:</strong></p>
                              <ul class="details-list">${item.proposed_repair_plan.map((step) => b2`<li>${step}</li>`)}</ul>
                            ` : null}
                        <p class="meta">
                          <strong>Affected findings:</strong> ${item.finding_ids?.join(", ") || "Unknown"}
                        </p>
                      </hamie-disclosure>

                      <hamie-button variant="secondary" size="xs" @click=${this._onReviewQueue}>
                        Review proposals
                      </hamie-button>
                    </div>
                  </hamie-problem-card>
                `;
    })}
            </div>
            ${this._total > PAGE_SIZE2 ? b2`
                  <div class="pager">
                    <hamie-button variant="ghost" size="xs" ?disabled=${this._offset === 0} @click=${this._previousPage}>Previous</hamie-button>
                    <span>${this._offset + 1}–${Math.min(this._offset + PAGE_SIZE2, this._total)} of ${this._total}</span>
                    <hamie-button variant="ghost" size="xs" ?disabled=${this._offset + PAGE_SIZE2 >= this._total} @click=${this._nextPage}>Next</hamie-button>
                  </div>
                ` : null}
          `}
    `;
  }
};
if (!customElements.get("hamie-view-recommendations")) {
  customElements.define("hamie-view-recommendations", HamieViewRecommendations);
}

// hamie/frontend/components/hamie-switch.js
var HamieSwitch = class extends i4 {
  static properties = {
    checked: { type: Boolean, reflect: true },
    disabled: { type: Boolean, reflect: true }
  };
  // Without an explicit default, `checked`/`disabled` start life as
  // `undefined` rather than `false` -- and since the `?checked=${...}`
  // binding a parent uses only ever *toggles the attribute*, a switch
  // whose real value is false from first render (never flipped true)
  // never gets an attributeChangedCallback at all, so the property is
  // left `undefined` forever instead of `false`. Any code that reads
  // `.checked` directly (not just `aria-checked` in this render(), which
  // happened to mask it by coercing with `? "true" : "false"`) would see
  // the wrong type for an off switch that was never touched.
  constructor() {
    super();
    this.checked = false;
    this.disabled = false;
  }
  static styles = i`
    :host {
      display: inline-flex;
    }
    button {
      position: relative;
      width: 36px;
      height: 20px;
      border-radius: var(--hamie-radius-pill);
      border: none;
      padding: 0;
      cursor: pointer;
      background: var(--hamie-surface-raised);
      transition: background-color var(--hamie-motion-fast) var(--hamie-motion-ease);
      flex-shrink: 0;
    }
    button[aria-checked="true"] {
      background: var(--hamie-accent-fill-loud);
    }
    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    button:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 2px;
    }
    .thumb {
      position: absolute;
      top: 2px;
      left: 2px;
      width: 16px;
      height: 16px;
      border-radius: var(--hamie-radius-circle);
      background: var(--hamie-accent-on);
      transition: transform var(--hamie-motion-fast) var(--hamie-motion-ease);
    }
    button[aria-checked="true"] .thumb {
      transform: translateX(16px);
    }
  `;
  _toggle() {
    if (this.disabled) return;
    this.checked = !this.checked;
    this.dispatchEvent(
      new CustomEvent("hamie-change", {
        detail: { checked: this.checked },
        bubbles: true,
        composed: true
      })
    );
  }
  render() {
    return b2`
      <button
        type="button"
        role="switch"
        aria-checked=${this.checked ? "true" : "false"}
        ?disabled=${this.disabled}
        @click=${this._toggle}
      >
        <span class="thumb"></span>
      </button>
    `;
  }
};
if (!customElements.get("hamie-switch")) {
  customElements.define("hamie-switch", HamieSwitch);
}

// hamie/frontend/views/hamie-view-remediation.js
var PAGE_SIZE3 = 25;
var TABS2 = [
  { id: "ready", label: "Ready" },
  { id: "needs_evidence", label: "Needs Evidence" },
  { id: "blocked", label: "Blocked" },
  { id: "approved", label: "Approved" },
  { id: "history", label: "History" }
];
var HISTORY_STATUSES = /* @__PURE__ */ new Set(["verified", "failed", "rolled_back", "rollback_failed", "rejected", "snoozed"]);
var STATUS_CHIP = {
  needs_review: "warning",
  snoozed: "idle",
  approved: "active",
  blocked: "critical",
  executing: "running",
  verified: "healthy",
  failed: "critical",
  rolled_back: "warning",
  rollback_failed: "critical",
  rejected: "idle"
};
var STATUS_LABELS = {
  needs_review: "Needs Review",
  snoozed: "Snoozed",
  approved: "Approved",
  blocked: "Blocked",
  executing: "Executing",
  verified: "Verified",
  failed: "Failed",
  rolled_back: "Rolled Back",
  rollback_failed: "Rollback Failed",
  rejected: "Rejected"
};
var DEPENDENCY_LABELS = {
  not_started: "Not checked",
  in_progress: "Checking\u2026",
  complete: "Checked",
  partial: "Partially checked",
  failed: "Source unavailable"
};
var WORK_ITEM_LIFECYCLE_LABELS = {
  needs_evidence: "Needs evidence",
  dependency_blocked: "Blocked",
  ai_investigation: "Needs investigation",
  manual_repair: "Manual repair",
  snoozed: "Snoozed",
  completed: "Completed",
  superseded: "Superseded"
};
var WORK_ITEM_LIFECYCLE_TONE = {
  needs_evidence: "evidence",
  dependency_blocked: "info",
  ai_investigation: "warning",
  manual_repair: "warning",
  snoozed: "unknown",
  completed: "healthy",
  superseded: "unknown"
};
var ACTION_TYPE_LABELS = {
  disable_entity_batch: "Disable unused entities",
  disable_unused_entity: "Disable unused entity",
  enable_entity: "Re-enable entity",
  "hamie.mark_for_manual_remediation": "Flag for manual review"
};
function humanizeActionType(actionType) {
  if (ACTION_TYPE_LABELS[actionType]) return ACTION_TYPE_LABELS[actionType];
  const bare = actionType.includes(".") ? actionType.split(".").at(-1) : actionType;
  const words = bare.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
function truncatedDigest(value) {
  return value ? `${value.slice(0, 16)}\u2026` : "\u2014";
}
var HamieViewRemediation = class extends i4 {
  static properties = {
    hass: { attribute: false },
    // Set by hamie-app.js when Overview's "attention" row or next-action
    // card navigates here -- picks the starting tab (see connectedCallback).
    focusStatus: { type: String },
    _items: { state: true },
    _total: { state: true },
    _sectionCounts: { state: true },
    _maintenanceWorkItems: { state: true },
    _capabilities: { state: true },
    _offset: { state: true },
    _activeTab: { state: true },
    _expandedBatches: { state: true },
    _error: { state: true },
    _actionError: { state: true },
    _busy: { state: true },
    // recommendation_id currently mid-action, or true for a dialog action
    _detail: { state: true },
    // full DetailResult for _detailRecommendationId
    _detailRecommendationId: { state: true },
    _detailLoading: { state: true },
    _pendingReject: { state: true },
    // { remediation_plan_id } once Reject is clicked
    _rejectReason: { state: true },
    _pendingRevoke: { state: true },
    // { approval_id } once Revoke is clicked
    _revokeReason: { state: true },
    _pendingApprove: { state: true },
    // { plan, preview } once Approve is clicked
    _destructiveAck: { state: true },
    _backupAck: { state: true },
    _pendingExecute: { state: true },
    // { plan, approval } once Execute is clicked
    _executeConfirmed: { state: true },
    _pendingRollback: { state: true },
    // { plan, execution, affectedObject }
    _pendingSnooze: { state: true },
    _snoozeDuration: { state: true },
    _snoozeReason: { state: true },
    _snoozeUntil: { state: true },
    _gatherEvidenceResult: { state: true }
    // { work_item_id, resolved, still_missing } from the last gather_evidence call
  };
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .header {
      margin-bottom: var(--hamie-space-4);
    }
    h1 {
      margin: 0;
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .subtitle {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .action-error {
      margin-bottom: var(--hamie-space-3);
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
      font-size: var(--hamie-text-small);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .tabs {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1);
      margin-bottom: var(--hamie-space-4);
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .tabs button {
      padding: var(--hamie-space-2) var(--hamie-space-1);
      margin-right: var(--hamie-space-4);
      border: 0;
      border-bottom: 2px solid transparent;
      background: transparent;
      color: var(--hamie-text-secondary);
      font: var(--hamie-weight-medium) var(--hamie-text-small)/1.2 inherit;
      cursor: pointer;
    }
    .tabs button[aria-selected="true"] {
      color: var(--hamie-text-primary);
      border-bottom-color: var(--hamie-accent);
    }
    .tab-count {
      color: var(--hamie-text-secondary);
      font-size: var(--hamie-text-micro);
    }
    .list {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-2-5);
    }
    .batch-members {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-2-5);
      margin: 0 0 var(--hamie-space-3) var(--hamie-space-5);
      padding-left: var(--hamie-space-3);
      border-left: 2px solid var(--hamie-border-hairline);
    }
    .row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .title {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .meta {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .badges {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      flex-shrink: 0;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      margin-top: var(--hamie-space-2);
      flex-wrap: wrap;
    }
    .unsupported-reason {
      margin-top: var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-status-critical);
    }
    .pager {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--hamie-space-3) 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .detail-section {
      margin-top: var(--hamie-space-3);
    }
    .detail-section h3 {
      margin: 0 0 var(--hamie-space-1);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .detail-meta {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.8;
    }
    .detail-list {
      margin: 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
    .fingerprint {
      font-family: var(--hamie-font-code);
      font-size: var(--hamie-text-caption);
    }
    .step {
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-md);
      padding: var(--hamie-space-2) var(--hamie-space-2-5);
      margin-bottom: var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
    }
    .step-warning {
      color: var(--hamie-status-warning);
    }
    .ack-row {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2-5);
      margin-top: var(--hamie-space-3);
    }
    .ack-row label {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-primary);
    }
    .dialog-reason {
      margin-top: var(--hamie-space-3);
    }
    .dialog-reason label {
      display: block;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      margin-bottom: var(--hamie-space-1);
    }
    .confirm-summary {
      background: var(--hamie-surface-raised);
      border-radius: var(--hamie-radius-md);
      padding: var(--hamie-space-3);
      font-size: var(--hamie-text-small);
      line-height: 1.8;
    }
  `;
  constructor() {
    super();
    this._offset = 0;
    this._sectionCounts = {};
    this._maintenanceWorkItems = [];
    this._activeTab = "ready";
    this._expandedBatches = /* @__PURE__ */ new Set();
  }
  connectedCallback() {
    super.connectedCallback();
    if (this.focusStatus === "ready_to_execute") this._activeTab = "approved";
    this._load();
  }
  // Ready/Approved map onto one real `status` value each and are
  // fetched server-side, paginated. Blocked/History each combine
  // several real status values the server can only filter by one at a
  // time -- fetched as one broader, unfiltered-by-status page and
  // narrowed client-side (see TABS' own comment for why this is an
  // acceptable, bounded trade-off here).
  _statusForTab(tab) {
    if (tab === "ready") return "needs_review";
    if (tab === "approved") return "approved";
    return void 0;
  }
  async _load() {
    if (!this.hass) return;
    try {
      const status = this._statusForTab(this._activeTab);
      const [result, capabilities] = await Promise.all([
        this.hass.callWS({
          type: "hamie/remediation/queue/list",
          ...status ? { status } : {},
          offset: this._offset,
          limit: PAGE_SIZE3
        }),
        this.hass.callWS({ type: "hamie/remediation/capabilities" })
      ]);
      let items = result.items;
      let total = result.total;
      if (this._activeTab === "blocked") {
        items = items.filter((item) => item.status === "blocked");
        total = items.length;
      } else if (this._activeTab === "history") {
        items = items.filter((item) => HISTORY_STATUSES.has(item.status));
        total = items.length;
      }
      this._items = items;
      this._capabilities = capabilities;
      this._total = total;
      this._sectionCounts = result.section_counts || {};
      this._maintenanceWorkItems = result.maintenance_work_items || [];
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "The remediation queue is temporarily unavailable.");
    }
  }
  _setTab(tab) {
    this._activeTab = tab;
    this._offset = 0;
    this._expandedBatches = /* @__PURE__ */ new Set();
    this._load();
  }
  _toggleBatch(key) {
    const next = new Set(this._expandedBatches);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    this._expandedBatches = next;
  }
  // Batch-first grouping (mission redesign section 8): the Ready tab's
  // items grouped by their real `action_type` (e.g. disable_entity_batch)
  // -- the actual remediation action a user would approve, not an
  // artificial category. Each group's members are further broken down
  // by title so a user sees "127 items" as a small number of named
  // batches instead of 127 individual rows to scroll through.
  _readyBatches(items) {
    const byAction = /* @__PURE__ */ new Map();
    for (const item of items) {
      const key = item.action_type || "other";
      if (!byAction.has(key)) byAction.set(key, []);
      byAction.get(key).push(item);
    }
    return [...byAction.entries()].map(([actionType, members]) => ({ actionType, members })).sort((a3, b3) => b3.members.length - a3.members.length);
  }
  _nextPage() {
    this._offset += PAGE_SIZE3;
    this._load();
  }
  _previousPage() {
    this._offset = Math.max(0, this._offset - PAGE_SIZE3);
    this._load();
  }
  async _openDetail(recommendationId) {
    this._detailRecommendationId = recommendationId;
    this._detailLoading = true;
    await this._reloadDetail();
    this._detailLoading = false;
  }
  async _reloadDetail() {
    if (!this.hass || !this._detailRecommendationId) return;
    try {
      this._detail = await this.hass.callWS({
        type: "hamie/remediation/detail/get",
        recommendation_id: this._detailRecommendationId
      });
      this._actionError = null;
    } catch (err) {
      this._actionError = friendlyError(err, "That detail could not be loaded.");
    }
  }
  _closeDetail() {
    this._detail = null;
    this._detailRecommendationId = null;
  }
  async _refreshEvidence() {
    if (!this.hass || this._busy) return;
    this._busy = "refresh_evidence";
    this._actionError = null;
    try {
      await this.hass.callService("hamie", "scan", {});
      await this._load();
      if (this._detailRecommendationId) await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "Evidence could not be refreshed.");
    } finally {
      this._busy = null;
    }
  }
  _setSnoozeDuration(value) {
    this._snoozeDuration = String(value);
    this._snoozeUntil = new Date(Date.now() + Number(value) * 6e4).toISOString();
  }
  _openSnooze(item) {
    this._pendingSnooze = { item };
    this._snoozeReason = "";
    this._setSnoozeDuration("1440");
  }
  _cancelSnooze() {
    this._pendingSnooze = null;
    this._snoozeReason = "";
    this._snoozeUntil = null;
  }
  async _confirmSnooze() {
    if (!this.hass || !this._pendingSnooze || this._busy || !this._snoozeUntil) return;
    const { item } = this._pendingSnooze;
    this._busy = item.plan_id;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/snooze",
        remediation_plan_id: item.plan_id,
        snooze_until: this._snoozeUntil,
        ...this._snoozeReason.trim() ? { reason: this._snoozeReason.trim() } : {},
        idempotency_token: idempotencyToken()
      });
      this._cancelSnooze();
      await this._load();
      if (this._detailRecommendationId) await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That proposal could not be snoozed.");
    } finally {
      this._busy = null;
    }
  }
  async _gatherEvidence(item) {
    if (!this.hass || this._busy || !item.work_item_id) return;
    this._busy = item.work_item_id;
    this._actionError = null;
    try {
      const result = await this.hass.callWS({
        type: "hamie/remediation/gather_evidence",
        work_item_id: item.work_item_id
      });
      this._gatherEvidenceResult = { title: item.title, ...result };
      await this._load();
    } catch (err) {
      this._actionError = friendlyError(err, "Evidence could not be gathered for that item.");
    } finally {
      this._busy = null;
    }
  }
  async _resumePlan(item) {
    if (!this.hass || this._busy || !item.plan_id) return;
    this._busy = item.plan_id;
    this._actionError = null;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/resume",
        remediation_plan_id: item.plan_id,
        idempotency_token: idempotencyToken()
      });
      await this._load();
      if (this._detailRecommendationId) await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That proposal could not be resumed.");
    } finally {
      this._busy = null;
    }
  }
  async _createOrRefreshPlan(recommendationId) {
    if (!this.hass || this._busy) return;
    this._busy = recommendationId;
    this._actionError = null;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/plan/create",
        recommendation_id: recommendationId,
        idempotency_token: idempotencyToken()
      });
      await this._load();
      if (this._detailRecommendationId === recommendationId) {
        await this._reloadDetail();
      }
    } catch (err) {
      this._actionError = friendlyError(err, "That plan could not be created.");
    } finally {
      this._busy = null;
    }
  }
  async _generatePreview(plan) {
    if (!this.hass || this._busy) return;
    this._busy = plan.remediation_plan_id;
    this._actionError = null;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/preview/generate",
        remediation_plan_id: plan.remediation_plan_id,
        idempotency_token: idempotencyToken()
      });
      await this._load();
      await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That preview could not be generated.");
    } finally {
      this._busy = null;
    }
  }
  _openApprove(plan) {
    this._destructiveAck = false;
    this._backupAck = false;
    this._pendingApprove = { plan };
  }
  _cancelApprove() {
    this._pendingApprove = null;
  }
  async _confirmApprove() {
    if (!this.hass || !this._pendingApprove) return;
    const { plan } = this._pendingApprove;
    this._busy = plan.remediation_plan_id;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/approve",
        remediation_plan_id: plan.remediation_plan_id,
        plan_fingerprint: plan.plan_fingerprint,
        preview_digest: plan.preview_digest,
        destructive_acknowledged: this._destructiveAck,
        backup_acknowledged: this._backupAck,
        warnings_acknowledged: [],
        idempotency_token: idempotencyToken()
      });
      this._pendingApprove = null;
      await this._load();
      await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That plan could not be approved.");
    } finally {
      this._busy = null;
    }
  }
  _openReject(plan) {
    this._rejectReason = "";
    this._pendingReject = { plan };
  }
  _cancelReject() {
    this._pendingReject = null;
    this._rejectReason = "";
  }
  async _confirmReject() {
    if (!this.hass || !this._pendingReject) return;
    const { plan } = this._pendingReject;
    this._busy = plan.remediation_plan_id;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/reject",
        remediation_plan_id: plan.remediation_plan_id,
        reason: this._rejectReason.trim(),
        idempotency_token: idempotencyToken()
      });
      this._pendingReject = null;
      this._rejectReason = "";
      await this._load();
      await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That plan could not be rejected.");
    } finally {
      this._busy = null;
    }
  }
  _openRevoke(approval) {
    this._revokeReason = "";
    this._pendingRevoke = { approval };
  }
  _cancelRevoke() {
    this._pendingRevoke = null;
    this._revokeReason = "";
  }
  async _confirmRevoke() {
    if (!this.hass || !this._pendingRevoke) return;
    const { approval } = this._pendingRevoke;
    this._busy = approval.approval_id;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/revoke",
        approval_id: approval.approval_id,
        reason: this._revokeReason.trim(),
        idempotency_token: idempotencyToken()
      });
      this._pendingRevoke = null;
      this._revokeReason = "";
      await this._load();
      await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That approval could not be revoked.");
    } finally {
      this._busy = null;
    }
  }
  _openExecute(plan, approval) {
    this._executeConfirmed = false;
    const affectedObject = this._detail?.recommendation?.affected_object?.source_id ?? plan.recommendation_id;
    this._pendingExecute = { plan, approval, affectedObject };
  }
  _cancelExecute() {
    this._pendingExecute = null;
  }
  async _confirmExecute() {
    if (!this.hass || !this._pendingExecute || !this._executeConfirmed) return;
    const { plan, approval } = this._pendingExecute;
    this._busy = plan.remediation_plan_id;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/execute",
        remediation_plan_id: plan.remediation_plan_id,
        approval_id: approval.approval_id,
        idempotency_token: idempotencyToken(),
        confirmed: true
      });
      this._pendingExecute = null;
      await this._load();
      await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That remediation could not be executed.");
    } finally {
      this._busy = null;
    }
  }
  // A plan/preview loaded strictly before the currently-displayed
  // approval was granted, or that has since been refreshed, no longer
  // matches the approval's own bound fingerprint/digest -- the queue's
  // own `status` already reflects this server-side, but Execute is also
  // independently gated here so a stale client render can never enable
  // it even for one frame.
  _openRollback(plan, execution) {
    const affectedObject = this._detail?.recommendation?.affected_object?.source_id ?? plan.recommendation_id;
    this._pendingRollback = { plan, execution, affectedObject };
  }
  _cancelRollback() {
    this._pendingRollback = null;
  }
  async _confirmRollback() {
    if (!this.hass || !this._pendingRollback) return;
    const { plan, execution } = this._pendingRollback;
    this._busy = plan.remediation_plan_id;
    try {
      await this.hass.callWS({
        type: "hamie/remediation/rollback",
        remediation_plan_id: plan.remediation_plan_id,
        execution_id: execution.execution_id,
        idempotency_token: idempotencyToken(),
        confirmed: true
      });
      this._pendingRollback = null;
      await this._load();
      await this._reloadDetail();
    } catch (err) {
      this._actionError = friendlyError(err, "That verified repair could not be rolled back.");
    } finally {
      this._busy = null;
    }
  }
  _approvalIsValidFor(plan, approval) {
    if (!approval || approval.state !== "granted" || approval.revoked_at) return false;
    return approval.plan_fingerprint === plan.plan_fingerprint && approval.preview_digest === plan.preview_digest && new Date(approval.expires_at).getTime() > Date.now();
  }
  render() {
    if (this._error) {
      return b2`<hamie-empty tone="unavailable" heading="Review Queue is unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._items) {
      return b2`<hamie-loading .lines=${4}></hamie-loading>`;
    }
    const readyCount = this._sectionCounts.ready_for_review || 0;
    const needsEvidenceItems = this._maintenanceWorkItems.filter((item) => item.lifecycle_state === "needs_evidence");
    const blockedWorkItems = this._maintenanceWorkItems.filter(
      (item) => item.lifecycle_state === "dependency_blocked" || item.lifecycle_state === "ai_investigation" || item.lifecycle_state === "manual_repair"
    );
    const tabCounts = {
      ready: this._activeTab === "ready" ? this._total : void 0,
      needs_evidence: needsEvidenceItems.length,
      blocked: (this._activeTab === "blocked" ? this._total : 0) + blockedWorkItems.length,
      approved: this._activeTab === "approved" ? this._total : void 0,
      history: this._activeTab === "history" ? this._total : void 0
    };
    return b2`
      <hamie-page-header
        heading="Review Queue"
        subtitle="${readyCount} item${readyCount === 1 ? "" : "s"} need your decision"
      >
        <div slot="actions">
          <hamie-button variant="secondary" size="xs" ?disabled=${Boolean(this._busy)} @click=${this._refreshEvidence}>
            Refresh evidence
          </hamie-button>
        </div>
      </hamie-page-header>

      ${this._actionError ? b2`
            <div class="action-error">
              <span role="alert">${this._actionError}</span>
              <hamie-button variant="ghost" size="xs" aria-label="Dismiss error" @click=${() => this._actionError = null}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          ` : null}

      <div class="tabs" role="tablist" aria-label="Review Queue status">
        ${TABS2.map(
      (tab) => b2`
            <button
              role="tab"
              aria-selected=${tab.id === this._activeTab ? "true" : "false"}
              @click=${() => this._setTab(tab.id)}
            >
              ${tab.label}${tabCounts[tab.id] ? b2` <span class="tab-count">${tabCounts[tab.id]}</span>` : null}
            </button>
          `
    )}
      </div>

      ${this._gatherEvidenceResult ? this._renderGatherEvidenceResult() : null}

      ${this._renderTabContent(needsEvidenceItems, blockedWorkItems)}

      ${this._detailRecommendationId ? this._renderDetailDialog() : null}
      ${this._pendingApprove ? this._renderApproveDialog() : null}
      ${this._pendingReject ? this._renderRejectDialog() : null}
      ${this._pendingRevoke ? this._renderRevokeDialog() : null}
      ${this._pendingExecute ? this._renderExecuteDialog() : null}
      ${this._pendingRollback ? this._renderRollbackDialog() : null}
      ${this._pendingSnooze ? this._renderSnoozeDialog() : null}
    `;
  }
  _renderPager() {
    return b2`
      <div class="pager">
        <hamie-button variant="ghost" size="xs" ?disabled=${this._offset === 0} @click=${this._previousPage}>Previous</hamie-button>
        <span>${this._total === 0 ? 0 : this._offset + 1}–${Math.min(this._offset + PAGE_SIZE3, this._total)} of ${this._total}</span>
        <hamie-button variant="ghost" size="xs" ?disabled=${this._offset + PAGE_SIZE3 >= this._total} @click=${this._nextPage}>Next</hamie-button>
      </div>
    `;
  }
  _renderTabContent(needsEvidenceItems, blockedWorkItems) {
    if (this._activeTab === "needs_evidence") {
      return needsEvidenceItems.length ? b2`<div class="list">${needsEvidenceItems.map((item) => this._renderMaintenanceWorkRow(item))}</div>` : b2`<hamie-card padding="md"><hamie-empty tone="positive" heading="Nothing needs more evidence right now"></hamie-empty></hamie-card>`;
    }
    if (this._activeTab === "blocked") {
      const hasAny = this._items.length || blockedWorkItems.length;
      return !hasAny ? b2`<hamie-card padding="md"><hamie-empty tone="positive" heading="Nothing is blocked right now"></hamie-empty></hamie-card>` : b2`
            <div class="list">
              ${blockedWorkItems.map((item) => this._renderMaintenanceWorkRow(item))}
              ${this._items.map((item) => this._renderRow(item))}
            </div>
          `;
    }
    if (this._activeTab === "ready") {
      if (!this._items.length) {
        return b2`<hamie-card padding="md"><hamie-empty tone="positive" heading="Nothing needs review right now"></hamie-empty></hamie-card>`;
      }
      return b2`
        <div class="list">${this._readyBatches(this._items).map((batch) => this._renderBatch(batch))}</div>
        ${this._renderPager()}
      `;
    }
    return this._items.length ? b2`
          <div class="list">${this._items.map((item) => this._renderRow(item))}</div>
          ${this._renderPager()}
        ` : b2`<hamie-card padding="md"><hamie-empty tone="neutral" heading="Nothing here yet"></hamie-empty></hamie-card>`;
  }
  _renderBatch(batch) {
    const key = batch.actionType;
    const defaultExpanded = batch.members.length <= 5;
    const expanded = this._expandedBatches.has(key) !== defaultExpanded;
    const label = humanizeActionType(batch.actionType);
    const byTitle = /* @__PURE__ */ new Map();
    for (const item of batch.members) {
      byTitle.set(item.title, (byTitle.get(item.title) || 0) + 1);
    }
    const subCounts = [...byTitle.entries()].sort((a3, b3) => b3[1] - a3[1]);
    const shownSubCounts = subCounts.slice(0, 5);
    const remainingSubCounts = subCounts.length - shownSubCounts.length;
    return b2`
      <hamie-card padding="md">
        <div class="row">
          <div>
            <p class="title">${label}</p>
            <p class="meta">${batch.members.length} item${batch.members.length === 1 ? "" : "s"}</p>
            ${subCounts.length > 1 ? b2`<p class="meta">
                  ${shownSubCounts.map(([title, count]) => `${title} ${count}`).join(" \xB7 ")}${remainingSubCounts > 0 ? `, +${remainingSubCounts} more` : ""}
                </p>` : null}
          </div>
          <hamie-button variant="secondary" size="xs" @click=${() => this._toggleBatch(key)}>
            ${expanded ? "Collapse" : `Review ${batch.members.length}`}
          </hamie-button>
        </div>
      </hamie-card>
      ${expanded ? b2`<div class="batch-members">${batch.members.map((item) => this._renderRow(item))}</div>` : null}
    `;
  }
  _renderMaintenanceWorkSection() {
    return b2`
      <hamie-section heading="Maintenance work (not yet executable)"></hamie-section>
      <p class="subtitle">
        ${this._maintenanceWorkItems.length} item${this._maintenanceWorkItems.length === 1 ? "" : "s"}
        HAMIE found but cannot act on automatically yet -- durable, not lost when this page reloads.
      </p>
      <div class="list">
        ${this._maintenanceWorkItems.map((item) => this._renderMaintenanceWorkRow(item))}
      </div>
    `;
  }
  _renderGatherEvidenceResult() {
    const result = this._gatherEvidenceResult;
    return b2`
      <div class="action-error" style="background: var(--hamie-status-info-fill); color: var(--hamie-text-primary);">
        <span>
          ${result.resolved ? `"${result.title}" -- evidence gathered, now actionable and moved to the review queue.` : `"${result.title}" -- evidence gathered, still blocked${result.still_missing?.length ? `: missing ${result.still_missing.join(", ")}` : ""}.`}
        </span>
        <hamie-button variant="ghost" size="xs" @click=${() => this._gatherEvidenceResult = null}>Dismiss</hamie-button>
      </div>
    `;
  }
  _renderMaintenanceWorkRow(item) {
    const shown = item.affected_entity_ids.slice(0, 5);
    const more = item.entity_count - shown.length;
    const busy = this._busy === item.work_item_id;
    return b2`
      <hamie-card padding="md">
        <div class="row">
          <div>
            <p class="title">${item.title} (${item.entity_count})</p>
            <p class="meta">${item.reason}</p>
            <p class="meta">${shown.join(", ")}${more > 0 ? `, +${more} more` : ""}</p>
          </div>
          <div class="badges">
            <hamie-status
              status=${WORK_ITEM_LIFECYCLE_TONE[item.lifecycle_state] || "info"}
              label=${WORK_ITEM_LIFECYCLE_LABELS[item.lifecycle_state] || item.lifecycle_state}
            ></hamie-status>
          </div>
        </div>
        <div class="actions">
          <hamie-button
            variant="secondary"
            size="xs"
            ?disabled=${busy}
            @click=${() => this._gatherEvidence(item)}
          >
            ${busy ? "Gathering evidence\u2026" : "Gather Evidence"}
          </hamie-button>
        </div>
      </hamie-card>
    `;
  }
  _renderRow(item) {
    const busy = this._busy === item.recommendation_id || this._busy === item.plan_id;
    return b2`
      <hamie-card padding="md">
        <div class="row">
          <div>
            <p class="title">${item.title}</p>
            <p class="meta">
              ${item.category} / ${item.subtype} · ${item.affected_object} · risk ${item.risk_level} · confidence ${item.confidence}
              · dependencies: ${DEPENDENCY_LABELS[item.dependency_status] || item.dependency_status}
              · updated ${relativeTime(item.updated_at)}
            </p>
          </div>
          <div class="badges">
            <hamie-status status=${STATUS_CHIP[item.status] || "unknown"} label=${STATUS_LABELS[item.status] || item.status}></hamie-status>
          </div>
        </div>
        ${!item.execution_supported && item.unsupported_reason ? b2`<p class="unsupported-reason">${item.unsupported_reason}</p>` : null}
        ${item.section === "snoozed" && item.snooze_until ? b2`<p class="meta">Snoozed until ${new Date(item.snooze_until).toLocaleString()}${item.snooze_reason ? ` \xB7 ${item.snooze_reason}` : ""}</p>` : null}
        <div class="actions">
          <hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._openDetail(item.recommendation_id)}>
            Inspect
          </hamie-button>
          <hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._createOrRefreshPlan(item.recommendation_id)}>
            ${item.plan_id ? "Review proposal" : "Create repair proposal"}
          </hamie-button>
          ${item.plan_id && ["ready_for_review", "needs_more_evidence", "awaiting_backup", "awaiting_approval"].includes(item.section) ? b2`<hamie-button variant="ghost" size="xs" ?disabled=${busy} @click=${() => this._openSnooze(item)}>Snooze</hamie-button>` : null}
          ${item.plan_id && item.section === "snoozed" ? b2`<hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._resumePlan(item)}>Resume now</hamie-button>` : null}
        </div>
      </hamie-card>
    `;
  }
  _renderDetailDialog() {
    if (this._detailLoading || !this._detail) {
      return b2`
        <hamie-dialog open heading="Loading…" @hamie-dialog-closed=${this._closeDetail}>
          <hamie-loading .lines=${3}></hamie-loading>
        </hamie-dialog>
      `;
    }
    const { recommendation, plan, approval, executions, rollbacks, status } = this._detail;
    const dep = recommendation.dependency_analysis;
    const approvalValid = plan && this._approvalIsValidFor(plan, approval);
    const busy = this._busy === recommendation.recommendation_id || plan && this._busy === plan.remediation_plan_id;
    const latestExecution = executions?.length ? executions[executions.length - 1] : null;
    const rollbackAvailable = plan?.rollback_plan?.supported && latestExecution?.outcome === "succeeded" && !rollbacks?.length;
    return b2`
      <hamie-dialog open heading="${recommendation.title}" @hamie-dialog-closed=${this._closeDetail}>
        <hamie-status status=${STATUS_CHIP[status] || "unknown"} label=${STATUS_LABELS[status] || status}></hamie-status>

        <div class="detail-section">
          <h3>Recommendation</h3>
          <p class="detail-meta">
            ${recommendation.category} / ${recommendation.subtype}<br />
            Affected: ${recommendation.affected_object.source_id}<br />
            Risk: ${recommendation.risk.risk.overall} · Confidence: ${recommendation.confidence.level}
          </p>
          <p>${recommendation.summary}</p>
        </div>

        <div class="detail-section">
          <h3>Dependencies</h3>
          <p class="detail-meta">
            Status: ${DEPENDENCY_LABELS[dep.status] || dep.status} · Confidence: ${dep.confidence}<br />
            ${dep.safe_to_delete === false ? "Deletion not permitted -- dependents exist or have not been ruled out." : ""}
          </p>
          ${dep.inbound_references?.length ? b2`
                <p class="detail-meta">Dependents:</p>
                <ul class="detail-list">${dep.inbound_references.map((ref) => b2`<li>${ref}</li>`)}</ul>
              ` : b2`<p class="detail-meta">No known dependents.</p>`}
          ${dep.unknown_dependencies?.length ? b2`
                <p class="detail-meta step-warning">Unresolved checks:</p>
                <ul class="detail-list">${dep.unknown_dependencies.map((item) => b2`<li>${item}</li>`)}</ul>
              ` : null}
        </div>

        ${plan ? b2`
              <div class="detail-section">
                <h3>Plan</h3>
                <p class="detail-meta">
                  Fingerprint: <span class="fingerprint">${truncatedDigest(plan.plan_fingerprint)}</span><br />
                  Action: ${plan.actions?.[0]?.action_type ?? "\u2014"} · Destructive: ${plan.risk.destructive ? "Yes" : "No"}
                  · Rollback: ${plan.risk.rollback_support} · Backup required: ${plan.requires_backup ? "Yes" : "No"}<br />
                  Expected impact: ${plan.risk.expected_user_visible_impact}
                </p>
                ${!plan.execution_supported ? b2`<p class="unsupported-reason">${plan.unsupported_reason}</p>` : null}
                ${plan.requires_backup ? b2`
                      <div class="step">
                        <strong>Backup provider unavailable</strong>
                        <p class="detail-meta">
                          HAMIE cannot prepare or verify the required Home Assistant backup in this environment.
                          This proposal cannot be approved or executed until a supported backup provider is configured.
                        </p>
                        <hamie-button
                          variant="secondary"
                          size="xs"
                          disabled
                          title="No supported Home Assistant backup provider is configured"
                        >
                          Prepare backup
                        </hamie-button>
                      </div>
                    ` : null}
              </div>

              ${plan.preview_digest ? b2`
                    <div class="detail-section">
                      <h3>Preview</h3>
                      <p class="detail-meta">Digest: <span class="fingerprint">${truncatedDigest(plan.preview_digest)}</span></p>
                    </div>
                  ` : null}

              ${approval ? b2`
                    <div class="detail-section">
                      <h3>Approval</h3>
                      <p class="detail-meta">
                        State: ${approval.state}${approval.revoked_at ? " (revoked)" : ""} · Approved by ${approval.approved_by}<br />
                        Decided: ${relativeTime(approval.decided_at)} · Expires: ${approval.expires_at ? relativeTime(approval.expires_at) : "\u2014"}<br />
                        ${approval.rejection_reason ? b2`Reason: ${approval.rejection_reason}` : null}
                        ${!approvalValid && approval.state === "granted" && !approval.revoked_at ? b2`<br /><span class="step-warning">This approval no longer matches the current plan/preview. Approve again.</span>` : null}
                      </p>
                    </div>
                  ` : null}

              ${executions?.length ? b2`
                    <div class="detail-section">
                      <h3>Execution history</h3>
                      ${executions.map(
      (exec) => b2`
                          <div class="step">
                            ${exec.outcome} · started ${relativeTime(exec.started_at)}
                            ${exec.completed_at ? b2`· completed ${relativeTime(exec.completed_at)}` : null}
                            ${exec.error ? b2`<br /><span class="step-warning">${exec.error}</span>` : null}
                          </div>
                        `
    )}
                    </div>
                  ` : null}

              ${rollbacks?.length ? b2`
                    <div class="detail-section">
                      <h3>Rollback history</h3>
                      ${rollbacks.map(
      (rb) => b2`
                          <div class="step">
                            ${rb.outcome} · initiated ${relativeTime(rb.initiated_at)} · ${rb.reason}
                            ${rb.outcome === "failed" ? b2`<br /><span class="step-warning">Rollback failed -- manual review required.</span>` : null}
                          </div>
                        `
    )}
                    </div>
                  ` : null}

              <div class="actions">
                <hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._createOrRefreshPlan(recommendation.recommendation_id)}>
                  Review proposal
                </hamie-button>
                ${plan.execution_supported && !plan.preview_digest ? b2`
                      <hamie-button variant="secondary" size="xs" ?disabled=${busy} @click=${() => this._generatePreview(plan)}>
                        Preview repair
                      </hamie-button>
                    ` : null}
                ${plan.execution_supported && plan.preview_digest && !approvalValid && plan.state !== "rejected" ? b2`
                      <hamie-button
                        variant="primary"
                        size="xs"
                        ?disabled=${busy || plan.requires_backup && !this._capabilities?.backup_provider_available}
                        title=${plan.requires_backup && !this._capabilities?.backup_provider_available ? "Approval is blocked until a supported backup provider verifies the required backup" : ""}
                        @click=${() => this._openApprove(plan)}
                      >
                        Approve repair
                      </hamie-button>
                      <hamie-button variant="ghost" size="xs" ?disabled=${busy} @click=${() => this._openReject(plan)}>
                        Reject
                      </hamie-button>
                    ` : null}
                ${approvalValid ? b2`
                      <hamie-button variant="primary" size="xs" ?disabled=${busy} @click=${() => this._openExecute(plan, approval)}>
                        Execute approved repair
                      </hamie-button>
                      <hamie-button variant="ghost" size="xs" ?disabled=${busy} @click=${() => this._openRevoke(approval)}>
                        Revoke Approval
                      </hamie-button>
                    ` : null}
                ${rollbackAvailable ? b2`
                      <hamie-button variant="danger" size="xs" ?disabled=${busy} @click=${() => this._openRollback(plan, latestExecution)}>
                        Preview rollback
                      </hamie-button>
                    ` : null}
                <hamie-button variant="ghost" size="xs" ?disabled=${busy} @click=${this._reloadDetail}>
                  Verify
                </hamie-button>
              </div>
            ` : b2`
              <div class="actions">
                <hamie-button variant="primary" size="xs" @click=${() => this._createOrRefreshPlan(recommendation.recommendation_id)}>
                  Create repair proposal
                </hamie-button>
              </div>
            `}

        <hamie-button slot="primary-action" variant="secondary" size="sm" @click=${this._closeDetail}>
          Close
        </hamie-button>
      </hamie-dialog>
    `;
  }
  _renderApproveDialog() {
    const { plan } = this._pendingApprove;
    const canConfirm = (!plan.risk.destructive || this._destructiveAck) && (!plan.requires_backup || this._capabilities?.backup_provider_available && this._backupAck);
    return b2`
      <hamie-dialog
        open
        heading="Approve this repair proposal?"
        cancel-label="Cancel"
        confirm-label="Approve repair"
        .destructive=${plan.risk.destructive}
        .busy=${!!this._busy}
        .errorMessage=${this._actionError || ""}
        .confirmDisabled=${!canConfirm}
        .onConfirm=${() => this._confirmApprove()}
        .onCancel=${() => this._cancelApprove()}
      >
        <p>Approval binds your decision to this exact plan and preview. It does not execute anything.</p>
        <div class="confirm-summary">
          Fingerprint: <span class="fingerprint">${truncatedDigest(plan.plan_fingerprint)}</span><br />
          Preview digest: <span class="fingerprint">${truncatedDigest(plan.preview_digest)}</span>
        </div>
        ${plan.risk.destructive ? b2`
          <div class="ack-row">
            <hamie-switch .checked=${this._destructiveAck} @hamie-change=${(e6) => this._destructiveAck = e6.detail.checked}></hamie-switch>
            <label>I understand this action is destructive.</label>
          </div>` : null}
        ${plan.requires_backup ? b2`
          <div class="ack-row">
            <hamie-switch .checked=${this._backupAck} @hamie-change=${(e6) => this._backupAck = e6.detail.checked}></hamie-switch>
            <label>I verified the required backup status shown above.</label>
          </div>` : null}
      </hamie-dialog>
    `;
  }
  _renderSnoozeDialog() {
    const { item } = this._pendingSnooze;
    const wakeTime = this._snoozeUntil ? new Date(this._snoozeUntil) : null;
    return b2`
      <hamie-dialog
        open
        heading="Snooze this proposal?"
        cancel-label="Cancel"
        confirm-label="Snooze"
        .busy=${!!this._busy}
        .errorMessage=${this._actionError || ""}
        .confirmDisabled=${!this._snoozeUntil}
        .onConfirm=${() => this._confirmSnooze()}
        .onCancel=${() => this._cancelSnooze()}
      >
        <p>
          Snoozing ${item.title} hides this proposal from active review until the selected time.
          It does not approve or execute anything.
        </p>
        <div class="dialog-reason">
          <label for="snooze-duration">Duration</label>
          <hamie-select
            id="snooze-duration"
            .value=${this._snoozeDuration}
            .options=${[
      { value: "60", label: "1 hour" },
      { value: "1440", label: "24 hours" },
      { value: "10080", label: "7 days" }
    ]}
            @hamie-change=${(event) => this._setSnoozeDuration(event.detail.value)}
          ></hamie-select>
        </div>
        <p class="detail-meta">
          Exact wake time:
          <time datetime=${this._snoozeUntil || ""}>${wakeTime ? wakeTime.toLocaleString() : "Unknown"}</time>
        </p>
        <div class="dialog-reason">
          <label for="snooze-reason">Reason (optional)</label>
          <hamie-input
            id="snooze-reason"
            .value=${this._snoozeReason}
            @hamie-input=${(event) => this._snoozeReason = event.detail.value}
          ></hamie-input>
        </div>
      </hamie-dialog>
    `;
  }
  _renderRejectDialog() {
    return b2`
      <hamie-dialog open heading="Reject this plan?" cancel-label="Cancel" confirm-label="Reject"
        destructive .busy=${!!this._busy} .errorMessage=${this._actionError || ""}
        .confirmDisabled=${!this._rejectReason?.trim()}
        .onConfirm=${() => this._confirmReject()} .onCancel=${() => this._cancelReject()}>
        <div class="dialog-reason">
          <label for="reject-reason">Reason (required)</label>
          <hamie-input id="reject-reason" .value=${this._rejectReason}
            @hamie-input=${(e6) => this._rejectReason = e6.detail.value}></hamie-input>
        </div>
      </hamie-dialog>
    `;
  }
  _renderRevokeDialog() {
    return b2`
      <hamie-dialog open heading="Revoke this approval?" cancel-label="Cancel" confirm-label="Revoke approval"
        destructive .busy=${!!this._busy} .errorMessage=${this._actionError || ""}
        .confirmDisabled=${!this._revokeReason?.trim()}
        .onConfirm=${() => this._confirmRevoke()} .onCancel=${() => this._cancelRevoke()}>
        <div class="dialog-reason">
          <label for="revoke-reason">Reason (required)</label>
          <hamie-input id="revoke-reason" .value=${this._revokeReason}
            @hamie-input=${(e6) => this._revokeReason = e6.detail.value}></hamie-input>
        </div>
      </hamie-dialog>
    `;
  }
  _renderExecuteDialog() {
    const { plan, approval, affectedObject } = this._pendingExecute;
    return b2`
      <hamie-dialog
        open
        heading="Execute this approved repair?"
        cancel-label="Cancel"
        confirm-label="Execute approved repair"
        .destructive=${plan.risk.destructive}
        .busy=${!!this._busy}
        .errorMessage=${this._actionError || ""}
        .confirmDisabled=${!this._executeConfirmed}
        .typedConfirmationPhrase=${plan.risk.destructive ? affectedObject : ""}
        .onConfirm=${() => this._confirmExecute()}
        .onCancel=${() => this._cancelExecute()}
      >
        <div class="confirm-summary">
          Action: ${plan.actions?.[0]?.action_type ?? "\u2014"}<br />
          Object: ${affectedObject}<br />
          Risk: ${plan.risk.destructive ? "Destructive" : "Not destructive"} · Rollback: ${plan.risk.rollback_support}<br />
          Backup status: ${plan.requires_backup ? "Required -- verification pending" : "Not required"}<br />
          Approved by: ${approval.approved_by}
        </div>
        <p>Verification runs after the single allowlisted operation. A successful API response alone never resolves the finding.</p>
        <div class="ack-row">
          <hamie-switch .checked=${this._executeConfirmed} @hamie-change=${(e6) => this._executeConfirmed = e6.detail.checked}></hamie-switch>
          <label>I understand and want to execute this approved repair now.</label>
        </div>
      </hamie-dialog>
    `;
  }
  _renderRollbackDialog() {
    const { plan, execution, affectedObject } = this._pendingRollback;
    const rollbackStep = plan.rollback_plan?.steps?.[0];
    return b2`
      <hamie-dialog
        open
        heading="Roll back this verified repair?"
        cancel-label="Cancel"
        confirm-label="Roll back"
        destructive
        .busy=${!!this._busy}
        .errorMessage=${this._actionError || ""}
        .typedConfirmationPhrase=${affectedObject}
        .onConfirm=${() => this._confirmRollback()}
        .onCancel=${() => this._cancelRollback()}
      >
        <p>This creates a new audited operation. It never erases the original execution evidence.</p>
        <div class="confirm-summary">
          Target: ${affectedObject}<br />
          Original execution: ${execution.execution_id}<br />
          Current operation: ${plan.actions?.[0]?.action_type ?? "\u2014"}<br />
          Rollback operation: ${rollbackStep?.action_type ?? "restore exact prior state"}<br />
          Verification: ${plan.rollback_plan?.verification ?? "Verify the prior state was restored"}
        </div>
      </hamie-dialog>
    `;
  }
};
if (!customElements.get("hamie-view-remediation")) {
  customElements.define("hamie-view-remediation", HamieViewRemediation);
}

// hamie/frontend/components/hamie-gauge.js
var RADIUS2 = 54;
var CIRCUMFERENCE2 = 2 * Math.PI * RADIUS2;
var TRACK = CIRCUMFERENCE2 * 0.75;
var HamieGauge = class extends i4 {
  static properties = {
    score: { type: Number }
  };
  static styles = i`
    :host {
      display: block;
      width: 144px;
      height: 144px;
      position: relative;
    }
    svg {
      transform: rotate(-225deg);
    }
    .label {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
    }
    .score {
      font-size: var(--hamie-text-display);
      font-weight: var(--hamie-weight-medium);
      line-height: 1;
      letter-spacing: -0.01em;
      color: var(--hamie-text-primary);
    }
    .of {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      margin-top: var(--hamie-space-1-5);
    }
  `;
  _color(score) {
    if (score >= 90) return "var(--hamie-status-healthy)";
    if (score >= 70) return "var(--hamie-status-warning)";
    return "var(--hamie-status-critical)";
  }
  render() {
    const hasScore = this.score !== null && this.score !== void 0;
    const score = hasScore ? Math.max(0, Math.min(100, this.score)) : 0;
    const fill = hasScore ? score / 100 * TRACK : 0;
    const color = hasScore ? this._color(score) : "var(--hamie-border-hairline)";
    return b2`
      ${w`
        <svg width="144" height="144" viewBox="0 0 144 144">
          <circle cx="72" cy="72" r=${RADIUS2} fill="none" stroke="var(--hamie-border-hairline)"
            stroke-width="9" stroke-linecap="round" stroke-dasharray="${TRACK} ${CIRCUMFERENCE2}" />
          <circle cx="72" cy="72" r=${RADIUS2} fill="none" stroke=${color}
            stroke-width="9" stroke-linecap="round" stroke-dasharray="${fill} ${CIRCUMFERENCE2}"
            style="transition: stroke-dasharray var(--hamie-motion-slow) var(--hamie-motion-ease)" />
        </svg>
      `}
      <div class="label">
        <span class="score">${hasScore ? score : "\u2014"}</span>
        <span class="of">${hasScore ? "/ 100" : "no data yet"}</span>
      </div>
    `;
  }
};
if (!customElements.get("hamie-gauge")) {
  customElements.define("hamie-gauge", HamieGauge);
}

// hamie/frontend/components/shared-styles.js
var iconBadgeStyles = i`
  .icon-badge {
    width: 28px;
    height: 28px;
    border-radius: var(--hamie-radius-md);
    background: var(--hamie-surface-raised);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  .icon-badge ha-icon {
    --mdc-icon-size: 14px;
    color: var(--hamie-text-secondary);
  }
`;

// hamie/frontend/components/hamie-metric.js
var HamieMetric = class extends i4 {
  static properties = {
    label: { type: String },
    value: { type: String },
    sub: { type: String },
    icon: { type: String },
    // mdi:* icon name
    color: { type: String }
    // CSS color value for the value text; defaults to primary text
  };
  static styles = [
    iconBadgeStyles,
    i`
      :host {
        display: block;
      }
      .row {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: var(--hamie-space-3);
      }
      .label {
        margin: 0;
        font-size: var(--hamie-text-caption);
        font-weight: var(--hamie-weight-medium);
        text-transform: uppercase;
        letter-spacing: var(--hamie-tracking-label);
        color: var(--hamie-text-secondary);
      }
      .value {
        margin: var(--hamie-space-1-5) 0 0;
        font-size: var(--hamie-text-metric);
        font-weight: var(--hamie-weight-medium);
        line-height: 1;
        letter-spacing: -0.01em;
      }
      .sub {
        margin: var(--hamie-space-1-5) 0 0;
        font-size: var(--hamie-text-micro);
        color: var(--hamie-text-secondary);
        line-height: 1.4;
      }
      .icon-badge {
        flex-shrink: 0;
      }
    `
  ];
  render() {
    return b2`
      <hamie-card padding="md">
        <div class="row">
          <div>
            <p class="label">${this.label}</p>
            <p class="value" style=${this.color ? `color: ${this.color}` : ""}>${this.value}</p>
            ${this.sub ? b2`<p class="sub">${this.sub}</p>` : null}
          </div>
          ${this.icon ? b2`<div class="icon-badge"><ha-icon icon=${this.icon}></ha-icon></div>` : null}
        </div>
      </hamie-card>
    `;
  }
};
if (!customElements.get("hamie-metric")) {
  customElements.define("hamie-metric", HamieMetric);
}

// node_modules/lit-html/directive.js
var t3 = { ATTRIBUTE: 1, CHILD: 2, PROPERTY: 3, BOOLEAN_ATTRIBUTE: 4, EVENT: 5, ELEMENT: 6 };
var e4 = (t5) => (...e6) => ({ _$litDirective$: t5, values: e6 });
var i5 = class {
  constructor(t5) {
  }
  get _$AU() {
    return this._$AM._$AU;
  }
  _$AT(t5, e6, i7) {
    this._$Ct = t5, this._$AM = e6, this._$Ci = i7;
  }
  _$AS(t5, e6) {
    return this.update(t5, e6);
  }
  update(t5, e6) {
    return this.render(...e6);
  }
};

// node_modules/lit-html/directive-helpers.js
var { I: t4 } = j;
var i6 = (o7) => o7;
var r4 = (o7) => void 0 === o7.strings;
var s4 = () => document.createComment("");
var v2 = (o7, n6, e6) => {
  const l3 = o7._$AA.parentNode, d3 = void 0 === n6 ? o7._$AB : n6._$AA;
  if (void 0 === e6) {
    const i7 = l3.insertBefore(s4(), d3), n7 = l3.insertBefore(s4(), d3);
    e6 = new t4(i7, n7, o7, o7.options);
  } else {
    const t5 = e6._$AB.nextSibling, n7 = e6._$AM, c6 = n7 !== o7;
    if (c6) {
      let t6;
      e6._$AQ?.(o7), e6._$AM = o7, void 0 !== e6._$AP && (t6 = o7._$AU) !== n7._$AU && e6._$AP(t6);
    }
    if (t5 !== d3 || c6) {
      let o8 = e6._$AA;
      for (; o8 !== t5; ) {
        const t6 = i6(o8).nextSibling;
        i6(l3).insertBefore(o8, d3), o8 = t6;
      }
    }
  }
  return e6;
};
var u3 = (o7, t5, i7 = o7) => (o7._$AI(t5, i7), o7);
var m2 = {};
var p3 = (o7, t5 = m2) => o7._$AH = t5;
var M2 = (o7) => o7._$AH;
var h3 = (o7) => {
  o7._$AR(), o7._$AA.remove();
};

// node_modules/lit-html/directives/repeat.js
var u4 = (e6, s6, t5) => {
  const r6 = /* @__PURE__ */ new Map();
  for (let l3 = s6; l3 <= t5; l3++) r6.set(e6[l3], l3);
  return r6;
};
var c4 = e4(class extends i5 {
  constructor(e6) {
    if (super(e6), e6.type !== t3.CHILD) throw Error("repeat() can only be used in text expressions");
  }
  dt(e6, s6, t5) {
    let r6;
    void 0 === t5 ? t5 = s6 : void 0 !== s6 && (r6 = s6);
    const l3 = [], o7 = [];
    let i7 = 0;
    for (const s7 of e6) l3[i7] = r6 ? r6(s7, i7) : i7, o7[i7] = t5(s7, i7), i7++;
    return { values: o7, keys: l3 };
  }
  render(e6, s6, t5) {
    return this.dt(e6, s6, t5).values;
  }
  update(s6, [t5, r6, c6]) {
    const d3 = M2(s6), { values: p4, keys: a3 } = this.dt(t5, r6, c6);
    if (!Array.isArray(d3)) return this.ut = a3, p4;
    const h6 = this.ut ??= [], v3 = [];
    let m3, y3, x2 = 0, j2 = d3.length - 1, k2 = 0, w2 = p4.length - 1;
    for (; x2 <= j2 && k2 <= w2; ) if (null === d3[x2]) x2++;
    else if (null === d3[j2]) j2--;
    else if (h6[x2] === a3[k2]) v3[k2] = u3(d3[x2], p4[k2]), x2++, k2++;
    else if (h6[j2] === a3[w2]) v3[w2] = u3(d3[j2], p4[w2]), j2--, w2--;
    else if (h6[x2] === a3[w2]) v3[w2] = u3(d3[x2], p4[w2]), v2(s6, v3[w2 + 1], d3[x2]), x2++, w2--;
    else if (h6[j2] === a3[k2]) v3[k2] = u3(d3[j2], p4[k2]), v2(s6, d3[x2], d3[j2]), j2--, k2++;
    else if (void 0 === m3 && (m3 = u4(a3, k2, w2), y3 = u4(h6, x2, j2)), m3.has(h6[x2])) if (m3.has(h6[j2])) {
      const e6 = y3.get(a3[k2]), t6 = void 0 !== e6 ? d3[e6] : null;
      if (null === t6) {
        const e7 = v2(s6, d3[x2]);
        u3(e7, p4[k2]), v3[k2] = e7;
      } else v3[k2] = u3(t6, p4[k2]), v2(s6, d3[x2], t6), d3[e6] = null;
      k2++;
    } else h3(d3[j2]), j2--;
    else h3(d3[x2]), x2++;
    for (; k2 <= w2; ) {
      const e6 = v2(s6, v3[w2 + 1]);
      u3(e6, p4[k2]), v3[k2++] = e6;
    }
    for (; x2 <= j2; ) {
      const e6 = d3[x2++];
      null !== e6 && h3(e6);
    }
    return this.ut = a3, p3(s6, v3), E;
  }
});

// hamie/frontend/components/hamie-table.js
var HamieTable = class extends i4 {
  static properties = {
    columns: { type: Array },
    rows: { type: Array }
    // [{ id, cells: [...] }]
  };
  static styles = i`
    :host {
      display: block;
    }
    .scroll {
      overflow-x: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
    }
    thead tr {
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    th {
      padding: var(--hamie-space-2-5) var(--hamie-space-4);
      text-align: left;
      font-size: var(--hamie-text-caption);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-text-secondary);
      white-space: nowrap;
    }
    tbody tr {
      border-bottom: 1px solid var(--hamie-surface-raised);
      transition: background-color var(--hamie-motion-fast) var(--hamie-motion-ease);
    }
    tbody tr:last-child {
      border-bottom: none;
    }
    tbody tr:hover {
      background: var(--hamie-surface-hover);
    }
    td {
      padding: var(--hamie-space-2-5) var(--hamie-space-4);
      font-size: var(--hamie-text-small);
      white-space: nowrap;
    }
  `;
  render() {
    const rows = this.rows || [];
    if (rows.length === 0) {
      return b2`<slot name="empty"></slot>`;
    }
    return b2`
      <div class="scroll">
        <table>
          <thead>
            <tr>
              ${(this.columns || []).map((col) => b2`<th>${col}</th>`)}
            </tr>
          </thead>
          <tbody>
            ${c4(
      rows,
      (row) => row.id,
      (row) => b2`<tr>${row.cells.map((cell) => b2`<td>${cell}</td>`)}</tr>`
    )}
          </tbody>
        </table>
      </div>
    `;
  }
};
if (!customElements.get("hamie-table")) {
  customElements.define("hamie-table", HamieTable);
}

// hamie/frontend/components/hamie-system-card.js
var STATE_TOKEN = {
  healthy: "healthy",
  degraded: "warning",
  offline: "critical",
  needs_review: "critical",
  unknown: "unknown"
};
var STATE_LABEL = {
  healthy: "Healthy",
  degraded: "Degraded",
  offline: "Offline",
  needs_review: "Needs review",
  unknown: "Unknown"
};
var HamieSystemCard = class extends i4 {
  static properties = {
    name: { type: String },
    icon: { type: String },
    state: { type: String },
    // "healthy" | "degraded" | "offline" | "needs_review" | "unknown"
    detail: { type: String },
    // one short line, e.g. "2 critical · 5 warning"
    interactive: { type: Boolean, reflect: true }
  };
  static styles = i`
    :host {
      display: block;
    }
    .card {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-3);
      width: 100%;
      box-sizing: border-box;
      padding: var(--hamie-space-3) var(--hamie-space-4);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-lg);
      background: var(--hamie-surface-card);
      text-align: left;
      font: inherit;
      color: inherit;
    }
    :host([interactive]) .card {
      cursor: pointer;
    }
    :host([interactive]) .card:hover {
      border-color: var(--hamie-border-normal);
      background: var(--hamie-surface-hover);
    }
    .card:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: -2px;
    }
    .icon-badge {
      flex-shrink: 0;
      width: 36px;
      height: 36px;
      border-radius: var(--hamie-radius-md);
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .icon-badge ha-icon {
      --mdc-icon-size: 18px;
    }
    .body {
      flex: 1;
      min-width: 0;
    }
    .name {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .detail {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .state-chip {
      flex-shrink: 0;
      display: inline-flex;
      align-items: center;
      gap: var(--hamie-space-1-5);
      padding: var(--hamie-space-half) var(--hamie-space-2);
      border-radius: var(--hamie-radius-pill);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
    }
    .dot {
      width: 6px;
      height: 6px;
      border-radius: var(--hamie-radius-circle);
      flex-shrink: 0;
    }
  `;
  _onClick() {
    if (!this.interactive) return;
    this.dispatchEvent(new CustomEvent("hamie-system-click", { bubbles: true, composed: true }));
  }
  render() {
    const state = this.state || "unknown";
    const token = STATE_TOKEN[state] || "unknown";
    const inner = b2`
      <span class="icon-badge" style="background: var(--hamie-status-${token}-fill)">
        <ha-icon icon=${this.icon || "mdi:cube-outline"} style="color: var(--hamie-status-${token})"></ha-icon>
      </span>
      <span class="body">
        <p class="name">${this.name}</p>
        ${this.detail ? b2`<p class="detail">${this.detail}</p>` : null}
      </span>
      <span class="state-chip" style="background: var(--hamie-status-${token}-fill); color: var(--hamie-status-${token})">
        <span class="dot" style="background: var(--hamie-status-${token})"></span>
        ${STATE_LABEL[state] || state}
      </span>
    `;
    return this.interactive ? b2`<button type="button" class="card" @click=${this._onClick}>${inner}</button>` : b2`<div class="card">${inner}</div>`;
  }
};
if (!customElements.get("hamie-system-card")) {
  customElements.define("hamie-system-card", HamieSystemCard);
}

// hamie/frontend/views/hamie-view-health.js
var CONNECTOR_ICON2 = {
  ollama: "mdi:brain",
  n8n: "mdi:sitemap-outline",
  mcp: "mdi:server-network-outline",
  hkg: "mdi:graph-outline"
};
var CONNECTOR_STATE = { healthy: "healthy", degraded: "degraded", error: "offline", disabled: "unknown", unknown: "unknown" };
var HamieViewHealth = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _overview: { state: true },
    _findings: { state: true },
    _findingsTotal: { state: true },
    _connectors: { state: true },
    _error: { state: true },
    _refreshError: { state: true },
    // scan-refresh-only failure; keeps existing data visible
    _scanning: { state: true }
  };
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .refresh-error {
      margin-bottom: var(--hamie-space-4);
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
      font-size: var(--hamie-text-small);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .health-summary {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-4);
    }
    @media (max-width: 870px) {
      .health-summary {
        grid-template-columns: repeat(2, 1fr);
      }
    }
    .content-grid {
      display: grid;
      grid-template-columns: 1fr 2fr;
      gap: var(--hamie-space-4);
      margin-bottom: var(--hamie-space-5);
    }
    .system-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-5);
    }
    @media (max-width: 870px) {
      .content-grid {
        grid-template-columns: 1fr;
      }
    }
    .gauge-card {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: var(--hamie-space-3);
      text-align: center;
    }
    .scanned {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .breakdown-row {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-2) 0;
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .breakdown-row:last-child {
      border-bottom: none;
    }
    .breakdown-name {
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      width: 140px;
      flex-shrink: 0;
      text-transform: capitalize;
    }
    .breakdown-count {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      flex: 1;
    }
    ha-icon {
      --mdc-icon-size: 14px;
      color: var(--hamie-text-secondary);
      flex-shrink: 0;
    }
  `;
  connectedCallback() {
    super.connectedCallback();
    this._load();
  }
  async _load() {
    if (!this.hass) return;
    try {
      const [overview, findings, connectors] = await Promise.all([
        this.hass.callWS({ type: "hamie/explorer/overview" }),
        this.hass.callWS({
          type: "hamie/explorer/findings",
          search: "",
          filters: { lifecycle: "open" },
          sort: "priority",
          offset: 0,
          // Server hard-caps this at 100 (domain/intelligence.py
          // MAX_PAGE_SIZE) -- sending more always raises ValueError.
          limit: 100
        }),
        this.hass.callWS({ type: "hamie/connectors/status" }).catch(() => [])
      ]);
      this._overview = overview;
      this._findings = findings.items;
      this._findingsTotal = findings.total;
      this._connectors = connectors;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Systems data is temporarily unavailable.");
    }
  }
  // No open findings -> healthy; only warnings -> degraded; any critical
  // -> needs_review; no scan completed yet -> unknown. See the module
  // docstring for why this never derives "offline".
  _systemState(groupItems) {
    if (!this._overview?.last_scan) return "unknown";
    if (groupItems.some((item) => item.severity === "critical")) return "needs_review";
    if (groupItems.some((item) => item.severity === "warning")) return "degraded";
    return "healthy";
  }
  async _onRefresh() {
    if (!this.hass) return;
    this._scanning = true;
    this._refreshError = null;
    try {
      await this.hass.callService("hamie", "scan", {});
      await this._load();
    } catch (err) {
      const message = friendlyError(err, "The scan could not be completed.");
      if (this._overview && this._findings) {
        this._refreshError = message;
      } else {
        this._error = message;
      }
    } finally {
      this._scanning = false;
    }
  }
  render() {
    if (this._error) {
      return b2`<hamie-empty tone="unavailable" heading="House Health data is unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._overview || !this._findings) {
      return b2`<hamie-loading .lines=${4}></hamie-loading>`;
    }
    const health = this._overview.availability_health;
    const hasHealth = health !== null && health !== void 0;
    const operational = this._overview.operational_health;
    const hasOperational = operational !== null && operational !== void 0;
    const tone = !hasOperational ? "unknown" : operational >= 90 ? "healthy" : operational >= 70 ? "warning" : "critical";
    const toneLabel = !hasOperational ? "Not scanned yet" : operational >= 90 ? "All systems nominal" : operational >= 70 ? "Needs attention" : "Critical issues detected";
    const breakdown = groupFindingsBy(this._findings, "category");
    const truncated = this._findingsTotal > this._findings.length;
    const integrationGroups = /* @__PURE__ */ new Map();
    for (const item of this._findings) {
      const key = item.integration || "Unknown";
      if (!integrationGroups.has(key)) integrationGroups.set(key, []);
      integrationGroups.get(key).push(item);
    }
    const systemCards = [...integrationGroups.entries()].map(([name, items]) => ({
      name,
      state: this._systemState(items),
      detail: `${items.length} open finding${items.length === 1 ? "" : "s"}`
    })).sort((a3, b3) => a3.name.localeCompare(b3.name));
    const repairable = this._findings.filter((item) => item.repairability === "Potentially safe to disable").length;
    const advisoryOnly = this._findings.filter((item) => item.repairability !== "Potentially safe to disable").length;
    const rows = this._findings.map((item) => {
      const status = findingStatusToken(item);
      return {
        id: item.finding_id,
        cells: [
          b2`<hamie-status variant="severity" status=${item.severity}></hamie-status>`,
          b2`<span style="font-family: var(--hamie-font-code); font-size: var(--hamie-text-micro); color: var(--hamie-text-secondary)">${item.entity_id}</span>`,
          b2`${item.recommendation}`,
          b2`${item.category}`,
          b2`<span style="font-family: var(--hamie-font-code); font-size: var(--hamie-text-micro); color: var(--hamie-text-secondary)">${relativeTime(item.first_seen)}</span>`,
          b2`<hamie-status status=${status.status} label=${status.label}></hamie-status>`
        ]
      };
    });
    return b2`
      <hamie-page-header heading="Systems" subtitle="Real health states by integration and by connector -- continuous monitoring across all home systems">
        <div slot="actions">
          <hamie-button variant="secondary" size="sm" ?disabled=${this._scanning} @click=${this._onRefresh}>
            <ha-icon icon="mdi:refresh"></ha-icon> ${this._scanning ? "Scanning\u2026" : "Refresh"}
          </hamie-button>
        </div>
      </hamie-page-header>

      ${this._refreshError ? b2`
            <div class="refresh-error" role="alert">
              <span>Latest scan failed: ${this._refreshError} Showing results from ${this._overview.last_scan ? relativeTime(this._overview.last_scan) : "the last successful scan"}.</span>
              <hamie-button variant="ghost" size="xs" aria-label="Dismiss" @click=${() => this._refreshError = null}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          ` : null}

      <div class="health-summary">
        <hamie-metric
          label="Current risks"
          value=${(this._overview.critical_findings || 0) + (this._overview.warning_findings || 0)}
          sub="Critical and warning findings"
          icon="mdi:alert-outline"
        ></hamie-metric>
        <hamie-metric
          label="Root causes"
          value=${this._overview.root_cause_groups ?? 0}
          sub="Evidence-derived groups"
          icon="mdi:family-tree"
        ></hamie-metric>
        <hamie-metric
          label="Changed since scan"
          value=${(this._overview.new_findings || 0) + (this._overview.resolved_findings || 0)}
          sub="${this._overview.new_findings || 0} new · ${this._overview.resolved_findings || 0} resolved"
          icon="mdi:swap-vertical"
        ></hamie-metric>
        <hamie-metric
          label="Repairability"
          value=${repairable}
          sub="${advisoryOnly} advisory or needs evidence"
          icon="mdi:wrench-outline"
        ></hamie-metric>
      </div>

      <div class="content-grid">
        <hamie-card padding="md">
          <div class="gauge-card">
            <hamie-gauge .score=${hasOperational ? operational : health}></hamie-gauge>
            <hamie-status status=${tone} label=${toneLabel}></hamie-status>
            <p class="scanned">
              ${this._overview.last_scan ? `Scanned ${relativeTime(this._overview.last_scan)}` : "No scan yet"}
            </p>
          </div>
        </hamie-card>

        <hamie-card padding="md">
          <hamie-section heading="Findings by category" description="Open findings grouped by analyzer category"></hamie-section>
          ${breakdown.length === 0 ? b2`<hamie-empty tone="positive" heading="No open findings"></hamie-empty>` : breakdown.map(
      (group) => b2`
                  <div class="breakdown-row">
                    <ha-icon icon="mdi:shape-outline"></ha-icon>
                    <span class="breakdown-name">${group.key}</span>
                    <span class="breakdown-count">${group.count} open finding${group.count === 1 ? "" : "s"}</span>
                    <hamie-status status=${group.status}></hamie-status>
                  </div>
                `
    )}
        </hamie-card>
      </div>

      <hamie-section heading="By integration" description="Real health state derived from each integration's own open findings"></hamie-section>
      ${systemCards.length === 0 ? b2`<hamie-empty tone="positive" heading="No open findings in any integration"></hamie-empty>` : b2`
            <div class="system-grid">
              ${systemCards.map((card) => b2`<hamie-system-card name=${card.name} icon="mdi:puzzle-outline" state=${card.state} detail=${card.detail}></hamie-system-card>`)}
            </div>
          `}

      ${this._connectors?.length ? b2`
            <hamie-section heading="By connector" description="HAMIE's own outbound connectors -- reachability, not finding counts"></hamie-section>
            <div class="system-grid">
              ${this._connectors.map((connector) => {
      const state = connector.enabled ? CONNECTOR_STATE[connector.status] || "unknown" : "unknown";
      const detail = connector.enabled ? `${connector.status}${connector.latency_ms != null ? ` \xB7 ${connector.latency_ms} ms` : ""}` : "Disabled";
      return b2`
                  <hamie-system-card
                    name=${connector.connector_id}
                    icon=${CONNECTOR_ICON2[connector.connector_id] || "mdi:swap-horizontal"}
                    state=${state}
                    detail=${detail}
                  ></hamie-system-card>
                `;
    })}
            </div>
          ` : null}

      <hamie-card padding="none">
        <div style="padding: var(--hamie-space-3) var(--hamie-space-4); border-bottom: 1px solid var(--hamie-border-hairline); font-size: var(--hamie-text-small); font-weight: var(--hamie-weight-medium); color: var(--hamie-text-primary)">
          Active findings
        </div>
        <hamie-table .columns=${["Severity", "Entity", "Issue", "Category", "Detected", "Status"]} .rows=${rows}>
          <div slot="empty" style="padding: var(--hamie-space-8) 0">
            <hamie-empty tone="positive" heading="No active findings"></hamie-empty>
          </div>
        </hamie-table>
        ${truncated ? b2`<div style="padding: var(--hamie-space-2) var(--hamie-space-4); font-size: var(--hamie-text-micro); color: var(--hamie-text-secondary); border-top: 1px solid var(--hamie-border-hairline)">
              Showing ${this._findings.length} of ${this._findingsTotal} open findings — see the Findings screen for the full list.
            </div>` : null}
      </hamie-card>
    `;
  }
};
if (!customElements.get("hamie-view-health")) {
  customElements.define("hamie-view-health", HamieViewHealth);
}

// hamie/frontend/views/hamie-view-intelligence.js
var HamieViewIntelligence = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _recommendations: { state: true },
    _error: { state: true },
    _analyzeError: { state: true },
    // "Analyze Now"-only failure; keeps existing data visible
    _analyzing: { state: true },
    _coverage: { state: true }
    // eligible/selected/skipped accounting from the last analysis
  };
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .analyze-error {
      margin-bottom: var(--hamie-space-4);
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
      font-size: var(--hamie-text-small);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      margin-bottom: var(--hamie-space-5);
    }
    h1 {
      margin: 0;
      font-size: var(--hamie-text-base);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .subtitle {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-5);
      max-width: 40rem;
    }
    @media (max-width: 600px) {
      .metrics {
        grid-template-columns: 1fr;
      }
    }
    .insight-row {
      display: flex;
      align-items: flex-start;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-3) 0;
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .insight-row:last-child {
      border-bottom: none;
    }
    .insight-body {
      flex: 1;
      min-width: 0;
    }
    .insight-title {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .insight-meta {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-1);
    }
    .insight-confidence {
      font-size: var(--hamie-text-caption);
      font-family: var(--hamie-font-code);
      color: var(--hamie-text-secondary);
      background: var(--hamie-surface-raised);
      padding: 1px var(--hamie-space-1-5);
      border-radius: var(--hamie-radius-sm);
    }
    .insight-text {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
    .footer-link {
      margin-top: var(--hamie-space-3);
    }
  `;
  connectedCallback() {
    super.connectedCallback();
    this._load();
  }
  async _load() {
    if (!this.hass) return;
    try {
      const [config, recommendations, overview] = await Promise.all([
        // schema_version is required (presentation/api.py) -- 2 is the
        // real current schema (configuration.py
        // CONFIGURATION_SCHEMA_VERSION).
        this.hass.callWS({ type: "hamie/configuration/get", schema_version: 2 }),
        this.hass.callWS({ type: "hamie/recommendations/list", offset: 0, limit: 25 }),
        this.hass.callWS({ type: "hamie/explorer/overview" })
      ]);
      this._config = config.sections?.ollama?.values || {};
      this._recommendations = recommendations.items.filter((item) => item.review_state === "new" && !item.stale);
      this._coverage = overview.ai_last_coverage || null;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Intelligence data is temporarily unavailable.");
    }
  }
  async _onAnalyzeNow() {
    if (!this.hass) return;
    this._analyzing = true;
    this._analyzeError = null;
    try {
      const result = await this.hass.callWS({ type: "hamie/ai/analyze" });
      this._coverage = result.coverage || null;
      await this._load();
    } catch (err) {
      const message = friendlyError(err, "There's nothing for HAMIE to analyze right now.");
      if (this._config && this._recommendations) {
        this._analyzeError = message;
      } else {
        this._error = message;
      }
    } finally {
      this._analyzing = false;
    }
  }
  _navigateToRecommendations() {
    this.dispatchEvent(new CustomEvent("hamie-navigate", { detail: { id: "recommendations" }, bubbles: true, composed: true }));
  }
  render() {
    if (this._error) {
      return b2`<hamie-empty tone="unavailable" heading="Intelligence data is unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._config || !this._recommendations) {
      return b2`<hamie-loading .lines=${4}></hamie-loading>`;
    }
    const method = this._config.ai_connection_method || "direct";
    const engineReady = method === "ha_ai_task" ? !!this._config.ai_task_entity_id && !!this.hass?.states?.[this._config.ai_task_entity_id] : !!this._config.ollama_enabled;
    const thirtyDaysAgo = Date.now() - 30 * 24 * 3600 * 1e3;
    const recentCount = this._recommendations.filter((item) => new Date(item.generated_at).getTime() >= thirtyDaysAgo).length;
    return b2`
      <div class="header">
        <div>
          <h1>Intelligence</h1>
          <p class="subtitle">HAMIE AI engine — pattern detection and predictive maintenance</p>
        </div>
        <div class="header-actions">
          <hamie-status status=${engineReady ? "running" : "offline"} label=${engineReady ? "Engine active" : "Not configured"}></hamie-status>
          <hamie-button variant="secondary" size="sm" ?disabled=${this._analyzing || !engineReady} @click=${this._onAnalyzeNow}>
            <ha-icon icon="mdi:creation"></ha-icon> ${this._analyzing ? "Analyzing\u2026" : "Analyze now"}
          </hamie-button>
        </div>
      </div>

      ${this._analyzeError ? b2`
            <div class="analyze-error" role="alert">
              <span>${this._analyzeError}</span>
              <hamie-button variant="ghost" size="xs" aria-label="Dismiss" @click=${() => this._analyzeError = null}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          ` : null}

      <div class="metrics">
        <hamie-metric
          label="Coverage"
          value=${this._coverage?.coverage || "Not analyzed"}
          sub=${this._coverage ? `${this._coverage.groups_analyzed} of ${this._coverage.root_cause_groups_detected} root-cause groups` : "Run analysis to measure coverage"}
          icon="mdi:chart-donut"
        ></hamie-metric>
        <hamie-metric
          label="Advisory insights"
          value=${this._recommendations.length}
          sub="${recentCount} in the last 30 days"
          icon="mdi:database-outline"
        ></hamie-metric>
      </div>

      ${this._coverage ? b2`
            <p class="subtitle" style="margin-bottom: var(--hamie-space-4)">
              ${this._coverage.total_findings} findings detected ·
              ${this._coverage.selected_total} selected ·
              ${this._coverage.groups_analyzed} root-cause groups analyzed ·
              ${this._coverage.skipped_total} deferred ·
              Coverage: ${this._coverage.coverage}. ${this._coverage.selection_reason}
            </p>
          ` : null}

      <div>
        <hamie-section heading="Recent insights" description="Generated from HAMIE's advisory analysis"></hamie-section>
        <hamie-card padding="md">
          ${this._recommendations.length === 0 ? b2`<hamie-empty tone="neutral" heading="No insights yet"></hamie-empty>` : this._recommendations.slice(0, 8).map(
      (item) => b2`
                  <div class="insight-row">
                    <ha-icon icon="mdi:lightbulb-on-outline"></ha-icon>
                    <div class="insight-body">
                      <div class="insight-meta">
                        <p class="insight-title">${item.summary}</p>
                        <span class="insight-confidence">${item.confidence} confidence</span>
                      </div>
                      <p class="insight-text">${item.probable_causes?.[0] || ""}</p>
                    </div>
                  </div>
                `
    )}
          <div class="footer-link">
            <hamie-button variant="ghost" size="xs" @click=${this._navigateToRecommendations}>
              View all recommendations <ha-icon icon="mdi:arrow-right"></ha-icon>
            </hamie-button>
          </div>
        </hamie-card>
      </div>
    `;
  }
};
if (!customElements.get("hamie-view-intelligence")) {
  customElements.define("hamie-view-intelligence", HamieViewIntelligence);
}

// hamie/frontend/views/hamie-view-security.js
var HamieViewSecurity = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _page: { state: true },
    _error: { state: true }
  };
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    h2 { margin: 0; font-size: var(--hamie-text-small); color: var(--hamie-text-primary); }
    .meta {
      margin: var(--hamie-space-1) 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .summary {
      display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: var(--hamie-space-3); margin: var(--hamie-space-4) 0;
    }
    .metric { font-size: var(--hamie-text-metric); font-weight: var(--hamie-weight-bold); margin-top: var(--hamie-space-1); }
    .stack { display: grid; gap: var(--hamie-space-3); }
    .finding-head { display: flex; justify-content: space-between; gap: var(--hamie-space-3); }
    .decision-grid {
      display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--hamie-space-3); margin-top: var(--hamie-space-3);
    }
    .label {
      display: block; margin-bottom: 4px; text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label); font-size: var(--hamie-text-caption);
      color: var(--hamie-text-secondary);
    }
    p, li { font-size: var(--hamie-text-small); color: var(--hamie-text-secondary); line-height: 1.55; }
    ul, ol { margin: 4px 0 0; padding-left: 1.2rem; }
    .sources { margin-top: var(--hamie-space-4); }
    @media (max-width: 700px) {
      .summary, .decision-grid { grid-template-columns: 1fr; }
    }
  `;
  connectedCallback() {
    super.connectedCallback();
    this._load();
  }
  updated(changed) {
    if (changed.has("hass") && this.hass && !this._page) this._load();
  }
  async _load() {
    if (!this.hass) return;
    try {
      this._page = await this.hass.callWS({ type: "hamie/security/findings" });
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Security evidence is temporarily unavailable.");
    }
  }
  render() {
    if (this._error) {
      return b2`<hamie-empty tone="unavailable" heading="Security evidence is unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._page) return b2`<hamie-loading .lines=${4}></hamie-loading>`;
    const highRisk = this._page.items.filter((item) => item.risk === "high" || item.risk === "critical").length;
    const manualOnly = this._page.items.filter((item) => item.execution_capability !== "Proposal available").length;
    return b2`
      <hamie-page-header heading="Security" subtitle="Evidence-backed risks and decision-ready remediation state"></hamie-page-header>

      <div class="summary">
        <hamie-card padding="md"><span class="label">Open findings</span><div class="metric">${this._page.total}</div></hamie-card>
        <hamie-card padding="md"><span class="label">High risk</span><div class="metric">${highRisk}</div></hamie-card>
        <hamie-card padding="md"><span class="label">Manual only</span><div class="metric">${manualOnly}</div></hamie-card>
      </div>

      <div class="stack">
        ${this._page.items.length === 0 ? b2`<hamie-card padding="md"><hamie-empty
              tone="positive"
              heading="No supported security findings"
              description="HAMIE found no risks in the security evidence it can currently inspect. This is not a full host or Home Assistant security audit."
            ></hamie-empty></hamie-card>` : this._page.items.map((item) => b2`
              <hamie-card padding="md">
                <div class="finding-head">
                  <div>
                    <h2>${item.title}</h2>
                    <p class="meta">${item.affected_object} · ${item.exposure}</p>
                  </div>
                  <hamie-status status=${item.risk === "critical" ? "critical" : "warning"} label="${item.risk} risk"></hamie-status>
                </div>
                <div class="decision-grid">
                  <div>
                    <span class="label">Evidence</span>
                    <ul>${item.evidence.map((value) => b2`<li>${value}</li>`)}</ul>
                  </div>
                  <div>
                    <span class="label">Recommended action</span>
                    <p>${item.recommended_action}</p>
                    <p><strong>${item.execution_capability}</strong> · ${item.confidence} confidence</p>
                  </div>
                  <div>
                    <span class="label">Manual steps</span>
                    <ol>${item.manual_steps.map((value) => b2`<li>${value}</li>`)}</ol>
                  </div>
                  <div>
                    <span class="label">Verification plan</span>
                    <ol>${item.verification_plan.map((value) => b2`<li>${value}</li>`)}</ol>
                  </div>
                </div>
              </hamie-card>
            `)}
      </div>

      <hamie-card class="sources" padding="md">
        <h2>Evidence coverage</h2>
        <p>Checked: ${this._page.evidence_sources.join(", ")}.</p>
        <p>Not available: ${this._page.unavailable_sources.join(", ")}. HAMIE does not infer findings from these missing sources.</p>
      </hamie-card>
    `;
  }
};
if (!customElements.get("hamie-view-security")) {
  customElements.define("hamie-view-security", HamieViewSecurity);
}

// hamie/frontend/views/hamie-view-dependencies.js
var HamieViewDependencies = class extends i4 {
  static properties = {
    hass: { attribute: false },
    // Set by hamie-app.js when a Findings row's "View dependency graph"
    // or a Group's graph action navigates here.
    focusFindingId: { type: String },
    focusGroupId: { type: String },
    focusLabel: { type: String },
    _findings: { state: true },
    _total: { state: true },
    _error: { state: true },
    _scanning: { state: true },
    _graph: { state: true },
    _graphError: { state: true },
    // Real scan lifecycle (hamie/explorer/overview's scan_status/
    // coverage) -- distinguishes "genuinely no open findings" from "no
    // scan has ever completed" or "the latest scan failed with nothing
    // retained yet", the same real signal House Health/Findings use.
    _scanStatus: { state: true },
    _coverage: { state: true }
  };
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .subtitle {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-4);
    }
    @media (max-width: 870px) {
      .metrics {
        grid-template-columns: 1fr;
      }
    }
    .row {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-3);
      padding: var(--hamie-space-3) var(--hamie-space-4);
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .row:last-child {
      border-bottom: none;
    }
    .name {
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      flex: 1;
    }
    .count {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
    }
    .graph-section {
      margin-bottom: var(--hamie-space-4);
    }
    .graph-section h2 {
      margin: 0 0 var(--hamie-space-2);
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .node-list {
      margin: 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      line-height: 1.7;
    }
    .decision-grid {
      display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--hamie-space-3); margin-bottom: var(--hamie-space-4);
    }
    .decision-grid p, .decision-grid li, details {
      color: var(--hamie-text-secondary); font-size: var(--hamie-text-small);
      line-height: 1.55;
    }
    .decision-grid h2 { margin-bottom: var(--hamie-space-1); }
    details > summary {
      cursor: pointer; color: var(--hamie-accent); font-weight: var(--hamie-weight-medium);
      margin-bottom: var(--hamie-space-3);
    }
    @media (max-width: 700px) {
      .decision-grid { grid-template-columns: 1fr; }
    }
    .badges {
      display: flex;
      gap: var(--hamie-space-2);
      margin-bottom: var(--hamie-space-4);
    }
  `;
  connectedCallback() {
    super.connectedCallback();
    this._load();
  }
  async _load() {
    if (!this.hass) return;
    if (this.focusFindingId || this.focusGroupId) {
      await this._loadGraph();
      return;
    }
    try {
      const [result, overview] = await Promise.all([
        this.hass.callWS({
          type: "hamie/explorer/findings",
          search: "",
          filters: { lifecycle: "open" },
          sort: "priority",
          offset: 0,
          // Server hard-caps this at 100 (domain/intelligence.py
          // MAX_PAGE_SIZE) -- sending more always raises ValueError.
          limit: 100
        }),
        this.hass.callWS({ type: "hamie/explorer/overview" })
      ]);
      this._findings = result.items.filter((item) => item.integration);
      this._total = result.total;
      this._scanStatus = overview.scan_status;
      this._coverage = overview.coverage;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Dependency data is temporarily unavailable.");
    }
  }
  async _loadGraph() {
    try {
      const params = this.focusGroupId ? { group_id: this.focusGroupId } : { finding_id: this.focusFindingId };
      this._graph = await this.hass.callWS({ type: "hamie/explorer/dependencies", ...params });
      this._graphError = null;
    } catch (err) {
      this._graphError = friendlyError(err, "That dependency graph is unavailable.");
    }
  }
  _onBackToIntegrations() {
    this.focusFindingId = null;
    this.focusGroupId = null;
    this.focusLabel = null;
    this._graph = null;
    this._graphError = null;
    this._load();
  }
  async _onRefresh() {
    if (!this.hass) return;
    this._scanning = true;
    try {
      await this.hass.callService("hamie", "scan", {});
      await this._load();
    } catch (err) {
      this._error = friendlyError(err, "Dependency data is temporarily unavailable.");
    } finally {
      this._scanning = false;
    }
  }
  render() {
    if (this.focusFindingId || this.focusGroupId) {
      return this._renderGraph();
    }
    if (this._error) {
      return b2`<hamie-empty tone="unavailable" heading="Dependencies are unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._findings) {
      return b2`<hamie-loading .lines=${4}></hamie-loading>`;
    }
    const neverScanned = this._scanStatus === "never_run";
    const failedWithNothingRetained = this._scanStatus === "failed" && this._coverage === "unknown";
    if (neverScanned || failedWithNothingRetained) {
      return b2`
        <hamie-page-header heading="Dependencies" subtitle="Open findings grouped by integration">
          <div slot="actions">
            <hamie-button variant="secondary" size="sm" ?disabled=${this._scanning} @click=${this._onRefresh}>
              <ha-icon icon="mdi:refresh"></ha-icon> ${this._scanning ? "Scanning\u2026" : "Refresh"}
            </hamie-button>
          </div>
        </hamie-page-header>
        <hamie-empty
          tone=${neverScanned ? "neutral" : "unavailable"}
          heading=${neverScanned ? "No scan has completed yet" : "The latest scan failed"}
          description=${neverScanned ? "Run a scan to see integration dependencies here." : "No previous results are available yet. Run a scan to try again."}
        ></hamie-empty>
      `;
    }
    const breakdown = groupFindingsBy(this._findings, "integration");
    const healthyCount = breakdown.filter((g2) => g2.status === "info").length;
    const degradedCount = breakdown.length - healthyCount;
    return b2`
      <hamie-page-header
        heading="Dependencies"
        subtitle="${breakdown.length} integrations with open findings · ${degradedCount} need attention"
      >
        <div slot="actions">
          <hamie-button variant="secondary" size="sm" ?disabled=${this._scanning} @click=${this._onRefresh}>
            <ha-icon icon="mdi:refresh"></ha-icon> ${this._scanning ? "Scanning\u2026" : "Refresh"}
          </hamie-button>
        </div>
      </hamie-page-header>

      <div class="metrics">
        <hamie-metric label="Integrations affected" value=${breakdown.length} sub="With at least one open finding" icon="mdi:puzzle-outline"></hamie-metric>
        <hamie-metric label="Needs attention" value=${degradedCount} sub="Warning or critical findings" icon="mdi:alert-outline" color="var(--hamie-status-warning)"></hamie-metric>
        <hamie-metric label="Informational only" value=${healthyCount} sub="No warning/critical findings" icon="mdi:information-outline"></hamie-metric>
      </div>

      <hamie-card padding="none">
        ${breakdown.length === 0 ? b2`<hamie-empty tone="positive" heading="No integrations have open findings" description="Findings only report an integration when Home Assistant can determine one."></hamie-empty>` : breakdown.map(
      (group) => b2`
                <div class="row">
                  <span class="name">${group.key}</span>
                  <span class="count">${group.count} open finding${group.count === 1 ? "" : "s"}</span>
                  <hamie-status status=${group.status}></hamie-status>
                </div>
              `
    )}
      </hamie-card>
      ${this._total > this._findings.length ? b2`<p class="subtitle" style="margin-top: var(--hamie-space-2)">
            Showing findings for the ${this._findings.length} of ${this._total} open findings with a determinable integration.
          </p>` : null}
    `;
  }
  _renderGraph() {
    if (this._graphError) {
      return b2`
        <hamie-page-header heading="Dependency decision">
          <div slot="actions">
            <hamie-button variant="ghost" size="sm" @click=${this._onBackToIntegrations}>
              <ha-icon icon="mdi:arrow-left"></ha-icon> Back to integrations
            </hamie-button>
          </div>
        </hamie-page-header>
        <hamie-empty tone="unavailable" heading="Dependency evidence is unavailable" description=${this._graphError}></hamie-empty>
      `;
    }
    if (!this._graph) return b2`<hamie-loading .lines=${4}></hamie-loading>`;
    const decision = this._graph.decision || {};
    const edgeRows = this._graph.edges.map((edge, index) => ({
      id: `${edge.source_id}-${edge.target_id}-${index}`,
      cells: [edge.source_id, edge.relationship_type, edge.target_id, edge.confidence]
    }));
    return b2`
      <hamie-page-header heading="Dependency decision" subtitle="${decision.friendly_name || decision.target || "Selected target"}">
        <div slot="actions">
          <hamie-button variant="ghost" size="sm" @click=${this._onBackToIntegrations}>
            <ha-icon icon="mdi:arrow-left"></ha-icon> Back to integrations
          </hamie-button>
        </div>
      </hamie-page-header>

      <div class="badges">
        <hamie-status status=${this._graph.coverage === "complete" ? "healthy" : "warning"} label="Coverage: ${this._graph.coverage}"></hamie-status>
        <hamie-status status=${decision.safe_to_disable ? "healthy" : "critical"} label=${decision.recommendation || "Manual review required"}></hamie-status>
      </div>

      <div class="decision-grid">
        <hamie-card padding="md">
          <h2>Summary</h2>
          <p><strong>${decision.friendly_name || decision.target}</strong><br />
            ${decision.target}<br />
            Integration: ${decision.integration || "Unknown"} ·
            Config entry: ${decision.config_entry || "Unknown"} ·
            Device: ${decision.device || "Unknown"} ·
            Area: ${decision.area || "Unknown"}
          </p>
          <p>Direct references: ${decision.direct_references?.length || 0} ·
            Indirect references: ${decision.indirect_references?.length || 0} ·
            Unresolved sources: ${decision.unresolved_sources?.length || 0}</p>
          <p>Safe to inspect: ${String(decision.safe_to_inspect)} ·
            Safe to disable: ${String(decision.safe_to_disable)} ·
            Safe to modify: ${String(decision.safe_to_modify)}</p>
        </hamie-card>

        <hamie-card padding="md">
          <h2>Recommendation</h2>
          <p><strong>${decision.recommendation || "Manual review required"}</strong></p>
          <p>${decision.reason || "Dependency evidence is incomplete."}</p>
          <p><strong>Possible impact:</strong> ${decision.possible_impact || "Unknown until coverage is complete."}</p>
        </hamie-card>

        <hamie-card padding="md">
          <h2>Referenced by</h2>
          ${Object.keys(decision.referenced_by || {}).length ? Object.entries(decision.referenced_by).map(([category, values]) => b2`
                <p><strong>${category}</strong></p>
                <ul>${values.map((value) => b2`<li>${value}</li>`)}</ul>
              `) : b2`<p>No verified direct references were found. This does not prove modification is safe unless dependency coverage is complete.</p>`}
        </hamie-card>

        <hamie-card padding="md">
          <h2>Belongs to or supports</h2>
          ${decision.belongs_to_or_supports?.length ? b2`<ul>${decision.belongs_to_or_supports.map((value) => b2`<li>${value}</li>`)}</ul>` : b2`<p>No supporting relationship was observed.</p>`}
        </hamie-card>
      </div>

      <details>
        <summary>View technical graph</summary>
        <div class="graph-section">
          <h2>Nodes</h2>
          ${this._graph.nodes.length ? b2`<ul class="node-list">${this._graph.nodes.map((node) => b2`<li>${node.kind}: ${node.label}</li>`)}</ul>` : b2`<hamie-empty tone="neutral" heading="No graph nodes"></hamie-empty>`}
        </div>
        <div class="graph-section">
          <h2>Relationships</h2>
          <hamie-card padding="none">
            <hamie-table .columns=${["Source", "Relation", "Target", "Confidence"]} .rows=${edgeRows}>
              <div slot="empty" style="padding: var(--hamie-space-8) 0">
                <hamie-empty tone="neutral" heading="No relationships found"></hamie-empty>
              </div>
            </hamie-table>
          </hamie-card>
        </div>
      </details>
    `;
  }
};
if (!customElements.get("hamie-view-dependencies")) {
  customElements.define("hamie-view-dependencies", HamieViewDependencies);
}

// hamie/frontend/views/hamie-view-groups.js
var PAGE_SIZE4 = 25;
var ACTIONS = [
  { id: "acknowledge", label: "Acknowledge", icon: "mdi:check-circle-outline" },
  { id: "snooze", label: "Snooze", icon: "mdi:clock-outline" },
  { id: "retain", label: "Retain", icon: "mdi:shield-check-outline" },
  { id: "dismiss", label: "Dismiss", icon: "mdi:close-circle-outline" },
  { id: "suppress", label: "Suppress", icon: "mdi:eye-off-outline" }
];
var HamieViewGroups = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _groups: { state: true },
    _total: { state: true },
    _offset: { state: true },
    _search: { state: true },
    _error: { state: true },
    _actionError: { state: true },
    _busyGroupId: { state: true },
    _pending: { state: true },
    // { group, action, preview } once a preview succeeds with count > 0
    _reason: { state: true },
    // suppress-only: user-entered reason text
    _detailGroup: { state: true }
  };
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .action-error {
      margin-bottom: var(--hamie-space-3);
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
      font-size: var(--hamie-text-small);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .list {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-2-5);
    }
    .row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .title {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .reason {
      margin: 2px 0 0;
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
    }
    .stats {
      margin-top: var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .badges {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      flex-shrink: 0;
    }
    .priority-badge {
      font-size: var(--hamie-text-caption);
      font-family: var(--hamie-font-code);
      color: var(--hamie-text-secondary);
      background: var(--hamie-surface-raised);
      padding: 1px var(--hamie-space-1-5);
      border-radius: var(--hamie-radius-sm);
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1);
      margin-top: var(--hamie-space-2);
    }
    .dialog-reason {
      margin-top: var(--hamie-space-3);
    }
    .dialog-reason label {
      display: block;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      margin-bottom: var(--hamie-space-1);
    }
    .toolbar {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-3);
    }
    .search {
      width: 280px;
    }
    .pager {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--hamie-space-3) 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .detail-meta {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.8;
    }
    .detail-section {
      margin-top: var(--hamie-space-3);
    }
    .detail-section h3 {
      margin: 0 0 var(--hamie-space-1);
      font-size: var(--hamie-text-micro);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .detail-list {
      margin: 0;
      padding-left: 1.1em;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      line-height: 1.6;
    }
  `;
  constructor() {
    super();
    this._search = "";
    this._offset = 0;
  }
  connectedCallback() {
    super.connectedCallback();
    this._load();
  }
  async _load() {
    if (!this.hass) return;
    try {
      const result = await this.hass.callWS({
        type: "hamie/explorer/groups",
        search: this._search,
        offset: this._offset,
        limit: PAGE_SIZE4
      });
      this._groups = result.items;
      this._total = result.total;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Groups are temporarily unavailable.");
    }
  }
  _onSearchInput(event) {
    this._search = event.detail.value;
  }
  _onSearchApply() {
    this._offset = 0;
    this._load();
  }
  _nextPage() {
    this._offset += PAGE_SIZE4;
    this._load();
  }
  _previousPage() {
    this._offset = Math.max(0, this._offset - PAGE_SIZE4);
    this._load();
  }
  _onViewFindings(group) {
    this.dispatchEvent(
      new CustomEvent("hamie-navigate-findings-group", {
        detail: { groupId: group.group_id, groupTitle: group.title },
        bubbles: true,
        composed: true
      })
    );
  }
  _onViewDependencyGraph(group) {
    this._detailGroup = null;
    this.dispatchEvent(
      new CustomEvent("hamie-navigate-dependencies", { detail: { groupId: group.group_id }, bubbles: true, composed: true })
    );
  }
  _statusFor(group) {
    if (group.critical_count > 0) return "critical";
    if (group.warning_count > 0) return "warning";
    return "info";
  }
  async _onAction(group, action) {
    if (!this.hass || this._busyGroupId) return;
    this._actionError = null;
    this._busyGroupId = group.group_id;
    try {
      const preview = await this.hass.callWS({
        type: "hamie/group/preview",
        group_id: group.group_id,
        action
      });
      if (preview.count === 0) {
        this._actionError = `No eligible findings for "${ACTIONS.find((item) => item.id === action)?.label}" in "${group.title}".`;
        return;
      }
      this._reason = "";
      this._pending = { group, action, preview };
    } catch (err) {
      this._actionError = friendlyError(err, "That action could not be started.");
    } finally {
      this._busyGroupId = null;
    }
  }
  _cancelPending() {
    this._pending = null;
    this._reason = "";
  }
  async _confirmPending() {
    if (!this.hass || !this._pending) return;
    const { group, action, preview } = this._pending;
    this._busyGroupId = group.group_id;
    try {
      if (action === "suppress") {
        await this.hass.callWS({
          type: "hamie/group/suppress",
          preview,
          idempotency_token: idempotencyToken(),
          // Required by the server schema (vol.Required("reason")) --
          // the Confirm button stays disabled until this is non-empty,
          // so there is no silent default to fall back on here.
          reason: this._reason.trim()
        });
      } else {
        await this.hass.callWS({
          type: "hamie/group/apply",
          preview,
          idempotency_token: idempotencyToken()
        });
      }
      this._pending = null;
      this._reason = "";
      await this._load();
    } catch (err) {
      this._actionError = friendlyError(err, "That action could not be applied.");
    } finally {
      this._busyGroupId = null;
    }
  }
  render() {
    if (this._error) {
      return b2`<hamie-empty tone="unavailable" heading="Groups are unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._groups) {
      return b2`<hamie-loading .lines=${4}></hamie-loading>`;
    }
    return b2`
      <hamie-page-header
        heading="Groups"
        subtitle="${this._total ?? this._groups.length} deterministic finding group${(this._total ?? this._groups.length) === 1 ? "" : "s"}"
      ></hamie-page-header>

      ${this._actionError ? b2`
            <div class="action-error">
              <span>${this._actionError}</span>
              <hamie-button variant="ghost" size="xs" @click=${() => this._actionError = null}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          ` : null}

      <div class="toolbar">
        <hamie-input
          class="search"
          placeholder="Search groups…"
          icon="mdi:magnify"
          .value=${this._search}
          @hamie-input=${this._onSearchInput}
          @keydown=${(event) => event.key === "Enter" && this._onSearchApply()}
        ></hamie-input>
        <hamie-button variant="secondary" size="sm" @click=${this._onSearchApply}>Search</hamie-button>
      </div>

      ${this._groups.length === 0 ? b2`<hamie-card padding="md"><hamie-empty tone="positive" heading="No groups yet"></hamie-empty></hamie-card>` : b2`
            <div class="list">
              ${this._groups.map(
      (group) => b2`
                  <hamie-card padding="md">
                    <div class="row">
                      <div>
                        <p class="title">${group.title}</p>
                        <p class="reason">${groupingReasonLabel(group.grouping_reason)}</p>
                        <p class="stats">
                          ${group.open_count} open of ${group.member_count} finding${group.member_count === 1 ? "" : "s"} · ${group.warning_count} warning · ${group.critical_count} critical
                          · updated ${relativeTime(group.last_seen)}
                        </p>
                      </div>
                      <div class="badges">
                        <span class="priority-badge">priority ${group.priority}</span>
                        <hamie-status status=${group.coverage_state === "complete" ? "healthy" : "warning"} label="Coverage: ${group.coverage_state}"></hamie-status>
                        <hamie-status status=${this._statusFor(group)} label=${group.review_state}></hamie-status>
                      </div>
                    </div>
                    <div class="actions">
                      ${ACTIONS.map(
        (item) => b2`
                          <hamie-button
                            variant="ghost"
                            size="xs"
                            ?disabled=${this._busyGroupId === group.group_id}
                            @click=${() => this._onAction(group, item.id)}
                          >
                            <ha-icon icon=${item.icon}></ha-icon> ${item.label}
                          </hamie-button>
                        `
      )}
                      <hamie-button variant="secondary" size="xs" @click=${() => this._detailGroup = group}>Details</hamie-button>
                      <hamie-button variant="secondary" size="xs" @click=${() => this._onViewFindings(group)}>View Findings</hamie-button>
                    </div>
                  </hamie-card>
                `
    )}
            </div>
            <div class="pager">
              <hamie-button variant="ghost" size="xs" ?disabled=${this._offset === 0} @click=${this._previousPage}>Previous</hamie-button>
              <span>${this._total === 0 ? 0 : this._offset + 1}–${Math.min(this._offset + PAGE_SIZE4, this._total)} of ${this._total}</span>
              <hamie-button variant="ghost" size="xs" ?disabled=${this._offset + PAGE_SIZE4 >= this._total} @click=${this._nextPage}>Next</hamie-button>
            </div>
          `}

      ${this._detailGroup ? this._renderDetailDialog(this._detailGroup) : null}

      ${this._pending ? b2`
            <hamie-dialog
              open
              heading="${ACTIONS.find((item) => item.id === this._pending.action)?.label} findings?"
              cancel-label="Cancel"
              .confirmLabel=${ACTIONS.find((item) => item.id === this._pending.action)?.label || "Confirm"}
              .destructive=${["dismiss", "suppress"].includes(this._pending.action)}
              .busy=${!!this._busyGroupId}
              .errorMessage=${this._actionError || ""}
              .confirmDisabled=${this._pending.action === "suppress" && !this._reason?.trim()}
              .onConfirm=${() => this._confirmPending()}
              .onCancel=${() => this._cancelPending()}
            >
              <p>
                ${ACTIONS.find((item) => item.id === this._pending.action)?.label} exactly ${this._pending.preview.count}
                finding${this._pending.preview.count === 1 ? "" : "s"} in "${this._pending.group.title}".
                ${this._pending.action === "snooze" ? "They will be snoozed for exactly 24 hours." : ""}
                ${this._pending.action === "suppress" ? "They will be hidden from default views, not deleted." : ""}
                Home Assistant objects will not be changed.
              </p>
              ${this._pending.action === "suppress" ? b2`
                    <div class="dialog-reason">
                      <label for="suppress-reason">Reason (required)</label>
                      <hamie-input
                        id="suppress-reason"
                        placeholder="Why is this being suppressed?"
                        .value=${this._reason}
                        @hamie-input=${(event) => this._reason = event.detail.value}
                      ></hamie-input>
                    </div>
                  ` : null}
            </hamie-dialog>
          ` : null}
    `;
  }
  _renderDetailDialog(group) {
    return b2`
      <hamie-dialog open heading="${group.title}" @hamie-dialog-closed=${() => this._detailGroup = null}>
        <p>${groupingReasonLabel(group.grouping_reason)}</p>
        <div class="detail-section">
          <h3>Coverage &amp; review</h3>
          <p class="detail-meta">
            Coverage: ${group.coverage_state} · Review: ${group.review_state} · Suppression: ${group.suppression_state}<br />
            AI explanation: ${group.ai_explanation_state} · Confidence: ${group.confidence}<br />
            First seen: ${relativeTime(group.first_seen)} · Last seen: ${relativeTime(group.last_seen)}
          </p>
        </div>
        ${group.common_provider || group.common_dependency_root ? b2`
              <div class="detail-section">
                <h3>Common attribution</h3>
                <p class="detail-meta">
                  ${group.common_provider ? b2`Provider: ${group.common_provider}<br />` : null}
                  ${group.common_dependency_root ? b2`Dependency root: ${group.common_dependency_root}` : null}
                </p>
              </div>
            ` : null}
        ${group.representative_subjects?.length ? b2`
              <div class="detail-section">
                <h3>Representative subjects</h3>
                <ul class="detail-list">${group.representative_subjects.map((s6) => b2`<li>${s6}</li>`)}</ul>
              </div>
            ` : null}
        <div class="detail-section">
          <h3>Member findings (${group.member_count})</h3>
          <p class="detail-meta">Use "View Findings" below to inspect each one with a friendly name.</p>
          <hamie-disclosure label="Technical details">
            <ul class="detail-list">
              ${group.member_finding_ids.map((id) => b2`<li>${id}</li>`)}
            </ul>
            ${group.member_list_truncated ? b2`<p class="detail-meta">List truncated -- use View Findings for the full set.</p>` : null}
          </hamie-disclosure>
        </div>
        <div class="detail-section" style="display: flex; gap: var(--hamie-space-2);">
          <hamie-button variant="secondary" size="xs" @click=${() => this._onViewFindings(group)}>View Findings</hamie-button>
          <hamie-button variant="secondary" size="xs" @click=${() => this._onViewDependencyGraph(group)}>View dependency graph</hamie-button>
        </div>
        <hamie-button slot="primary-action" variant="secondary" size="sm" @click=${() => this._detailGroup = null}>
          Close
        </hamie-button>
      </hamie-dialog>
    `;
  }
};
if (!customElements.get("hamie-view-groups")) {
  customElements.define("hamie-view-groups", HamieViewGroups);
}

// hamie/frontend/components/hamie-provider-card.js
var STATUS_MAP = {
  healthy: "healthy",
  degraded: "warning",
  error: "critical",
  disabled: "offline",
  unknown: "unknown"
};
var HamieProviderCard = class extends i4 {
  static properties = {
    connectorId: { type: String },
    displayName: { type: String },
    icon: { type: String },
    enabled: { type: Boolean },
    status: { type: String },
    // ConnectorStatus value
    errorCode: { type: String },
    capabilityMode: { type: String },
    lastTested: { type: String },
    latencyMs: { type: Number },
    consecutiveFailures: { type: Number },
    _detailsOpen: { state: true }
  };
  static styles = [
    iconBadgeStyles,
    i`
    :host {
      display: block;
    }
    .row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .identity {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2-5);
      min-width: 0;
    }
    .icon-badge {
      flex-shrink: 0;
    }
    .name {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .mode {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .meta {
      margin-top: var(--hamie-space-3);
      display: flex;
      flex-wrap: wrap;
      gap: var(--hamie-space-1) var(--hamie-space-4);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .meta strong {
      color: var(--hamie-text-primary);
      font-weight: var(--hamie-weight-medium);
      font-family: var(--hamie-font-code);
    }
    .error {
      margin-top: var(--hamie-space-2);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-2);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-status-critical);
    }
    .error-details {
      margin-top: var(--hamie-space-1);
      font-size: var(--hamie-text-micro);
      font-family: var(--hamie-font-code);
      color: var(--hamie-text-secondary);
    }
    .actions {
      display: flex;
      gap: var(--hamie-space-2);
      margin-top: var(--hamie-space-3);
    }
  `
  ];
  _onTest() {
    this.dispatchEvent(
      new CustomEvent("hamie-provider-test", {
        detail: { connectorId: this.connectorId },
        bubbles: true,
        composed: true
      })
    );
  }
  _onConfigure() {
    this.dispatchEvent(
      new CustomEvent("hamie-provider-configure", {
        detail: { connectorId: this.connectorId },
        bubbles: true,
        composed: true
      })
    );
  }
  render() {
    const status = this.enabled ? this.status || "unknown" : "disabled";
    return b2`
      <hamie-card padding="md">
        <div class="row">
          <div class="identity">
            <div class="icon-badge">
              <ha-icon icon=${this.icon || "mdi:puzzle-outline"}></ha-icon>
            </div>
            <div>
              <p class="name">${this.displayName || this.connectorId}</p>
              ${this.capabilityMode ? b2`<p class="mode">${this.capabilityMode}</p>` : null}
            </div>
          </div>
          <hamie-status status=${STATUS_MAP[status] || "unknown"} label=${this._label(status)}></hamie-status>
        </div>

        <div class="meta">
          <span>Last checked: <strong>${this.lastTested || (this.enabled ? "Checking\u2026" : "\u2014")}</strong></span>
          ${this.latencyMs != null ? b2`<span>Latency: <strong>${this.latencyMs} ms</strong></span>` : null}
          ${this.consecutiveFailures > 0 ? b2`<span>${this.consecutiveFailures} consecutive failure${this.consecutiveFailures === 1 ? "" : "s"}</span>` : null}
        </div>

        ${this.errorCode ? b2`
              <div class="error">
                <span>${humanizeCode(this.errorCode, "That connector could not complete its last operation.")}</span>
                <hamie-button variant="ghost" size="xs" @click=${() => this._detailsOpen = !this._detailsOpen}>
                  ${this._detailsOpen ? "Hide details" : "View Details"}
                </hamie-button>
              </div>
              ${this._detailsOpen ? b2`<p class="error-details">Technical: ${this.errorCode}</p>` : null}
            ` : null}

        <div class="actions">
          <hamie-button variant="secondary" size="xs" ?disabled=${!this.enabled} @click=${this._onTest}>
            <ha-icon icon="mdi:lan-connect"></ha-icon> ${this.errorCode ? "Retry" : "Test"}
          </hamie-button>
          <hamie-button variant="ghost" size="xs" @click=${this._onConfigure}>
            <ha-icon icon="mdi:cog-outline"></ha-icon> Configure
          </hamie-button>
        </div>
      </hamie-card>
    `;
  }
  _label(status) {
    if (status === "disabled") return "Disabled";
    if (status === "unknown") return "Checking\u2026";
    if (status === "degraded") return "Degraded";
    if (status === "error") return "Offline";
    return void 0;
  }
};
if (!customElements.get("hamie-provider-card")) {
  customElements.define("hamie-provider-card", HamieProviderCard);
}

// hamie/frontend/connector-security.js
function applyEnabledTransition({
  draft,
  enabledKey,
  approveHostKey,
  nextEnabled,
  approveHostManuallyChanged
}) {
  const wasEnabled = Boolean(draft[enabledKey]);
  const next = { ...draft, [enabledKey]: nextEnabled };
  if (!wasEnabled && nextEnabled && !approveHostManuallyChanged && !draft[approveHostKey]) {
    next[approveHostKey] = true;
  }
  return next;
}

// hamie/frontend/views/hamie-ai-provider-editor.js
var FIELD_ERROR_MESSAGES = {
  required: "This field is required.",
  invalid_url: "Enter a valid HTTP or HTTPS address without embedded credentials.",
  host_not_allowed: "This host needs explicit approval before HAMIE can connect.",
  unsafe_host: "This address range is blocked by HAMIE's host policy.",
  credential_required: "Enter the required credential and choose Replace.",
  model_not_found: "Select a model returned by the provider, or use Advanced manual entry.",
  invalid_authentication: "Review the authentication method and credential.",
  below_minimum: "The value is below the supported minimum.",
  above_maximum: "The value exceeds the supported maximum.",
  invalid_type: "Enter a value in the expected format."
};
function fieldErrorMessage(code) {
  return FIELD_ERROR_MESSAGES[code] || String(code).replaceAll("_", " ");
}
var ADVANCED_FIELD_KEYS = [
  "ollama_provider_type",
  "ollama_approve_remote_host",
  "ollama_api_key",
  "ollama_credential_action",
  "ollama_confirm_remove_credential",
  "ollama_timeout",
  "ollama_verify_tls",
  "ollama_maximum_input_characters",
  "ai_maximum_advisory_groups_per_run",
  "ai_maximum_findings_per_group",
  "ai_maximum_estimated_tokens",
  "ai_minimum_confidence_threshold",
  "ollama_maximum_output_tokens",
  "ollama_temperature",
  "ollama_think",
  "ollama_analyze_findings",
  "ollama_analyze_groups",
  "ollama_prioritize_findings",
  "ollama_suggest_troubleshooting_checks",
  "ollama_suggest_non_executing_repair_plans",
  "ollama_automatic_analysis"
];
var HamieAiProviderEditor = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _providers: { state: true },
    _draft: { state: true },
    _errors: { state: true },
    _dirty: { state: true },
    _advancedOpen: { state: true },
    _discoveredModels: { state: true },
    _modelSearch: { state: true },
    _result: { state: true },
    _saving: { state: true },
    _testing: { state: true },
    _error: { state: true }
  };
  static styles = i`
    :host {
      display: block;
    }
    .credential-note {
      margin: 0 0 var(--hamie-space-3);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .fields {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-1);
    }
    .field.boolean {
      flex-direction: row;
      align-items: center;
      justify-content: space-between;
    }
    label {
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .description {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .field-error {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-status-critical);
    }
    .status-value {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
    }
    .disclosure {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1);
      background: none;
      border: none;
      cursor: pointer;
      color: var(--hamie-accent);
      font-size: var(--hamie-text-small);
      padding: var(--hamie-space-2) 0;
      margin: var(--hamie-space-2) 0;
    }
    .advanced {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
      padding-top: var(--hamie-space-2);
      border-top: 1px solid var(--hamie-border-hairline);
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      padding-bottom: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-3);
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .dirty-flag {
      margin-left: auto;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .result {
      margin: 0 0 var(--hamie-space-3);
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      font-size: var(--hamie-text-small);
    }
    .result.ok {
      background: var(--hamie-status-positive-fill);
      color: var(--hamie-status-positive);
    }
    .result.fail {
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
    }
  `;
  constructor() {
    super();
    this._modelSearch = "";
    this._discoveredModels = [];
    this._advancedOpen = false;
    this._errors = {};
    this._approveHostManuallyChanged = false;
  }
  connectedCallback() {
    super.connectedCallback();
    this._load();
  }
  async _load() {
    if (!this.hass) return;
    try {
      const [config, providers] = await Promise.all([
        this.hass.callWS({ type: "hamie/configuration/get", schema_version: 2 }),
        this.hass.callWS({ type: "hamie/ai_providers/discover" }).catch(() => ({ ai_task_available: false, ai_task_entities: [] }))
      ]);
      this._config = config;
      this._providers = providers;
      this._resetDraft();
      const cached = config.sections?.ollama?.metadata?.discovered_models;
      if (Array.isArray(cached) && cached.length) {
        this._discoveredModels = [...cached].sort((left, right) => left.localeCompare(right));
      }
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "AI provider settings are temporarily unavailable.");
    }
  }
  _resetDraft() {
    const section = this._config.sections?.ollama;
    const values = structuredClone(section?.values || {});
    for (const field of section?.fields || []) {
      if (field.secret) values[field.key] = "";
    }
    this._draft = values;
    this._errors = {};
    this._dirty = false;
    this._result = void 0;
    this._discoveredModels = [];
    this._modelSearch = "";
    this._approveHostManuallyChanged = false;
  }
  _fieldsByKey() {
    return Object.fromEntries((this._config.sections?.ollama?.fields || []).map((field) => [field.key, field]));
  }
  _onFieldChange(key, value) {
    if (key === "ollama_approve_host") {
      this._approveHostManuallyChanged = true;
    }
    this._draft = key === "ollama_enabled" ? applyEnabledTransition({
      draft: this._draft,
      enabledKey: "ollama_enabled",
      approveHostKey: "ollama_approve_host",
      nextEnabled: value,
      approveHostManuallyChanged: this._approveHostManuallyChanged
    }) : { ...this._draft, [key]: value };
    this._dirty = true;
    if (this._errors[key]) {
      const errors = { ...this._errors };
      delete errors[key];
      this._errors = errors;
    }
    this._result = void 0;
    if (key === "ollama_base_url") {
      this._discoveredModels = [];
      this._modelSearch = "";
    }
  }
  _statusLine() {
    const method = this._draft.ai_connection_method || "direct";
    const providers = this._providers || { ai_task_available: false, ai_task_entities: [] };
    if (!this._draft.ollama_enabled) return "Disabled";
    if (this._result?.ok === false) return "Test failed";
    if (method === "ha_ai_task") {
      if (!providers.ai_task_available) return "Unsupported \u2014 AI Task is not installed";
      if (!this._draft.ai_task_entity_id) return "Not configured";
      const known = providers.ai_task_entities.some((entity) => entity.entity_id === this._draft.ai_task_entity_id);
      if (!known) return "Entity unavailable";
      return "Ready";
    }
    if (!this._draft.ollama_model) return "Not configured -- no model selected";
    if (this._discoveredModels.length && !this._discoveredModels.includes(this._draft.ollama_model)) {
      return `Ready, but "${this._draft.ollama_model}" was not in the last discovered model list`;
    }
    return "Ready (direct connection -- deprecated advanced fallback)";
  }
  _buildSaveValues() {
    const section = this._config.sections.ollama;
    const values = {};
    for (const field of section.fields || []) {
      const hasDraft = Object.prototype.hasOwnProperty.call(this._draft, field.key);
      values[field.key] = field.locked ? section.values[field.key] ?? field.default : structuredClone(hasDraft ? this._draft[field.key] : field.default);
    }
    if (values.ollama_api_key && values.ollama_credential_action === "keep") {
      values.ollama_credential_action = "replace";
    }
    return values;
  }
  async _onSave() {
    this._saving = true;
    try {
      const result = await this.hass.callWS({
        type: "hamie/configuration/save",
        schema_version: 2,
        section: "ollama",
        values: this._buildSaveValues(),
        expected_revision: this._config.revision,
        idempotency_token: idempotencyToken()
      });
      if (result.ok === false) {
        this._applyFailure(result);
        return;
      }
      this._config = { ...this._config, revision: result.revision };
      if (result.section_state) {
        this._config = {
          ...this._config,
          sections: { ...this._config.sections, ollama: result.section_state }
        };
      }
      this._resetDraft();
      this._result = { ok: true, message: result.saved ? "Settings saved." : "No settings changed." };
      this.dispatchEvent(new CustomEvent("hamie-ai-provider-saved", { bubbles: true, composed: true }));
    } catch (err) {
      this._applyFailure({ error_code: err?.code });
    } finally {
      this._saving = false;
    }
  }
  _onCancel() {
    this.dispatchEvent(new CustomEvent("hamie-ai-provider-cancelled", { bubbles: true, composed: true }));
  }
  async _onTest() {
    this._testing = true;
    try {
      const method = this._draft.ai_connection_method || "direct";
      if (method !== "direct") {
        await this._testNativeProvider(method);
        return;
      }
      const result = await this.hass.callWS({
        type: "hamie/configuration/test",
        schema_version: 2,
        connector_id: "ollama",
        values: this._buildSaveValues()
      });
      if (result.ok === false || result.connected === false) {
        this._applyFailure(result, result.error_code || "unreachable");
        return;
      }
      this._discoveredModels = [...result.models || []].slice(0, 100).sort((left, right) => left.localeCompare(right));
      this._modelSearch = "";
      this._result = { ok: true, message: "Connection test succeeded without saving." };
    } catch (err) {
      this._applyFailure({ error_code: err?.code }, err?.code || "unreachable");
    } finally {
      this._testing = false;
    }
  }
  async _testNativeProvider(method) {
    const entityId = this._draft.ai_task_entity_id;
    if (!entityId) {
      this._applyFailure({ field_errors: { ai_task_entity_id: "required" } }, "required");
      return;
    }
    try {
      const result = await this.hass.callWS({
        type: "hamie/ai_providers/test",
        connection_method: method,
        entity_id: entityId
      });
      if (result.ok === false || result.connected === false) {
        this._applyFailure(result, result.error_code || "unreachable");
        return;
      }
      this._result = { ok: true, message: `Connection test succeeded without saving. Latency ${result.latency_ms} ms.` };
    } catch (err) {
      this._applyFailure({ error_code: err?.code }, err?.code || "unreachable");
    }
  }
  _applyFailure(result, fallbackCode = "configuration_failed") {
    this._errors = structuredClone(result?.field_errors || {});
    if (Object.keys(this._errors).length) this._advancedOpen = true;
    this._result = { ok: false, message: result?.message || fieldErrorMessage(result?.error_code || fallbackCode) };
  }
  _renderField(key, { label } = {}) {
    const field = this._fieldsByKey()[key];
    if (!field) return null;
    const value = this._draft[key] ?? field.default ?? "";
    const error = this._errors[key] ? fieldErrorMessage(this._errors[key]) : "";
    let control;
    if (field.kind === "boolean") {
      control = b2`<hamie-switch ?checked=${Boolean(value)} @hamie-change=${(e6) => this._onFieldChange(key, e6.detail.checked)}></hamie-switch>`;
    } else if (field.kind === "select") {
      const options = (field.choices || []).map((choice) => ({ value: choice, label: String(choice).replaceAll("_", " ") }));
      control = b2`<hamie-select .value=${value} .options=${options} @hamie-change=${(e6) => this._onFieldChange(key, e6.detail.value)}></hamie-select>`;
    } else {
      control = b2`<hamie-input
        .value=${String(value)}
        type=${field.secret ? "password" : field.kind === "url" ? "url" : "text"}
        @hamie-input=${(e6) => {
        const raw = e6.detail.value;
        const numeric = ["integer", "number"].includes(field.kind) && raw !== "" ? Number(raw) : raw;
        this._onFieldChange(key, numeric);
      }}
      ></hamie-input>`;
    }
    return b2`
      <div class="field ${field.kind === "boolean" ? "boolean" : ""}">
        <label>${label || field.label}</label>
        ${control}
        ${field.description ? b2`<span class="description">${field.description}</span>` : null}
        ${error ? b2`<span class="field-error">${error}</span>` : null}
      </div>
    `;
  }
  _renderModelField() {
    const value = this._draft.ollama_model || "";
    const error = this._errors.ollama_model ? fieldErrorMessage(this._errors.ollama_model) : "";
    if (!this._discoveredModels.length) {
      return b2`
        <div class="field">
          <label>Model</label>
          <span class="description">
            ${value ? `Currently set to "${value}". Test Connection to discover available models and confirm it's still available.` : "Test Connection to discover available models."}
          </span>
          ${error ? b2`<span class="field-error">${error}</span>` : null}
        </div>
      `;
    }
    const configuredModelMissing = value && !this._discoveredModels.includes(value);
    const query = this._modelSearch.trim().toLocaleLowerCase();
    let filtered = this._discoveredModels.filter((model) => model.toLocaleLowerCase().includes(query));
    if (value && this._discoveredModels.includes(value) && !filtered.includes(value)) filtered = [value, ...filtered];
    const options = [{ value: "", label: "Select a discovered model" }, ...filtered.map((model) => ({ value: model, label: model }))];
    return b2`
      <div class="field">
        <label>Search models</label>
        <hamie-input .value=${this._modelSearch} placeholder="Filter discovered models" @hamie-input=${(e6) => this._modelSearch = e6.detail.value}></hamie-input>
        <label>Model</label>
        <hamie-select .value=${value} .options=${options} @hamie-change=${(e6) => this._onFieldChange("ollama_model", e6.detail.value)}></hamie-select>
        ${configuredModelMissing ? b2`<span class="field-error">"${value}" was not in the last discovered model list. It may no longer be available on this provider -- select one of the discovered models above, or retest.</span>` : null}
        ${error ? b2`<span class="field-error">${error}</span>` : null}
      </div>
    `;
  }
  _renderManualModelField() {
    const value = this._draft.ollama_model || "";
    return b2`
      <div class="field">
        <label>Manual model identifier</label>
        <hamie-input .value=${value} @hamie-input=${(e6) => this._onFieldChange("ollama_model", e6.detail.value)}></hamie-input>
        <span class="description">Advanced fallback when model discovery is unavailable.</span>
      </div>
    `;
  }
  render() {
    if (this._error) {
      return b2`<p class="field-error">${this._error}</p>`;
    }
    if (!this._config || !this._draft) {
      return b2`<p class="description">Loading…</p>`;
    }
    const method = this._draft.ai_connection_method || "direct";
    const providers = this._providers || { ai_task_available: false, ai_task_entities: [] };
    const methodField = this._fieldsByKey().ai_connection_method;
    const methodOptions = [
      providers.ai_task_available ? { value: "ha_ai_task", label: "Home Assistant AI Task (recommended)" } : null,
      { value: "direct", label: "Legacy direct provider \u2014 deprecated compatibility fallback" }
    ].filter(Boolean);
    const credentialConfigured = this._config.sections.ollama.values?.ollama_credential_configured;
    const noAuthConfigured = !this._draft.ollama_api_key && !credentialConfigured;
    const authNote = noAuthConfigured ? b2`<span class="description">No API key configured -- this connects without authentication. That's the expected, fully supported setup for a local Ollama instance.</span>` : b2`<span class="description">An API key is configured for this connection.</span>`;
    let basicDirectFields = null;
    let extraAdvancedFields = null;
    if (method === "direct") {
      basicDirectFields = b2`
        ${this._renderField("ollama_base_url", { label: "Address" })}
        ${authNote}
        ${this._renderModelField()}
      `;
    } else {
      extraAdvancedFields = b2`
        ${this._renderField("ollama_base_url", { label: "Address" })}
        ${authNote}
        ${this._renderModelField()}
      `;
    }
    const entities = providers.ai_task_entities || [];
    const entityValue = this._draft.ai_task_entity_id || "";
    const entityError = this._errors.ai_task_entity_id ? fieldErrorMessage(this._errors.ai_task_entity_id) : "";
    const entityOptions = [
      { value: "", label: entities.length ? "Select a provider" : "No compatible entities found" },
      ...entities.map((entity) => ({ value: entity.entity_id, label: `${entity.name} \u2014 ${entity.entity_id}` }))
    ];
    return b2`
      <div class="actions">
        <hamie-button variant="primary" size="sm" ?disabled=${this._saving} @click=${this._onSave}>
          ${this._saving ? "Saving\u2026" : "Save"}
        </hamie-button>
        <hamie-button variant="secondary" size="sm" @click=${this._onCancel}>Cancel</hamie-button>
        <hamie-button variant="secondary" size="sm" ?disabled=${this._testing} @click=${this._onTest}>
          <ha-icon icon="mdi:lan-connect"></ha-icon> ${this._testing ? "Testing\u2026" : "Test Connection"}
        </hamie-button>
        <span class="dirty-flag">${this._dirty ? "Unsaved changes" : "Saved"}</span>
      </div>
      ${credentialConfigured === void 0 ? null : b2`<p class="credential-note">Authentication: ${credentialConfigured ? "configured (value hidden)" : "not configured"}</p>`}
      ${this._result ? b2`<div class="result ${this._result.ok ? "ok" : "fail"}">${this._result.message}</div>` : null}

      <div class="fields">
        ${this._renderField("ollama_enabled")}
        ${this._renderField("ollama_approve_host")}
        <div class="field">
          <label>Connection method</label>
          <hamie-select .value=${method} .options=${methodOptions} @hamie-change=${(e6) => this._onFieldChange("ai_connection_method", e6.detail.value)}></hamie-select>
          ${method === "direct" ? b2`<span class="description">Direct is a deprecated, advanced-only fallback. Home Assistant AI Task is the recommended background-analysis pipeline.</span>` : methodField?.description ? b2`<span class="description">${methodField.description}</span>` : null}
        </div>
        ${method === "ha_ai_task" ? b2`
              <div class="field">
                <label>Provider</label>
                <hamie-select
                  .value=${entityValue}
                  .options=${entityOptions}
                  ?disabled=${!entities.length}
                  @hamie-change=${(e6) => this._onFieldChange("ai_task_entity_id", e6.detail.value)}
                ></hamie-select>
                ${entityError ? b2`<span class="field-error">${entityError}</span>` : b2`<span class="description">Discovered from this Home Assistant.</span>`}
              </div>
            ` : null}
        ${basicDirectFields}
        <div class="field">
          <label>Status</label>
          <span class="status-value">${this._statusLine()}</span>
        </div>
      </div>

      <button class="disclosure" type="button" aria-expanded=${this._advancedOpen} @click=${() => this._advancedOpen = !this._advancedOpen}>
        <ha-icon icon="mdi:chevron-${this._advancedOpen ? "up" : "down"}"></ha-icon>
        ${this._advancedOpen ? "Hide" : "Show"} Advanced Options
      </button>
      ${this._advancedOpen ? b2`
            <div class="advanced">
              ${extraAdvancedFields}
              ${this._renderManualModelField()}
              ${ADVANCED_FIELD_KEYS.map((key) => this._renderField(key))}
            </div>
          ` : null}
    `;
  }
};
if (!customElements.get("hamie-ai-provider-editor")) {
  customElements.define("hamie-ai-provider-editor", HamieAiProviderEditor);
}

// hamie/frontend/views/hamie-connector-editor.js
var CONNECTOR_LABELS = { n8n: "n8n", mcp: "MCP", hkg: "HKG" };
var BASIC_FIELD_KEYS = {
  n8n: ["n8n_base_url", "n8n_outbound_webhook_url", "n8n_authentication_type", "n8n_username", "n8n_outbound_credential"],
  mcp: ["mcp_endpoint", "mcp_authentication_type", "mcp_credential"],
  hkg: ["hkg_endpoint", "hkg_authentication_type", "hkg_credential"]
};
var N8N_CONNECTION_KEYS = ["n8n_base_url"];
var N8N_OUTBOUND_KEYS = ["n8n_outbound_webhook_url", "n8n_authentication_type", "n8n_username", "n8n_outbound_credential"];
function isBasicFieldVisible(connectorId, key, draft) {
  if (key === "n8n_username") return draft.n8n_authentication_type === "username_and_password";
  if (key === "n8n_outbound_credential") return draft.n8n_authentication_type !== "none";
  if (key === "mcp_credential") return draft.mcp_authentication_type !== "none";
  if (key === "hkg_credential") return draft.hkg_authentication_type !== "none";
  return true;
}
var HamieConnectorEditor = class extends i4 {
  static properties = {
    hass: { attribute: false },
    connectorId: { type: String, attribute: "connector-id" },
    _config: { state: true },
    _draft: { state: true },
    _errors: { state: true },
    _dirty: { state: true },
    _advancedOpen: { state: true },
    _result: { state: true },
    _saving: { state: true },
    _testing: { state: true },
    _error: { state: true }
  };
  static styles = i`
    :host {
      display: block;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
      padding-bottom: var(--hamie-space-3);
      margin-bottom: var(--hamie-space-3);
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .dirty-flag {
      margin-left: auto;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .credential-note {
      margin: 0 0 var(--hamie-space-3);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .fields {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-1);
    }
    .field.boolean {
      flex-direction: row;
      align-items: center;
      justify-content: space-between;
    }
    label {
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .description {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .field-error {
      font-size: var(--hamie-text-micro);
      color: var(--hamie-status-critical);
    }
    .disclosure {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-1);
      background: none;
      border: none;
      cursor: pointer;
      color: var(--hamie-accent);
      font-size: var(--hamie-text-small);
      padding: var(--hamie-space-2) 0;
      margin: var(--hamie-space-3) 0 0;
    }
    .advanced {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
      padding-top: var(--hamie-space-2);
      border-top: 1px solid var(--hamie-border-hairline);
    }
    .result {
      margin: 0 0 var(--hamie-space-3);
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      font-size: var(--hamie-text-small);
    }
    .result.ok {
      background: var(--hamie-status-positive-fill);
      color: var(--hamie-status-positive);
    }
    .result.fail {
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
    }
    .group-heading {
      margin: var(--hamie-space-2) 0 0;
      font-size: var(--hamie-text-caption);
      font-weight: var(--hamie-weight-medium);
      text-transform: uppercase;
      letter-spacing: var(--hamie-tracking-label);
      color: var(--hamie-text-secondary);
    }
    .group-help {
      margin: 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    .inbound-endpoint {
      font-family: var(--hamie-font-code);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      word-break: break-all;
    }
  `;
  constructor() {
    super();
    this._advancedOpen = false;
    this._errors = {};
    this._approveHostManuallyChanged = false;
  }
  connectedCallback() {
    super.connectedCallback();
    this._load();
  }
  async _load() {
    if (!this.hass || !this.connectorId) return;
    try {
      this._config = await this.hass.callWS({ type: "hamie/configuration/get", schema_version: 2 });
      this._resetDraft();
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, `${CONNECTOR_LABELS[this.connectorId]} settings are temporarily unavailable.`);
    }
  }
  _section() {
    return this._config?.sections?.[this.connectorId];
  }
  _resetDraft() {
    const section = this._section();
    const values = structuredClone(section?.values || {});
    for (const field of section?.fields || []) {
      if (field.secret) values[field.key] = "";
    }
    this._draft = values;
    this._errors = {};
    this._dirty = false;
    this._result = void 0;
    this._approveHostManuallyChanged = false;
  }
  _fieldsByKey() {
    return Object.fromEntries((this._section()?.fields || []).map((field) => [field.key, field]));
  }
  _onFieldChange(key, value) {
    const enabledKey = `${this.connectorId}_enabled`;
    const approveHostKey = `${this.connectorId}_approve_host`;
    if (key === approveHostKey) {
      this._approveHostManuallyChanged = true;
    }
    this._draft = key === enabledKey ? applyEnabledTransition({
      draft: this._draft,
      enabledKey,
      approveHostKey,
      nextEnabled: value,
      approveHostManuallyChanged: this._approveHostManuallyChanged
    }) : { ...this._draft, [key]: value };
    this._dirty = true;
    if (this._errors[key]) {
      const errors = { ...this._errors };
      delete errors[key];
      this._errors = errors;
    }
    this._result = void 0;
  }
  _buildSaveValues() {
    const section = this._section();
    const values = {};
    for (const field of section.fields || []) {
      const hasDraft = Object.prototype.hasOwnProperty.call(this._draft, field.key);
      values[field.key] = field.locked ? section.values[field.key] ?? field.default : structuredClone(hasDraft ? this._draft[field.key] : field.default);
    }
    for (const [credentialKey, actionKey] of [
      ["n8n_outbound_credential", "n8n_outbound_credential_action"],
      ["n8n_inbound_credential", "n8n_inbound_credential_action"],
      ["mcp_credential", "mcp_credential_action"],
      ["hkg_credential", "hkg_credential_action"]
    ]) {
      if (values[credentialKey] && values[actionKey] === "keep") values[actionKey] = "replace";
    }
    return values;
  }
  async _onSave() {
    this._saving = true;
    try {
      const result = await this.hass.callWS({
        type: "hamie/configuration/save",
        schema_version: 2,
        section: this.connectorId,
        values: this._buildSaveValues(),
        expected_revision: this._config.revision,
        idempotency_token: idempotencyToken()
      });
      if (result.ok === false) {
        this._applyFailure(result);
        return;
      }
      this._config = { ...this._config, revision: result.revision };
      if (result.section_state) {
        this._config = {
          ...this._config,
          sections: { ...this._config.sections, [this.connectorId]: result.section_state }
        };
      }
      this._resetDraft();
      this._result = { ok: true, message: result.saved ? "Settings saved." : "No settings changed." };
      this.dispatchEvent(new CustomEvent("hamie-connector-saved", { bubbles: true, composed: true }));
    } catch (err) {
      this._applyFailure({ error_code: err?.code });
    } finally {
      this._saving = false;
    }
  }
  _onCancel() {
    this.dispatchEvent(new CustomEvent("hamie-connector-cancelled", { bubbles: true, composed: true }));
  }
  async _onTest() {
    this._testing = true;
    try {
      const result = await this.hass.callWS({
        type: "hamie/configuration/test",
        schema_version: 2,
        connector_id: this.connectorId,
        values: this._buildSaveValues()
      });
      if (result.ok === false || result.connected === false) {
        this._applyFailure(result, result.error_code || "unreachable");
        return;
      }
      this._result = { ok: true, message: this._testSuccessMessage(result) };
    } catch (err) {
      this._applyFailure({ error_code: err?.code }, err?.code || "unreachable");
    } finally {
      this._testing = false;
    }
  }
  _applyFailure(result, fallbackCode = "configuration_failed") {
    this._errors = structuredClone(result?.field_errors || {});
    if (Object.keys(this._errors).length) this._advancedOpen = true;
    this._result = { ok: false, message: result?.message || humanizeCode(result?.error_code || fallbackCode, "That could not be completed.") };
  }
  /**
   * n8n's Test Connection never fails just because the outbound webhook
   * is blank or not yet confirmed -- base service health and webhook
   * readiness are reported as two independent facts (connectors/n8n.py
   * N8nConnector.async_test), so a bare "Connection test succeeded"
   * would hide real, actionable information behind a falsely-complete
   * success message. Reported as concise, structured status sentences
   * ("Service reachable. Outbound webhook not configured.") rather than
   * the previous repetitive "n8n is reachable. n8n is reachable, but
   * ..." phrasing.
   */
  _testSuccessMessage(result) {
    if (this.connectorId !== "n8n") return "Connection test succeeded without saving.";
    const details = result?.result?.details;
    const readiness = details?.webhook_readiness;
    if (!readiness || readiness === "readiness_confirmed") {
      return "Service reachable. Outbound webhook ready.";
    }
    if (readiness === "not_configured") {
      return "Service reachable. Outbound webhook not configured.";
    }
    return `Service reachable. ${humanizeCode(details.webhook_error_code, "Outbound webhook readiness could not be confirmed.")}`;
  }
  _renderField(key) {
    const field = this._fieldsByKey()[key];
    if (!field) return null;
    const value = this._draft[key] ?? field.default ?? "";
    const error = this._errors[key] ? humanizeCode(this._errors[key], this._errors[key]) : "";
    let control;
    if (field.kind === "boolean") {
      control = b2`<hamie-switch ?checked=${Boolean(value)} ?disabled=${field.locked} @hamie-change=${(e6) => this._onFieldChange(key, e6.detail.checked)}></hamie-switch>`;
    } else if (field.kind === "select") {
      const options = (field.choices || []).map((choice) => ({ value: choice, label: String(choice).replaceAll("_", " ") }));
      control = b2`<hamie-select .value=${value} .options=${options} ?disabled=${field.locked} @hamie-change=${(e6) => this._onFieldChange(key, e6.detail.value)}></hamie-select>`;
    } else if (field.kind === "multiselect" || field.kind === "json" || field.kind === "csv") {
      const text = Array.isArray(value) ? value.join(", ") : String(value ?? "");
      control = b2`<hamie-input .value=${text} ?disabled=${field.locked} @hamie-input=${(e6) => this._onFieldChange(key, field.kind === "multiselect" ? e6.detail.value.split(",").map((v3) => v3.trim()).filter(Boolean) : e6.detail.value)}></hamie-input>`;
    } else {
      control = b2`<hamie-input
        .value=${String(value)}
        type=${field.secret ? "password" : field.kind === "url" ? "url" : "text"}
        ?disabled=${field.locked}
        @hamie-input=${(e6) => {
        const raw = e6.detail.value;
        const numeric = ["integer", "number"].includes(field.kind) && raw !== "" ? Number(raw) : raw;
        this._onFieldChange(key, numeric);
      }}
      ></hamie-input>`;
    }
    return b2`
      <div class="field ${field.kind === "boolean" ? "boolean" : ""}">
        <label>${field.label}${field.locked ? " (fixed)" : ""}</label>
        ${control}
        ${field.description ? b2`<span class="description">${field.description}</span>` : null}
        ${error ? b2`<span class="field-error">${error}</span>` : null}
      </div>
    `;
  }
  render() {
    if (this._error) {
      return b2`<p class="field-error">${this._error}</p>`;
    }
    if (!this._config || !this._draft) {
      return b2`<p class="description">Loading…</p>`;
    }
    const section = this._section();
    const enabledKey = `${this.connectorId}_enabled`;
    const approveHostKey = `${this.connectorId}_approve_host`;
    const approveRemoteHostKey = `${this.connectorId}_approve_remote_host`;
    const allKeys = (section.fields || []).map((f4) => f4.key).filter((key) => !key.endsWith("_allowed_hosts"));
    const basicKeys = (BASIC_FIELD_KEYS[this.connectorId] || []).filter(
      (key) => allKeys.includes(key) && isBasicFieldVisible(this.connectorId, key, this._draft)
    );
    const advancedKeys = allKeys.filter(
      (key) => key !== enabledKey && key !== approveHostKey && key !== approveRemoteHostKey && !basicKeys.includes(key)
    );
    const securityHeader = b2`
      ${this._renderField(enabledKey)}
      ${this._renderField(approveHostKey)}
    `;
    return b2`
      <div class="actions">
        <hamie-button variant="primary" size="sm" ?disabled=${this._saving} @click=${this._onSave}>
          ${this._saving ? "Saving\u2026" : "Save"}
        </hamie-button>
        <hamie-button variant="secondary" size="sm" @click=${this._onCancel}>Cancel</hamie-button>
        <hamie-button variant="secondary" size="sm" ?disabled=${this._testing} @click=${this._onTest}>
          <ha-icon icon="mdi:lan-connect"></ha-icon> ${this._testing ? "Testing\u2026" : "Test Connection"}
        </hamie-button>
        <span class="dirty-flag">${this._dirty ? "Unsaved changes" : "Saved"}</span>
      </div>

      ${this._result ? b2`<div class="result ${this._result.ok ? "ok" : "fail"}">${this._result.message}</div>` : null}

      <div class="fields">
        ${securityHeader}
        ${this.connectorId === "n8n" ? this._renderN8nBody(basicKeys) : basicKeys.map((key) => this._renderField(key))}
      </div>

      <button class="disclosure" type="button" aria-expanded=${this._advancedOpen} @click=${() => this._advancedOpen = !this._advancedOpen}>
        <ha-icon icon="mdi:chevron-${this._advancedOpen ? "up" : "down"}"></ha-icon>
        ${this._advancedOpen ? "Hide" : "Show"} Advanced Options
      </button>
      ${this._advancedOpen ? b2`
            <div class="advanced">
              ${this.connectorId === "n8n" ? this._renderN8nAdvanced(advancedKeys) : advancedKeys.map((key) => this._renderField(key))}
              ${this._renderField(approveRemoteHostKey)}
            </div>
          ` : null}
    `;
  }
  /**
   * n8n's Basic fields, split into the two real, distinct concepts a
   * user reported conflating: the base service connection (already
   * covered by the universal security header + Base URL) versus the
   * *optional* HAMIE -> n8n outbound webhook. Neither implies the other
   * is broken -- see N8nConnector.async_test's own independent
   * health/webhook-readiness facts this mirrors.
   */
  _renderN8nBody(basicKeys) {
    const connectionKeys = basicKeys.filter((key) => N8N_CONNECTION_KEYS.includes(key));
    const outboundKeys = basicKeys.filter((key) => N8N_OUTBOUND_KEYS.includes(key));
    return b2`
      ${connectionKeys.map((key) => this._renderField(key))}
      <h3 class="group-heading">HAMIE → n8n</h3>
      <p class="group-help">
        Optional webhook used when HAMIE sends commands or events to n8n.
        This is separate from the n8n service-health connection above.
      </p>
      ${outboundKeys.map((key) => this._renderField(key))}
    `;
  }
  /** n8n's Advanced fields, with the real inbound (n8n -> HAMIE) surface
   * grouped and labeled separately from generic connector tuning. */
  _renderN8nAdvanced(advancedKeys) {
    const inboundKeys = advancedKeys.filter((key) => key.startsWith("n8n_inbound"));
    const otherKeys = advancedKeys.filter((key) => !key.startsWith("n8n_inbound"));
    const inboundEndpoint = this._config?.sections?.n8n?.metadata?.inbound_endpoint;
    return b2`
      ${otherKeys.map((key) => this._renderField(key))}
      <h3 class="group-heading">n8n → HAMIE</h3>
      <p class="group-help">Controls for n8n calling back into HAMIE (inbound commands).</p>
      ${inboundEndpoint ? b2`
            <div class="field">
              <label>Inbound endpoint</label>
              <span class="inbound-endpoint">${inboundEndpoint}</span>
            </div>
          ` : null}
      ${inboundKeys.map((key) => this._renderField(key))}
    `;
  }
};
if (!customElements.get("hamie-connector-editor")) {
  customElements.define("hamie-connector-editor", HamieConnectorEditor);
}

// hamie/frontend/views/hamie-view-connectors.js
var CONNECTOR_META = {
  ollama: { displayName: "Ollama", icon: "mdi:server-outline" },
  n8n: { displayName: "n8n", icon: "mdi:sitemap-outline" },
  mcp: { displayName: "MCP", icon: "mdi:api" },
  hkg: { displayName: "HKG", icon: "mdi:graph-outline" }
};
var HamieViewConnectors = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _connectors: { state: true },
    _error: { state: true },
    _actionError: { state: true },
    _testingId: { state: true },
    _copiedEndpoint: { state: true },
    _configuringId: { state: true }
  };
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .action-error {
      margin-bottom: var(--hamie-space-3);
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
      font-size: var(--hamie-text-small);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: var(--hamie-space-3);
    }
    .grid hamie-button {
      margin-top: var(--hamie-space-2);
    }
    @media (max-width: 870px) {
      .grid {
        grid-template-columns: 1fr;
      }
    }
    /* A disabled connector is not a problem needing attention -- it must
     * never compete visually with an active, possibly-degraded one. */
    .connector-tile[data-disabled] {
      opacity: 0.55;
    }
    hamie-dialog {
      --mdc-dialog-min-width: min(560px, 90vw);
    }
  `;
  connectedCallback() {
    super.connectedCallback();
    this._load();
    this._onLiveUpdate = () => this._load();
    window.addEventListener("hamie-live-update", this._onLiveUpdate);
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("hamie-live-update", this._onLiveUpdate);
  }
  async _load() {
    if (!this.hass) return;
    try {
      this._connectors = await this.hass.callWS({ type: "hamie/connectors/status" });
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Connector data is temporarily unavailable.");
    }
  }
  async _onTest(event) {
    if (!this.hass) return;
    const connectorId = event.detail.connectorId;
    this._actionError = null;
    this._testingId = connectorId;
    try {
      const result = await this.hass.callWS({ type: "hamie/connectors/test", connector_id: connectorId });
      this._connectors = this._connectors.map((item) => item.connector_id === connectorId ? result : item);
    } catch (err) {
      this._actionError = friendlyError(err, `Testing ${connectorId} failed.`);
    } finally {
      this._testingId = null;
    }
  }
  _onConfigure(event) {
    this._configuringId = event.detail.connectorId;
  }
  async _onConfigureDone() {
    this._configuringId = null;
    await this._load();
  }
  async _onCopyN8nEndpoint() {
    this._actionError = null;
    try {
      await navigator.clipboard.writeText("/api/hamie/n8n");
      this._copiedEndpoint = true;
      setTimeout(() => {
        this._copiedEndpoint = false;
      }, 2e3);
    } catch {
      this._actionError = "Copy is unavailable. The inbound endpoint is /api/hamie/n8n.";
    }
  }
  render() {
    if (this._error) {
      return b2`<hamie-empty tone="unavailable" heading="Connectors are unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._connectors) {
      return b2`<hamie-loading .lines=${4}></hamie-loading>`;
    }
    const enabledCount = this._connectors.filter((item) => item.enabled).length;
    return b2`
      <hamie-page-header heading="Connectors" subtitle="${enabledCount} of ${this._connectors.length} connectors enabled"></hamie-page-header>

      ${this._actionError ? b2`
            <div class="action-error">
              <span>${this._actionError}</span>
              <hamie-button variant="ghost" size="xs" @click=${() => this._actionError = null}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          ` : null}

      <div class="grid">
        ${this._connectors.map((item) => {
      const meta = CONNECTOR_META[item.connector_id] || { displayName: item.connector_id, icon: "mdi:puzzle-outline" };
      return b2`
            <div class="connector-tile" ?data-disabled=${!item.enabled}>
              <hamie-provider-card
                .connectorId=${item.connector_id}
                .displayName=${meta.displayName}
                .icon=${meta.icon}
                .enabled=${item.enabled}
                .status=${this._testingId === item.connector_id ? "unknown" : item.status}
                .capabilityMode=${item.capability_mode}
                .lastTested=${item.last_tested ? relativeTime(item.last_tested) : null}
                .latencyMs=${item.latency_ms}
                .consecutiveFailures=${item.consecutive_failures}
                .errorCode=${item.error_code}
                @hamie-provider-test=${this._onTest}
                @hamie-provider-configure=${this._onConfigure}
              ></hamie-provider-card>
              ${item.connector_id === "n8n" ? b2`
                    <hamie-button variant="ghost" size="xs" @click=${this._onCopyN8nEndpoint}>
                      <ha-icon icon="mdi:content-copy"></ha-icon>
                      ${this._copiedEndpoint ? "Copied!" : "Copy inbound endpoint"}
                    </hamie-button>
                  ` : null}
            </div>
          `;
    })}
      </div>

      ${this._configuringId ? b2`
            <hamie-dialog
              open
              heading="Configure ${CONNECTOR_META[this._configuringId]?.displayName || this._configuringId}"
              @hamie-dialog-closed=${this._onConfigureDone}
            >
              ${this._configuringId === "ollama" ? b2`<hamie-ai-provider-editor .hass=${this.hass} @hamie-ai-provider-saved=${this._onConfigureDone} @hamie-ai-provider-cancelled=${this._onConfigureDone}></hamie-ai-provider-editor>` : b2`<hamie-connector-editor .hass=${this.hass} connector-id=${this._configuringId} @hamie-connector-saved=${this._onConfigureDone} @hamie-connector-cancelled=${this._onConfigureDone}></hamie-connector-editor>`}
            </hamie-dialog>
          ` : null}
    `;
  }
};
if (!customElements.get("hamie-view-connectors")) {
  customElements.define("hamie-view-connectors", HamieViewConnectors);
}

// node_modules/lit-html/async-directive.js
var s5 = (i7, t5) => {
  const e6 = i7._$AN;
  if (void 0 === e6) return false;
  for (const i8 of e6) i8._$AO?.(t5, false), s5(i8, t5);
  return true;
};
var o5 = (i7) => {
  let t5, e6;
  do {
    if (void 0 === (t5 = i7._$AM)) break;
    e6 = t5._$AN, e6.delete(i7), i7 = t5;
  } while (0 === e6?.size);
};
var r5 = (i7) => {
  for (let t5; t5 = i7._$AM; i7 = t5) {
    let e6 = t5._$AN;
    if (void 0 === e6) t5._$AN = e6 = /* @__PURE__ */ new Set();
    else if (e6.has(i7)) break;
    e6.add(i7), c5(t5);
  }
};
function h4(i7) {
  void 0 !== this._$AN ? (o5(this), this._$AM = i7, r5(this)) : this._$AM = i7;
}
function n4(i7, t5 = false, e6 = 0) {
  const r6 = this._$AH, h6 = this._$AN;
  if (void 0 !== h6 && 0 !== h6.size) if (t5) if (Array.isArray(r6)) for (let i8 = e6; i8 < r6.length; i8++) s5(r6[i8], false), o5(r6[i8]);
  else null != r6 && (s5(r6, false), o5(r6));
  else s5(this, i7);
}
var c5 = (i7) => {
  i7.type == t3.CHILD && (i7._$AP ??= n4, i7._$AQ ??= h4);
};
var f3 = class extends i5 {
  constructor() {
    super(...arguments), this._$AN = void 0;
  }
  _$AT(i7, t5, e6) {
    super._$AT(i7, t5, e6), r5(this), this.isConnected = i7._$AU;
  }
  _$AO(i7, t5 = true) {
    i7 !== this.isConnected && (this.isConnected = i7, i7 ? this.reconnected?.() : this.disconnected?.()), t5 && (s5(this, i7), o5(this));
  }
  setValue(t5) {
    if (r4(this._$Ct)) this._$Ct._$AI(t5, this);
    else {
      const i7 = [...this._$Ct._$AH];
      i7[this._$Ci] = t5, this._$Ct._$AI(i7, this, 0);
    }
  }
  disconnected() {
  }
  reconnected() {
  }
};

// node_modules/lit-html/directives/ref.js
var e5 = () => new h5();
var h5 = class {
};
var o6 = /* @__PURE__ */ new WeakMap();
var n5 = e4(class extends f3 {
  render(i7) {
    return A;
  }
  update(i7, [s6]) {
    const e6 = s6 !== this.G;
    return e6 && this.rt(void 0), (e6 || this.lt !== this.ct) && (this.G = s6, this.ht = i7.options?.host, this.rt(this.ct = i7.element)), A;
  }
  rt(t5) {
    if (void 0 !== this.G) if (this.isConnected || (t5 = void 0), "function" == typeof this.G) {
      const i7 = this.ht ?? globalThis;
      let s6 = o6.get(i7);
      void 0 === s6 && (s6 = /* @__PURE__ */ new WeakMap(), o6.set(i7, s6)), void 0 !== s6.get(this.G) && this.G.call(this.ht, void 0), s6.set(this.G, t5), void 0 !== t5 && this.G.call(this.ht, t5);
    } else this.G.value = t5;
  }
  get lt() {
    return "function" == typeof this.G ? o6.get(this.ht ?? globalThis)?.get(this.G) : this.G?.value;
  }
  disconnected() {
    this.lt === this.ct && this.rt(void 0);
  }
  reconnected() {
    this.rt(this.ct);
  }
});

// hamie/frontend/components/hamie-activity-timeline.js
var HamieActivityTimeline = class extends i4 {
  static properties = {
    items: { type: Array },
    // [{ id, heading, meta, timeLabel, tone, icon }]
    interactive: { type: Boolean, reflect: true }
  };
  static styles = i`
    :host {
      display: block;
    }
    .row {
      position: relative;
      display: flex;
      gap: var(--hamie-space-3);
      padding: 0 0 var(--hamie-space-4);
    }
    .row:last-child {
      padding-bottom: 0;
    }
    .rail {
      position: relative;
      flex-shrink: 0;
      width: 24px;
      display: flex;
      justify-content: center;
    }
    .dot {
      z-index: 1;
      width: 24px;
      height: 24px;
      border-radius: var(--hamie-radius-circle);
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .dot ha-icon {
      --mdc-icon-size: 12px;
    }
    .line {
      position: absolute;
      top: 24px;
      bottom: -16px;
      width: 1px;
      background: var(--hamie-border-hairline);
    }
    .row:last-child .line {
      display: none;
    }
    .body {
      flex: 1;
      min-width: 0;
      padding-top: 2px;
    }
    .top {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .heading {
      margin: 0;
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
    }
    .time {
      flex-shrink: 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      font-family: var(--hamie-font-code);
    }
    .meta {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
    }
    button.body {
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      text-align: left;
      cursor: pointer;
      border-radius: var(--hamie-radius-sm);
    }
    button.body:hover .heading {
      color: var(--hamie-accent);
    }
    button.body:focus-visible {
      outline: 2px solid var(--hamie-accent);
      outline-offset: 2px;
    }
  `;
  _onClick(id) {
    if (!this.interactive) return;
    this.dispatchEvent(new CustomEvent("hamie-timeline-click", { detail: { id }, bubbles: true, composed: true }));
  }
  render() {
    const items = this.items || [];
    return b2`
      ${items.map((item) => {
      const body = b2`
          <span class="top">
            <p class="heading">${item.heading}</p>
            <span class="time">${item.timeLabel}</span>
          </span>
          ${item.meta ? b2`<p class="meta">${item.meta}</p>` : null}
        `;
      return b2`
          <div class="row">
            <span class="rail">
              <span class="dot" style="background: var(--hamie-status-${item.tone || "unknown"}-fill)">
                <ha-icon icon=${item.icon || "mdi:circle-small"} style="color: var(--hamie-status-${item.tone || "unknown"})"></ha-icon>
              </span>
              <span class="line"></span>
            </span>
            ${this.interactive ? b2`<button type="button" class="body" @click=${() => this._onClick(item.id)}>${body}</button>` : b2`<span class="body">${body}</span>`}
          </div>
        `;
    })}
    `;
  }
};
if (!customElements.get("hamie-activity-timeline")) {
  customElements.define("hamie-activity-timeline", HamieActivityTimeline);
}

// hamie/frontend/views/hamie-view-audit.js
var PAGE_SIZE5 = 25;
var EVENT_LABELS = {
  scan_completed: "Scan completed",
  connector_test_succeeded: "Connector test succeeded",
  connector_test_failed: "Connector test failed",
  ai_recommendation_created: "Recommendation generated",
  evidence_refreshed: "Evidence refreshed",
  remediation_plan_created: "Proposal created",
  remediation_proposal_snoozed: "Proposal snoozed",
  remediation_proposal_resumed: "Proposal resumed",
  remediation_proposal_snooze_expired: "Proposal snooze expired",
  backup_started: "Backup started",
  backup_verified: "Backup verified",
  remediation_approval_granted: "Proposal approved",
  remediation_approval_rejected: "Proposal rejected",
  remediation_execution_started: "Execution started",
  remediation_execution_succeeded: "Execution succeeded",
  remediation_execution_failed: "Execution failed",
  remediation_verification_passed: "Verification passed",
  remediation_verification_failed: "Verification failed",
  remediation_rollback_started: "Rollback started",
  remediation_rollback_succeeded: "Rollback completed",
  group_snooze: "Findings snoozed",
  group_dismiss: "Findings dismissed",
  audit_history_cleared: "Audit history cleared"
};
function eventLabel(event) {
  return EVENT_LABELS[event] || event.replaceAll("_", " ").replace(/^./, (value) => value.toUpperCase());
}
var ENTITY_ID_PATTERN = /^[a-z_]+\.[a-z0-9_]+$/;
function targetSummary(targetIds) {
  if (!targetIds.length) return "\u2014";
  if (targetIds.length === 1 && ENTITY_ID_PATTERN.test(targetIds[0])) return targetIds[0];
  return `${targetIds.length} object${targetIds.length === 1 ? "" : "s"}`;
}
function eventOutcome(item) {
  if (item.details?.outcome) return item.details.outcome.replaceAll("_", " ").replace(/^./, (value) => value.toUpperCase());
  if (item.event.endsWith("_failed") || item.event.endsWith("_rejected")) return "Failed";
  if (item.event.endsWith("_succeeded") || item.event.endsWith("_completed") || item.event.endsWith("_passed")) return "Succeeded";
  return "Recorded";
}
function eventTone(item) {
  const outcome = eventOutcome(item);
  if (outcome === "Failed") return "critical";
  if (outcome === "Succeeded") return "healthy";
  return "info";
}
var EVENT_ICON_PREFIX = [
  [/^scan/, "mdi:magnify"],
  [/^connector/, "mdi:swap-horizontal"],
  [/^ai_/, "mdi:brain"],
  [/^remediation_execution/, "mdi:play-circle-outline"],
  [/^remediation_rollback/, "mdi:undo-variant"],
  [/^remediation_approval/, "mdi:check-decagram-outline"],
  [/^remediation/, "mdi:wrench-check-outline"],
  [/^group_/, "mdi:folder-alert-outline"],
  [/^maintenance_work/, "mdi:broom"],
  [/^configuration/, "mdi:cog-outline"],
  [/^audit_history/, "mdi:clipboard-text-clock-outline"]
];
function eventIcon(event) {
  return EVENT_ICON_PREFIX.find(([pattern]) => pattern.test(event))?.[1] || "mdi:circle-small";
}
var HamieViewAudit = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _page: { state: true },
    _offset: { state: true },
    _error: { state: true },
    _actionError: { state: true },
    _detail: { state: true },
    // the one audit record currently shown in the details dialog
    _clearing: { state: true },
    _confirmingClear: { state: true },
    _filters: { state: true }
  };
  _clearHistoryTriggerRef = e5();
  // Focus must return to the control that opened the dialog once it
  // closes (Cancel, X, Escape, or a successful clear all route through
  // this same dialog-closed handler) -- not left stranded on whatever
  // the browser's default post-removal focus target happens to be.
  _onConfirmClearDialogClosed() {
    this._confirmingClear = false;
    this._clearHistoryTriggerRef.value?.focus();
  }
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: var(--hamie-space-2);
    }
    .action-error {
      margin-bottom: var(--hamie-space-3);
      padding: var(--hamie-space-2-5) var(--hamie-space-3);
      border-radius: var(--hamie-radius-md);
      background: var(--hamie-status-critical-fill);
      color: var(--hamie-status-critical);
      font-size: var(--hamie-text-small);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--hamie-space-3);
    }
    .audit-filters {
      display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: var(--hamie-space-2); margin-bottom: var(--hamie-space-3);
    }
    .audit-filters input {
      min-height: 38px; box-sizing: border-box; width: 100%;
      color: var(--hamie-text-primary); background: var(--hamie-surface-raised);
      border: 1px solid var(--hamie-border-hairline);
      border-radius: var(--hamie-radius-md); padding: 8px;
    }
    @media (max-width: 870px) {
      .audit-filters { grid-template-columns: 1fr; }
    }
    .pager {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--hamie-space-3) var(--hamie-space-4);
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      border-top: 1px solid var(--hamie-border-hairline);
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      font-size: var(--hamie-text-micro);
      font-family: var(--hamie-font-code);
      color: var(--hamie-text-secondary);
      margin: 0;
    }
  `;
  constructor() {
    super();
    this._offset = 0;
    this._filters = {};
  }
  connectedCallback() {
    super.connectedCallback();
    this._load();
  }
  async _load() {
    if (!this.hass) return;
    try {
      this._page = await this.hass.callWS({
        type: "hamie/audit/list",
        offset: this._offset,
        limit: PAGE_SIZE5,
        ...this._filters
      });
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Audit history is temporarily unavailable.");
    }
  }
  _nextPage() {
    this._offset += PAGE_SIZE5;
    this._load();
  }
  _previousPage() {
    this._offset = Math.max(0, this._offset - PAGE_SIZE5);
    this._load();
  }
  async _onExport() {
    if (!this.hass) return;
    this._actionError = null;
    try {
      const data = await this.hass.callWS({
        type: "hamie/configuration/audit/export",
        schema_version: 2
      });
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `hamie-audit-export-${(/* @__PURE__ */ new Date()).toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      this._actionError = friendlyError(err, "The audit history could not be exported.");
    }
  }
  async _onConfirmClear() {
    if (!this.hass || !this._page) return;
    this._clearing = true;
    try {
      await this.hass.callWS({
        type: "hamie/configuration/audit/clear",
        schema_version: 2,
        expected_revision: this._page.revision,
        idempotency_token: idempotencyToken(),
        confirmed: true
      });
      this._onConfirmClearDialogClosed();
      this._offset = 0;
      await this._load();
    } catch (err) {
      this._actionError = friendlyError(err, "Audit history could not be cleared.");
    } finally {
      this._clearing = false;
    }
  }
  render() {
    if (this._error) {
      return b2`<hamie-empty tone="unavailable" heading="Audit history is unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._page) {
      return b2`<hamie-loading .lines=${4}></hamie-loading>`;
    }
    const items = this._page.items;
    const timelineItems = items.map((item) => ({
      id: item.audit_id,
      icon: eventIcon(item.event),
      tone: eventTone(item),
      heading: eventLabel(item.event),
      meta: `${item.actor} \xB7 ${targetSummary(item.target_ids)} \xB7 ${eventOutcome(item)}`,
      timeLabel: relativeTime(item.at),
      raw: item
    }));
    return b2`
      <hamie-page-header
        heading="Activity"
        subtitle="${this._page.total} recorded event${this._page.total === 1 ? "" : "s"}"
      >
        <div slot="actions" class="header-actions">
          <hamie-button variant="secondary" size="sm" @click=${this._onExport}>
            <ha-icon icon="mdi:download-outline"></ha-icon> Export
          </hamie-button>
          <hamie-button
            ${n5(this._clearHistoryTriggerRef)}
            variant="danger"
            size="sm"
            ?disabled=${items.length === 0}
            @click=${() => this._confirmingClear = true}
          >
            <ha-icon icon="mdi:trash-can-outline"></ha-icon> Clear history
          </hamie-button>
        </div>
      </hamie-page-header>

      <div class="audit-filters" aria-label="Audit filters">
        ${[
      ["event_type", "Event type"],
      ["actor", "Actor"],
      ["target", "Target"],
      ["outcome", "Outcome"],
      ["date_from", "Date from (aware ISO)"],
      ["date_to", "Date to (aware ISO)"],
      ["proposal", "Proposal ID"],
      ["finding", "Finding ID"]
    ].map(([key, placeholder]) => b2`
          <input
            aria-label=${placeholder}
            placeholder=${placeholder}
            .value=${this._filters[key] || ""}
            @input=${(event) => this._filters = { ...this._filters, [key]: event.target.value }}
          />
        `)}
        <hamie-button variant="secondary" size="sm" @click=${() => {
      this._offset = 0;
      this._load();
    }}>Apply filters</hamie-button>
        <hamie-button variant="ghost" size="sm" @click=${() => {
      this._filters = {};
      this._offset = 0;
      this._load();
    }}>Clear filters</hamie-button>
      </div>

      ${this._actionError ? b2`
            <div class="action-error">
              <span>${this._actionError}</span>
              <hamie-button variant="ghost" size="xs" @click=${() => this._actionError = null}>
                <ha-icon icon="mdi:close"></ha-icon>
              </hamie-button>
            </div>
          ` : null}

      <hamie-card padding="md">
        ${timelineItems.length === 0 ? b2`<hamie-empty tone="neutral" heading="No activity yet"></hamie-empty>` : b2`<hamie-activity-timeline interactive .items=${timelineItems} @hamie-timeline-click=${(event) => this._detail = items.find((item) => item.audit_id === event.detail.id)}></hamie-activity-timeline>`}
        ${this._page.total > 0 ? b2`
              <div class="pager">
                <hamie-button variant="ghost" size="xs" ?disabled=${this._offset === 0} @click=${this._previousPage}>Previous</hamie-button>
                <span>${this._offset + 1}–${Math.min(this._offset + PAGE_SIZE5, this._page.total)} of ${this._page.total}</span>
                <hamie-button variant="ghost" size="xs" ?disabled=${this._offset + PAGE_SIZE5 >= this._page.total} @click=${this._nextPage}>Next</hamie-button>
              </div>
            ` : null}
      </hamie-card>

      ${this._detail ? b2`
            <hamie-dialog open heading="${eventLabel(this._detail.event)}" @hamie-dialog-closed=${() => this._detail = null}>
              <p><strong>Actor:</strong> ${this._detail.actor}</p>
              <p><strong>When:</strong> ${relativeTime(this._detail.at)}</p>
              <p><strong>Targets:</strong> ${this._detail.target_ids.length ? this._detail.target_ids.join(", ") : "none"}</p>
              <p><strong>Details:</strong></p>
              <pre>${JSON.stringify(this._detail.details, null, 2)}</pre>
              <hamie-button slot="primary-action" variant="secondary" size="sm" @click=${() => this._detail = null}>
                Close
              </hamie-button>
            </hamie-dialog>
          ` : null}

      ${this._confirmingClear ? b2`
            <hamie-dialog
              open
              heading="Clear all audit history?"
              cancel-label="Cancel"
              confirm-label="Clear history"
              destructive
              .busy=${this._clearing}
              .errorMessage=${this._actionError || ""}
              .onConfirm=${() => this._onConfirmClear()}
              .onCancel=${() => this._onConfirmClearDialogClosed()}
              .focusReturnTarget=${this._clearHistoryTriggerRef.value}
            >
              <p>
                This permanently clears all ${this._page.total} recorded audit event${this._page.total === 1 ? "" : "s"}.
                Home Assistant objects and HAMIE findings are not affected.
              </p>
            </hamie-dialog>
          ` : null}
    `;
  }
};
if (!customElements.get("hamie-view-audit")) {
  customElements.define("hamie-view-audit", HamieViewAudit);
}

// hamie/frontend/views/hamie-view-settings.js
var SECTION_LABELS = {
  general: "General",
  provenance: "Source & Deployment",
  findings: "Findings",
  grouping: "Grouping",
  ollama: "Ollama",
  n8n: "n8n",
  mcp: "MCP",
  hkg: "HKG",
  safety: "Safety",
  audit: "Audit",
  ai_control: "AI Control"
};
function formatValue(field, value) {
  if (field.secret) return null;
  if (value === null || value === void 0 || value === "") return "\u2014";
  if (field.kind === "boolean") return value ? "Enabled" : "Disabled";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "\u2014";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
var HamieViewSettings = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _scheduler: { state: true },
    _error: { state: true },
    _editingOllama: { state: true }
  };
  static styles = i`
    :host {
      display: block;
      padding: var(--hamie-space-5);
      max-width: var(--hamie-content-max-wide);
      box-sizing: border-box;
    }
    .sections {
      display: flex;
      flex-direction: column;
      gap: var(--hamie-space-3);
    }
    .field-row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--hamie-space-4);
      padding: var(--hamie-space-2) 0;
      border-bottom: 1px solid var(--hamie-border-hairline);
    }
    .field-row:last-child {
      border-bottom: none;
    }
    .field-label {
      font-size: var(--hamie-text-small);
      font-weight: var(--hamie-weight-medium);
      color: var(--hamie-text-primary);
      flex-shrink: 0;
      width: 40%;
    }
    .field-description {
      margin: 2px 0 0;
      font-size: var(--hamie-text-micro);
      color: var(--hamie-text-secondary);
      font-weight: var(--hamie-weight-normal);
    }
    .field-value {
      font-size: var(--hamie-text-small);
      color: var(--hamie-text-secondary);
      font-family: var(--hamie-font-code);
      text-align: right;
      word-break: break-word;
    }
  `;
  connectedCallback() {
    super.connectedCallback();
    this._load();
    this._onLiveUpdate = () => this._load();
    window.addEventListener("hamie-live-update", this._onLiveUpdate);
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("hamie-live-update", this._onLiveUpdate);
  }
  async _load() {
    if (!this.hass) return;
    try {
      const [config, context, scheduler] = await Promise.all([
        this.hass.callWS({ type: "hamie/configuration/get", schema_version: 2 }),
        this.hass.callWS({ type: "hamie/configuration/context" }),
        this.hass.callWS({ type: "hamie/scheduler/status" }).catch(() => null)
      ]);
      this._config = config;
      this._fallbackPath = context.fallback_path;
      this._scheduler = scheduler;
      this._error = null;
    } catch (err) {
      this._error = friendlyError(err, "Settings are temporarily unavailable.");
    }
  }
  _renderScheduler() {
    const scheduler = this._scheduler;
    if (!scheduler) return null;
    const nextScanText = scheduler.next_scan_seconds == null ? "\u2014" : scheduler.next_scan_seconds <= 0 ? "Due now" : `${Math.max(1, Math.round(scheduler.next_scan_seconds / 60))} minutes`;
    return b2`
      <hamie-card padding="md">
        <hamie-section heading="Scanning &amp; connector health"></hamie-section>
        <div class="field-row">
          <div class="field-label">Automatic scanning</div>
          <hamie-status
            status=${scheduler.auto_scan_enabled ? "healthy" : "offline"}
            label=${scheduler.auto_scan_enabled ? "On" : "Off"}
          ></hamie-status>
        </div>
        <div class="field-row">
          <div class="field-label">Interval</div>
          <span class="field-value">Every ${scheduler.auto_scan_interval_minutes} minutes</span>
        </div>
        <div class="field-row">
          <div class="field-label">Last automatic scan</div>
          <span class="field-value">${scheduler.last_scan ? relativeTime(scheduler.last_scan) : "Never"}</span>
        </div>
        ${scheduler.auto_scan_enabled ? b2`
              <div class="field-row">
                <div class="field-label">Next scan</div>
                <span class="field-value">${nextScanText}</span>
              </div>
            ` : null}
        ${scheduler.last_scan_error_summary ? b2`
              <div class="field-row">
                <div class="field-label">Last scan failure</div>
                <span class="field-value">${scheduler.last_scan_error_summary}</span>
              </div>
            ` : null}
        <div class="field-row">
          <div class="field-label">Connector heartbeat interval</div>
          <span class="field-value">Every ${scheduler.connector_heartbeat_interval_seconds} seconds</span>
        </div>
      </hamie-card>
    `;
  }
  _onEdit() {
    if (!this._fallbackPath) return;
    history.pushState(null, "", this._fallbackPath);
    window.dispatchEvent(new CustomEvent("location-changed"));
  }
  async _onOllamaSaved() {
    this._editingOllama = false;
    await this._load();
  }
  render() {
    if (this._error) {
      return b2`<hamie-empty tone="unavailable" heading="Settings are unavailable" description=${this._error}></hamie-empty>`;
    }
    if (!this._config) {
      return b2`<hamie-loading .lines=${6}></hamie-loading>`;
    }
    const sections = Object.entries(this._config.sections || {}).filter(
      ([, section]) => section.fields && section.fields.length > 0
    );
    return b2`
      <hamie-page-header heading="Settings" subtitle="Current configuration (revision ${this._config.revision})">
        <div slot="actions">
          <hamie-button variant="primary" size="sm" @click=${this._onEdit}>
            <ha-icon icon="mdi:open-in-new"></ha-icon> Edit in Home Assistant
          </hamie-button>
        </div>
      </hamie-page-header>

      <div class="sections">
        ${this._renderScheduler()}
        ${sections.map(
      ([sectionId, section]) => sectionId === "ollama" ? b2`
                <hamie-card padding="md">
                  <hamie-section heading="${SECTION_LABELS.ollama}">
                    ${this._editingOllama ? null : b2`<hamie-button slot="action" variant="secondary" size="sm" @click=${() => this._editingOllama = true}>Edit</hamie-button>`}
                  </hamie-section>
                  ${this._editingOllama ? b2`
                        <hamie-ai-provider-editor
                          .hass=${this.hass}
                          @hamie-ai-provider-saved=${this._onOllamaSaved}
                          @hamie-ai-provider-cancelled=${() => this._editingOllama = false}
                        ></hamie-ai-provider-editor>
                      ` : section.fields.map((field) => {
        const value = section.values?.[field.key];
        return b2`
                          <div class="field-row">
                            <div class="field-label">
                              ${field.label}
                              ${field.description ? b2`<p class="field-description">${field.description}</p>` : null}
                            </div>
                            ${field.secret ? b2`<hamie-status status="unknown" label="Hidden for security"></hamie-status>` : b2`<span class="field-value">${formatValue(field, value)}</span>`}
                          </div>
                        `;
      })}
                </hamie-card>
              ` : b2`
                <hamie-card padding="md">
                  <hamie-section heading="${SECTION_LABELS[sectionId] || sectionId}"></hamie-section>
                  ${section.fields.map((field) => {
        const value = section.values?.[field.key];
        return b2`
                      <div class="field-row">
                        <div class="field-label">
                          ${field.label}
                          ${field.description ? b2`<p class="field-description">${field.description}</p>` : null}
                        </div>
                        ${field.secret ? b2`<hamie-status status="unknown" label="Hidden for security"></hamie-status>` : b2`<span class="field-value">${formatValue(field, value)}</span>`}
                      </div>
                    `;
      })}
                </hamie-card>
              `
    )}
      </div>
    `;
  }
};
if (!customElements.get("hamie-view-settings")) {
  customElements.define("hamie-view-settings", HamieViewSettings);
}

// hamie/frontend/hamie-app.js
var ADVANCED_ITEMS = [
  { id: "recommendations", label: "Recommendations", icon: "mdi:lightbulb-outline" },
  { id: "remediation", label: "Remediation Queue", icon: "mdi:wrench-check-outline" },
  { id: "dependencies", label: "Dependencies", icon: "mdi:graph-outline" },
  { id: "security", label: "Security", icon: "mdi:shield-outline" },
  { id: "connectors", label: "Connectors", icon: "mdi:swap-horizontal" },
  { id: "groups", label: "Groups", icon: "mdi:folder-multiple-outline" },
  { id: "findings", label: "Raw Findings", icon: "mdi:file-search-outline" }
];
var NAV_ITEMS = [
  { id: "overview", label: "Home", icon: "mdi:home-outline" },
  { id: "incidents", label: "Incidents", icon: "mdi:alert-decagram-outline" },
  { id: "review", label: "Review", icon: "mdi:clipboard-check-outline" },
  { id: "health", label: "Systems", icon: "mdi:view-grid-outline" },
  { id: "audit", label: "Activity", icon: "mdi:timeline-clock-outline" },
  { id: "search", label: "Search", icon: "mdi:magnify-expand", dividerBefore: true },
  { id: "settings", label: "Settings", icon: "mdi:cog-outline" },
  { id: "advanced", label: "Advanced", icon: "mdi:tune-variant", children: ADVANCED_ITEMS }
];
var ROUTE_IDS = /* @__PURE__ */ new Set([...NAV_ITEMS.filter((item) => !item.children).map((item) => item.id), ...ADVANCED_ITEMS.map((item) => item.id), "ai"]);
var NARROW_BREAKPOINT = 870;
var HamieApp = class extends i4 {
  static properties = {
    hass: { attribute: false },
    _activeId: { state: true },
    _sidebarOpen: { state: true },
    _narrow: { state: true },
    _overview: { state: true },
    _focusFindingId: { state: true },
    _focusDependencyFindingId: { state: true },
    _focusDependencyGroupId: { state: true },
    _focusDependencyLabel: { state: true },
    _focusGroupId: { state: true },
    _focusGroupTitle: { state: true },
    _focusQueueStatus: { state: true },
    _queueActionableCount: { state: true }
  };
  static styles = [
    designTokens,
    i`
      :host {
        display: flex;
        height: 100%;
        overflow: hidden;
        font-family: var(--hamie-font-body);
        font-size: var(--hamie-text-small);
        color: var(--hamie-text-primary);
        background: var(--hamie-surface-app);
        position: relative;
      }
      main {
        flex: 1;
        overflow-y: auto;
        min-width: 0;
      }
      .menu-button {
        display: none;
        position: absolute;
        top: var(--hamie-space-3);
        left: var(--hamie-space-3);
        z-index: 2;
        background: var(--hamie-surface-card);
        border: 1px solid var(--hamie-border-hairline);
        border-radius: var(--hamie-radius-md);
        width: 36px;
        height: 36px;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        color: var(--hamie-text-primary);
      }
      .scrim {
        display: none;
      }
      :host([narrow]) .menu-button {
        display: flex;
      }
      :host([narrow]) hamie-sidebar {
        position: absolute;
        inset: 0 auto 0 0;
        z-index: 3;
        transform: translateX(-100%);
        transition: transform var(--hamie-motion-normal) var(--hamie-motion-ease);
        box-shadow: var(--hamie-elevation-popover);
      }
      :host([narrow][sidebar-open]) hamie-sidebar {
        transform: translateX(0);
      }
      :host([narrow][sidebar-open]) .scrim {
        display: block;
        position: absolute;
        inset: 0;
        background: rgba(0, 0, 0, 0.5);
        z-index: 2;
      }
      :host([narrow]) main {
        padding-top: var(--hamie-space-8);
      }
    `
  ];
  constructor() {
    super();
    this._activeId = this._routeFromLocation();
    this._sidebarOpen = false;
    this._narrow = false;
    this._mediaQuery = null;
  }
  _routeFromLocation() {
    const route = window.location.hash.replace(/^#\/?/, "");
    return ROUTE_IDS.has(route) ? route : "overview";
  }
  _syncRoute = () => {
    this._activeId = this._routeFromLocation();
    this._sidebarOpen = false;
  };
  _activate(id, { history: history2 = true } = {}) {
    if (!ROUTE_IDS.has(id)) return;
    this._activeId = id;
    this._sidebarOpen = false;
    if (history2 && window.location.hash !== `#${id}`) window.history.pushState({ hamieRoute: id }, "", `#${id}`);
  }
  connectedCallback() {
    super.connectedCallback();
    this._mediaQuery = window.matchMedia(`(max-width: ${NARROW_BREAKPOINT}px)`);
    this._onMediaChange = () => {
      this._narrow = this._mediaQuery.matches;
      if (!this._narrow) this._sidebarOpen = false;
    };
    window.addEventListener("popstate", this._syncRoute);
    window.addEventListener("hashchange", this._syncRoute);
    this._mediaQuery.addEventListener("change", this._onMediaChange);
    this._onMediaChange();
    this._loadOverview();
    this._subscribeLiveUpdates();
  }
  // One canonical live-state channel (mission: connector heartbeat, auto
  // scan, and other background-initiated changes must reach the UI
  // without a manual refresh, and without every view inventing its own
  // polling loop). Backend: RuntimeProjection already fans out a change
  // notification on every scan sync / connector status update / AI
  // coverage change (see runtime_projection.py's _notify call sites);
  // hamie/updates/subscribe (presentation/api.py) is a thin WS
  // subscription over that exact fan-out. This app shell is the single
  // subscriber; it refreshes its own sidebar/footer state directly and
  // rebroadcasts a `hamie-live-update` window event so any mounted view
  // can refresh itself the same way it already refreshes after its own
  // user-triggered actions -- no bespoke per-view polling.
  async _subscribeLiveUpdates() {
    if (!this.hass?.connection?.subscribeMessage) return;
    try {
      this._unsubscribeLiveUpdates = await this.hass.connection.subscribeMessage(
        () => {
          this._loadOverview();
          window.dispatchEvent(new CustomEvent("hamie-live-update"));
        },
        { type: "hamie/updates/subscribe" }
      );
    } catch {
      this._liveUpdateFallback = window.setInterval(() => {
        this._loadOverview();
        window.dispatchEvent(new CustomEvent("hamie-live-update"));
      }, 45e3);
    }
  }
  async _loadOverview() {
    if (!this.hass) return;
    try {
      const [overview, queue] = await Promise.all([
        this.hass.callWS({ type: "hamie/explorer/overview" }),
        this.hass.callWS({ type: "hamie/remediation/queue/list", offset: 0, limit: 1 }).catch(() => null)
      ]);
      this._overview = overview;
      const counts = queue?.section_counts || {};
      this._queueActionableCount = (counts.ready_for_review || 0) + (counts.awaiting_approval || 0) + (counts.ready_to_execute || 0);
    } catch {
      this._overview = null;
      this._queueActionableCount = 0;
    }
  }
  // Production defect fix: this was previously only ever called once, in
  // connectedCallback -- fine for the initial sidebar badge/status render,
  // but it meant the sidebar's own "last scan" state froze at whatever it
  // was when the panel was first opened and never updated again for the
  // rest of that browser session, even after the user ran a fresh scan or
  // cleanup pass from the Overview view (which reloads its own, separate
  // `_overview` state correctly). Two UI surfaces independently deriving
  // "last scan" from the same WS command but refreshed on different
  // triggers is exactly the contradiction ("last scan completed Just now"
  // at the top vs "Scanned 3d ago" in the sidebar) seen live. The
  // `hamie-data-changed` listener on `<main>` above re-runs this any time
  // a child view finishes a scan or cleanup pass, so both surfaces read
  // the same fresh state.
  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("popstate", this._syncRoute);
    window.removeEventListener("hashchange", this._syncRoute);
    this._mediaQuery?.removeEventListener("change", this._onMediaChange);
    this._unsubscribeLiveUpdates?.();
    this._unsubscribeLiveUpdates = null;
    if (this._liveUpdateFallback) {
      window.clearInterval(this._liveUpdateFallback);
      this._liveUpdateFallback = null;
    }
  }
  updated(changed) {
    if (changed.has("_narrow")) this.toggleAttribute("narrow", this._narrow);
    if (changed.has("_sidebarOpen")) this.toggleAttribute("sidebar-open", this._sidebarOpen);
  }
  _onNavigate(event) {
    this._activate(event.detail.id);
    if (event.detail.id === "remediation") {
      this._focusQueueStatus = event.detail.status || null;
    }
  }
  // Recommendations' "View finding" button dispatches this (findingId
  // in detail) -- previously unhandled anywhere, so the button did
  // nothing at all. Navigates to Findings and asks it to focus on that
  // one finding.
  _onNavigateFinding(event) {
    this._activate("findings");
    this._sidebarOpen = false;
    this._focusFindingId = event.detail.findingId;
  }
  // Findings' "View dependency graph" button (findingId + entityId in
  // detail) and Groups' per-group graph action (groupId in detail) both
  // dispatch this. Navigates to Dependencies and asks it to load the
  // real per-finding/per-group impact graph instead of its default
  // integration-breakdown view.
  _onNavigateDependencies(event) {
    this._activate("dependencies");
    this._sidebarOpen = false;
    if (event.detail.groupId) {
      this._focusDependencyGroupId = event.detail.groupId;
      this._focusDependencyFindingId = null;
      this._focusDependencyLabel = null;
    } else {
      this._focusDependencyFindingId = event.detail.findingId;
      this._focusDependencyGroupId = null;
      this._focusDependencyLabel = event.detail.entityId;
    }
  }
  // Groups' "View Findings" button dispatches this (groupId + groupTitle
  // in detail) -- the real Groups -> Findings handoff (matches the
  // legacy panel's "Open Group" button).
  _onNavigateFindingsGroup(event) {
    this._activate("findings");
    this._sidebarOpen = false;
    this._focusGroupId = event.detail.groupId;
    this._focusGroupTitle = event.detail.groupTitle;
  }
  _toggleSidebar() {
    this._sidebarOpen = !this._sidebarOpen;
  }
  // NOTE: this element is a view router, not a generic content host -- it
  // has no bare <slot>. Only known view ids render (via this method);
  // arbitrary light-DOM children passed to <hamie-app> are never
  // projected anywhere and won't inherit design tokens. Isolated
  // component-level tests need their own minimal token-applying host
  // (see tests/frontend's token-host.js pattern), not this element.
  _renderView() {
    if (this._activeId === "overview") {
      return b2`<hamie-view-overview .hass=${this.hass}></hamie-view-overview>`;
    }
    if (this._activeId === "findings") {
      return b2`<hamie-view-findings
        .hass=${this.hass}
        .focusFindingId=${this._focusFindingId}
        .focusGroupId=${this._focusGroupId}
        .focusGroupTitle=${this._focusGroupTitle}
      ></hamie-view-findings>`;
    }
    if (this._activeId === "incidents") {
      return b2`<hamie-view-incidents .hass=${this.hass} @hamie-navigate-finding=${this._onNavigateFinding}></hamie-view-incidents>`;
    }
    if (this._activeId === "review") {
      return b2`<hamie-view-review .hass=${this.hass} @hamie-navigate=${this._onNavigate} @hamie-navigate-finding=${this._onNavigateFinding}></hamie-view-review>`;
    }
    if (this._activeId === "search") {
      return b2`<hamie-view-search .hass=${this.hass} @hamie-navigate-finding=${this._onNavigateFinding} @hamie-navigate-findings-group=${this._onNavigateFindingsGroup}></hamie-view-search>`;
    }
    if (this._activeId === "recommendations") {
      return b2`<hamie-view-recommendations .hass=${this.hass} @hamie-navigate-finding=${this._onNavigateFinding}></hamie-view-recommendations>`;
    }
    if (this._activeId === "health") {
      return b2`<hamie-view-health .hass=${this.hass}></hamie-view-health>`;
    }
    if (this._activeId === "ai") {
      return b2`<hamie-view-intelligence .hass=${this.hass} @hamie-navigate=${this._onNavigate}></hamie-view-intelligence>`;
    }
    if (this._activeId === "security") {
      return b2`<hamie-view-security .hass=${this.hass}></hamie-view-security>`;
    }
    if (this._activeId === "dependencies") {
      return b2`<hamie-view-dependencies
        .hass=${this.hass}
        .focusFindingId=${this._focusDependencyFindingId}
        .focusGroupId=${this._focusDependencyGroupId}
        .focusLabel=${this._focusDependencyLabel}
      ></hamie-view-dependencies>`;
    }
    if (this._activeId === "remediation") {
      return b2`<hamie-view-remediation .hass=${this.hass} .focusStatus=${this._focusQueueStatus}></hamie-view-remediation>`;
    }
    if (this._activeId === "groups") {
      return b2`<hamie-view-groups .hass=${this.hass}></hamie-view-groups>`;
    }
    if (this._activeId === "connectors") {
      return b2`<hamie-view-connectors .hass=${this.hass}></hamie-view-connectors>`;
    }
    if (this._activeId === "audit") {
      return b2`<hamie-view-audit .hass=${this.hass}></hamie-view-audit>`;
    }
    if (this._activeId === "settings") {
      return b2`<hamie-view-settings .hass=${this.hass}></hamie-view-settings>`;
    }
    const item = NAV_ITEMS.find((entry) => entry.id === this._activeId);
    return b2`
      <hamie-empty
        tone="unavailable"
        heading="${item?.label || "This view"} is not yet migrated to UI 3.0"
        description="Still served by the current production panel until this screen is built and validated against the Figma specification."
      ></hamie-empty>
    `;
  }
  // Only counts with real decision significance are badged (spec
  // section 4): open findings and actionable Review Queue work. Never
  // Recommendations merely because historical AI recommendations exist
  // -- most are already reviewed/stale, so that count doesn't mean
  // "action needed" the way the other two genuinely do. Badges are
  // simply absent when data hasn't loaded yet or a count is zero, never
  // a placeholder number.
  _navItemsWithBadges() {
    const overview = this._overview;
    return NAV_ITEMS.map((item) => {
      if (item.id === "incidents" && overview?.active_incidents) {
        return { ...item, badge: overview.active_incidents };
      }
      if (item.id === "advanced" && this._queueActionableCount) {
        return { ...item, badge: this._queueActionableCount };
      }
      return item;
    });
  }
  _footerStatus() {
    if (!this._overview) return { text: "Loading\u2026", ok: true };
    const { operational_health: health, coverage, last_scan: lastScan } = this._overview;
    const ok = health == null || typeof health === "number" && health >= 90 && coverage === "complete";
    const scanText = lastScan ? `Scanned ${relativeTime(lastScan)}` : "No scan yet";
    return { text: `${ok ? "All systems operational" : "Needs attention"} \xB7 ${scanText}`, ok };
  }
  render() {
    const status = this._footerStatus();
    return b2`
      <button class="menu-button" @click=${this._toggleSidebar} aria-label="Toggle navigation">
        <ha-icon icon="mdi:menu"></ha-icon>
      </button>
      <div class="scrim" @click=${this._toggleSidebar}></div>
      <hamie-sidebar
        .items=${this._navItemsWithBadges()}
        .activeId=${this._activeId}
        .statusText=${status.text}
        .statusOk=${status.ok}
        @hamie-navigate=${this._onNavigate}
      >
        <span slot="version">UI 3.1</span>
      </hamie-sidebar>
      <!--
        hamie-navigate is bound here too, not just on hamie-sidebar:
        Lit's @event binding attaches directly to that one element, and
        <main> (a sibling of hamie-sidebar, not an ancestor of it) never
        passes bubbled events through it. Any view rendered inside main
        that dispatches hamie-navigate (e.g. Overview's "View in
        Groups") would otherwise silently do nothing -- the same class
        of dead-navigation bug already found and fixed for
        hamie-navigate-finding earlier this pass. hamie-navigate-finding,
        hamie-navigate-dependencies, and hamie-navigate-findings-group
        are bound here for the same reason, delegated once at this level
        rather than per-view.
      -->
      <main
        @hamie-navigate=${this._onNavigate}
        @hamie-navigate-finding=${this._onNavigateFinding}
        @hamie-navigate-dependencies=${this._onNavigateDependencies}
        @hamie-navigate-findings-group=${this._onNavigateFindingsGroup}
        @hamie-data-changed=${this._loadOverview}
      >
        ${this._renderView()}
      </main>
    `;
  }
};
if (!customElements.get("hamie-app")) {
  customElements.define("hamie-app", HamieApp);
}
export {
  HamieApp
};
/*! Bundled license information:

@lit/reactive-element/css-tag.js:
  (**
   * @license
   * Copyright 2019 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/reactive-element.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/lit-html.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-element/lit-element.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/is-server.js:
  (**
   * @license
   * Copyright 2022 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/directive.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/directive-helpers.js:
  (**
   * @license
   * Copyright 2020 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/directives/repeat.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/async-directive.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/directives/ref.js:
  (**
   * @license
   * Copyright 2020 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)
*/
