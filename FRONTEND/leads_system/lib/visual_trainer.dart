import 'dart:async';
import 'package:flutter/material.dart';
import 'package:desktop_webview_window/desktop_webview_window.dart';

// ─────────────────────────────────────────────────────────────────────────────
// VisualTrainerPage — OS-window element inspector (desktop_webview_window)
//
// Flow:
//   1. Opens the target URL in a separate WebView2 OS window.
//   2. Injects _inspectorJs which:
//        • Blocks ALL link navigation and form submits.
//        • On hover: highlights the richest ancestor element in green.
//        • On click: walks up with findBestTarget(), locks the element in
//          yellow, stores its CSS selector + outerHTML in window globals.
//   3. Dart polls window.__leadsSelector / window.__leadsHtml every 400 ms.
//   4. When the user presses "USE THIS ELEMENT & RETURN", pops with:
//          "<css_selector>|<outerHTML>"
//      ExecutionPage splits on the first '|'.
// ─────────────────────────────────────────────────────────────────────────────

const _inspectorJs = r"""
(function() {
  // ── SETUP FUNCTION — runs immediately AND deferred to ensure DOM is ready ──
  // The key problem: addScriptToExecuteOnDocumentCreated can fire before
  // document.body exists. We run setup() now AND on DOMContentLoaded so
  // whichever fires second wins without duplicating listeners.
  //
  // The re-inject timer calls this every 2s to survive in-page navigation.
  // We do NOT use a global __leadsInjected guard here — each re-injection
  // must be able to re-attach listeners on a fresh page.

  function setup() {
    if (!document.body) return; // body not ready yet — DOMContentLoaded will retry

    // ── LAYER 1: pointer-events:none kills browser navigation on <a> clicks ──
    // The browser hit-test engine sees pointer-events:none and treats <a> as
    // transparent. Clicks pass through to the parent. findBestTarget() then
    // walks UP to recover the <a> with its href and classes.
    if (!document.getElementById('__nav_kill')) {
      var ks = document.createElement('style');
      ks.id  = '__nav_kill';
      ks.textContent =
        'a, button, [role="button"], input[type="submit"], input[type="button"] {' +
        '  pointer-events: none !important; }';
      document.head.appendChild(ks);
    }

    // ── LAYER 3: beforeunload safety net ─────────────────────────────────────
    if (!window.__leadsBeforeUnload) {
      window.__leadsBeforeUnload = true;
      window.addEventListener('beforeunload', function(e) {
        e.preventDefault(); e.returnValue = ''; return '';
      });
    }

    // ── Inspector state ───────────────────────────────────────────────────────
    if (window.__leadsListening) return; // listeners already attached this page
    window.__leadsListening = true;
    window.__leadsSelector  = window.__leadsSelector  || '';
    window.__leadsHtml      = window.__leadsHtml      || '';
    window.__leadsLocked    = window.__leadsLocked    || false;

    // ── findBestTarget ────────────────────────────────────────────────────────
    // pointer-events:none means the click lands on an inner child (a <span>).
    // Walk UP to the richest meaningful ancestor that has scraping value.
    var INLINE = {SPAN:1,STRONG:1,EM:1,B:1,I:1,SMALL:1,LABEL:1,ABBR:1,
                  CITE:1,CODE:1,MARK:1,SUB:1,SUP:1,SVG:1,PATH:1,IMG:1,
                  BR:1,U:1,S:1,KBD:1,VAR:1,TIME:1};

    function findBestTarget(node) {
      var n = node, steps = 0, MAX = 8;
      while (n && n !== document.body && n.nodeType === 1 && steps < MAX) {
        var tag = n.tagName;
        if (tag === 'A') return n;
        if (tag === 'LI' || tag === 'TR' || tag === 'TD' || tag === 'TH') return n;
        if (tag === 'ARTICLE' || tag === 'SECTION' || tag === 'FIGURE') return n;
        if (tag === 'DIV' || tag === 'P' || tag === 'HEADER' ||
            tag === 'FOOTER' || tag === 'ASIDE' || tag === 'NAV') {
          if (n.id || (n.dataset && Object.keys(n.dataset).length) ||
              (n.children && n.children.length >= 2)) return n;
        }
        if (INLINE[tag]) { n = n.parentElement; steps++; continue; }
        if (steps > 0) return n;
        n = n.parentElement; steps++;
      }
      return node;
    }

    // ── CSS path builder ──────────────────────────────────────────────────────
    function cssPath(el) {
      if (!el || el.nodeType !== 1) return '';
      var path = [];
      while (el && el.nodeType === 1 && el.tagName.toLowerCase() !== 'html') {
        var s = el.tagName.toLowerCase();
        if (el.id) { s += '#' + el.id; path.unshift(s); break; }
        if (el.className) {
          var cls = Array.from(el.classList)
            .filter(function(c){ return c && !/^__leads/.test(c); })
            .slice(0, 3).join('.');
          if (cls) s += '.' + cls;
        }
        var sibs = el.parentNode
          ? Array.from(el.parentNode.children).filter(function(x){
              return x.tagName === el.tagName; })
          : [];
        if (sibs.length > 1)
          s += ':nth-child(' + (Array.from(el.parentNode.children).indexOf(el)+1) + ')';
        path.unshift(s);
        el = el.parentNode;
      }
      return path.join(' > ');
    }

    // ── Inspector UI (idempotent) ─────────────────────────────────────────────
    if (!document.getElementById('__leads_style')) {
      var st = document.createElement('style');
      st.id  = '__leads_style';
      st.textContent =
        '.__lh{outline:3px solid #00ff88!important;outline-offset:2px!important;' +
          'cursor:crosshair!important;background:rgba(0,255,136,0.07)!important}' +
        '.__ll{outline:3px solid #ffcc00!important;outline-offset:2px!important;' +
          'background:rgba(255,204,0,0.07)!important}' +
        '#__lb{position:fixed;top:12px;right:12px;z-index:2147483647;' +
          'background:#ffcc00;color:#000;font:bold 12px monospace;padding:7px 14px;' +
          'border-radius:8px;pointer-events:none;display:none;' +
          'box-shadow:0 2px 12px rgba(0,0,0,.5);max-width:60vw;' +
          'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
        '#__lban{position:fixed;bottom:0;left:0;right:0;z-index:2147483646;' +
          'background:rgba(0,0,0,.9);color:#00ff88;font:12px monospace;' +
          'padding:10px 16px;text-align:center;pointer-events:none}';
      document.head.appendChild(st);
    }

    if (!document.getElementById('__lb')) {
      var b = document.createElement('div'); b.id = '__lb';
      document.body.appendChild(b);
    }
    if (!document.getElementById('__lban')) {
      var bn = document.createElement('div'); bn.id = '__lban';
      bn.textContent = '🔍  INSPECTOR ON — hover to highlight, click to lock';
      document.body.appendChild(bn);
    }

    var badge  = document.getElementById('__lb');
    var banner = document.getElementById('__lban');
    var hovered = null;

    // ── Hover ─────────────────────────────────────────────────────────────────
    document.addEventListener('mouseover', function(e) {
      if (window.__leadsLocked) return;
      var best = findBestTarget(e.target);
      if (hovered && hovered !== best) hovered.classList.remove('__lh');
      hovered = best;
      if (hovered) hovered.classList.add('__lh');
    }, true);

    document.addEventListener('mouseout', function(e) {
      if (window.__leadsLocked) return;
      if (!e.relatedTarget || (hovered && !hovered.contains(e.relatedTarget))) {
        if (hovered) hovered.classList.remove('__lh');
        hovered = null;
      }
    }, true);

    // ── LAYER 2: mousedown — before browser finalises navigation ─────────────
    document.addEventListener('mousedown', function(e) {
      e.preventDefault();
      e.stopImmediatePropagation();

      var prev = document.querySelector('.__ll');
      if (prev) prev.classList.remove('__ll');
      if (hovered) hovered.classList.remove('__lh');

      var target = findBestTarget(e.target);
      target.classList.add('__ll');

      var sel  = cssPath(target);
      var html = (target.outerHTML || '').substring(0, 3000);

      window.__leadsSelector = sel;
      window.__leadsHtml     = html;
      window.__leadsLocked   = true;

      var short = target.tagName.toLowerCase();
      if (target.className) {
        var fc = Array.from(target.classList)
          .filter(function(c){ return !/^__leads/.test(c); })[0];
        if (fc) short += '.' + fc;
      }
      badge.textContent = '✓ LOCKED: ' + short;
      badge.style.display = 'block';
      banner.textContent  = '✓  ' + sel + ' — click RE-PICK to choose again';
    }, true);

    // Block click as secondary defence
    document.addEventListener('click', function(e) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }, true);

    // Block form submits
    document.addEventListener('submit', function(e) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }, true);

    // Allow right-click (DevTools)
    document.addEventListener('contextmenu', function(e) {
      e.stopImmediatePropagation();
    }, true);
  } // end setup()

  // Run now (body might already exist on re-inject) AND on DOMContentLoaded
  setup();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      // Reset per-page flag so listeners re-attach on fresh page
      window.__leadsListening = false;
      setup();
    });
  }
})();
""";

// ─────────────────────────────────────────────────────────────────────────────
// Widget
// ─────────────────────────────────────────────────────────────────────────────

class VisualTrainerPage extends StatefulWidget {
  final String taskId;
  final String domain;        // URL or keyword — normalised before launch
  final String captureLabel;  // Shown in appbar + instructions

  const VisualTrainerPage({
    super.key,
    required this.taskId,
    required this.domain,
    this.captureLabel = 'Element',
  });

  @override
  State<VisualTrainerPage> createState() => _VisualTrainerPageState();
}

class _VisualTrainerPageState extends State<VisualTrainerPage> {
  late final TextEditingController _urlCtrl;

  // Manual-entry mode toggle (false = webview inspector, true = type-it-in)
  bool _manualMode = false;

  // Manual input: site URL the user types directly
  late final TextEditingController _manualUrlCtrl;

  // Manual input: raw outerHTML of the element they want to target
  final TextEditingController _manualElementCtrl = TextEditingController();

  // Manual input: raw outerHTML of the pagination button / next-page link
  final TextEditingController _manualPaginationCtrl = TextEditingController();

  Webview? _webview;
  bool     _webviewOpen = false;
  bool     _loading     = false;
  String?  _error;

  String?  _liveSelector;
  String?  _liveHtml;

  Timer?   _pollTimer;
  Timer?   _injectTimer;

  // ── URL normaliser ──────────────────────────────────────────────────────────
  static String _normalise(String raw) {
    final t = raw.trim();
    if (t.isEmpty) return '';
    if (t.startsWith('http://') || t.startsWith('https://')) return t;
    if (!t.contains(' ') && t.contains('.')) return 'https://$t';
    return 'https://www.google.com/search?q=${Uri.encodeComponent(t)}';
  }

  @override
  void initState() {
    super.initState();
    _urlCtrl = TextEditingController(text: _normalise(widget.domain));

    // Seed the manual URL field with the same normalised value so it's
    // pre-filled even if the user switches to manual mode immediately.
    _manualUrlCtrl = TextEditingController(text: _normalise(widget.domain));
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _injectTimer?.cancel();
    _webview?.close();
    _urlCtrl.dispose();
    
    _manualUrlCtrl.dispose();
    _manualElementCtrl.dispose();
    _manualPaginationCtrl.dispose();
    
    super.dispose();
  }

  // ── Open WebView2 window ────────────────────────────────────────────────────
  Future<void> _openSiteInWindow() async {
    final url = _normalise(_urlCtrl.text);
    if (url.isEmpty) {
      setState(() => _error = 'Please enter a valid URL.');
      return;
    }

    _pollTimer?.cancel();
    _injectTimer?.cancel();
    if (_webviewOpen) _webview?.close();

    setState(() {
      _loading = true; _error = null;
      _liveSelector = null; _liveHtml = null;
    });

    try {
      final webview = await WebviewWindow.create(
        configuration: CreateConfiguration(
          title: 'Inspector ✦ ${widget.captureLabel}',
          titleBarHeight: 40,
        ),
      );

      // addScriptToExecuteOnDocumentCreated returns void — do NOT await it.
      webview.addScriptToExecuteOnDocumentCreated(_inspectorJs);
      webview.launch(url);

      // Tear down BEFORE starting timers so there is no race where a tick
      // fires against an already-destroyed window id (→ PlatformException).
      webview.onClose.then((_) {
        _pollTimer?.cancel();
        _injectTimer?.cancel();
        _pollTimer   = null;
        _injectTimer = null;
        if (mounted) setState(() { _webviewOpen = false; _webview = null; });
      });

      setState(() { _webview = webview; _webviewOpen = true; _loading = false; });

      // Re-inject every 2 s to survive in-page navigation.
      // Reset __leadsListening first so setup() actually re-attaches listeners
      // on the fresh page — without this the guard causes re-injection to no-op.
      _injectTimer = Timer.periodic(const Duration(seconds: 2), (_) async {
        final wv = _webview;
        if (wv == null) { _injectTimer?.cancel(); return; }
        try {
          await wv.evaluateJavaScript('window.__leadsListening = false;');
          await wv.evaluateJavaScript(_inspectorJs);
        } on Exception catch (e) {
          if (e.toString().contains('can not find webview')) {
            _injectTimer?.cancel(); _injectTimer = null;
            if (mounted) setState(() { _webviewOpen = false; _webview = null; });
          }
        }
      });

      // Poll globals every 400 ms
      _pollTimer = Timer.periodic(const Duration(milliseconds: 400), (_) async {
        final wv = _webview;
        if (wv == null) { _pollTimer?.cancel(); return; }
        try {
          final rawSel  = await wv.evaluateJavaScript('window.__leadsSelector||""');
          final rawHtml = await wv.evaluateJavaScript('window.__leadsHtml||""');
          if (!mounted) return;
          final sel  = (rawSel  ?? '').toString().replaceAll(RegExp(r'^"|"$'), '').trim();
          final html = (rawHtml ?? '').toString().replaceAll(RegExp(r'^"|"$'), '').trim();
          if (sel.isNotEmpty && sel != _liveSelector) {
            setState(() { _liveSelector = sel; _liveHtml = html; });
          }
        } on Exception catch (e) {
          if (e.toString().contains('can not find webview')) {
            _pollTimer?.cancel(); _pollTimer = null;
            if (mounted) setState(() { _webviewOpen = false; _webview = null; });
          }
        }
      });

    } catch (e) {
      setState(() {
        _loading = false;
        _error = 'Could not open WebView2: $e\n\n'
            'Ensure the WebView2 Runtime is installed.\n'
            'Download: https://developer.microsoft.com/en-us/microsoft-edge/webview2/';
      });
    }
  }

  // ── Accept selection ────────────────────────────────────────────────────────
  /// Returns "<css_selector>|<outerHTML>" to ExecutionPage.
  void _useSelector() {
    String sel;
    String html;

    if (_manualMode) {
      // Raw HTML exactly as the user pasted it — this is what Groq receives.
      html = _manualElementCtrl.text.trim();
      if (html.isEmpty) return;

      // DEBUG — print the raw text from each controller exactly as Flutter
      // received it from the user.  The === delimiters let you see if the
      // string was truncated, had its whitespace stripped, or arrived empty.
      debugPrint('');
      debugPrint('╔══════════════════════════════════════════════════════════');
      debugPrint('║ [VisualTrainer] _useSelector → MANUAL MODE PAYLOAD');
      debugPrint('╠══════════════════════════════════════════════════════════');
      debugPrint('║ ELEMENT HTML (${html.length} chars):');
      // Print in 200-char chunks so long HTML is never cut off by the console
      for (int _i = 0; _i < html.length; _i += 200) {
        debugPrint('║   ${html.substring(_i, _i + 200 > html.length ? html.length : _i + 200)}');
      }
      debugPrint('╠══════════════════════════════════════════════════════════');
      final _pagDebug = _manualPaginationCtrl.text.trim();
      debugPrint('║ PAGINATION HTML (${_pagDebug.length} chars):');
      for (int _i = 0; _i < _pagDebug.length; _i += 200) {
        debugPrint('║   ${_pagDebug.substring(_i, _i + 200 > _pagDebug.length ? _pagDebug.length : _i + 200)}');
      }
      debugPrint('╠══════════════════════════════════════════════════════════');
      debugPrint('║ SENTINEL SELECTOR: __manual__');
      debugPrint('╚══════════════════════════════════════════════════════════');
      debugPrint('');

      // Use a sentinel selector so the backend knows Groq must derive the
      // real selector from element_html, not from this string.
      // "__manual__" is checked in listings_site.py (Patch 3 below).
      sel = '__manual__';

      final pag = _manualPaginationCtrl.text.trim();
      
      // DEBUG — print the exact string being returned to ExecutionPage.
      // This lets you verify the pipe-delimited format is intact and that
      // the full HTML (not just the first word/class) is in the payload.
      final _returnStr = '$sel|$html||$pag';
      debugPrint('');
      debugPrint('╔══════════════════════════════════════════════════════════');
      debugPrint('║ [VisualTrainer] Navigator.pop PAYLOAD (${_returnStr.length} chars total)');
      debugPrint('║ Format: <sentinel>|<elementHtml>||<paginationHtml>');
      debugPrint('╠══════════════════════════════════════════════════════════');
      for (int _i = 0; _i < _returnStr.length; _i += 200) {
        debugPrint('║ ${_returnStr.substring(_i, _i + 200 > _returnStr.length ? _returnStr.length : _i + 200)}');
      }
      debugPrint('╚══════════════════════════════════════════════════════════');
      debugPrint('');
      Navigator.pop(context, _returnStr); // replace the old Navigator.pop line
      
    } else {
      // Webview mode: use the inspector-captured values as before.
      sel  = _liveSelector ?? '';
      html = _liveHtml     ?? '';
      if (sel.isEmpty) return;
      _pollTimer?.cancel();
      _injectTimer?.cancel();
      _webview?.close();
      Navigator.pop(context, '$sel|$html');
    }
  }
  
  // ── Clear lock (re-pick) ────────────────────────────────────────────────────
  Future<void> _clearLock() async {
    try {
      await _webview?.evaluateJavaScript(
        'window.__leadsSelector=""; window.__leadsHtml=""; window.__leadsLocked=false;'
        'var p=document.querySelector(".__ll"); if(p) p.classList.remove("__ll");'
        'var b=document.getElementById("__lb"); if(b) b.style.display="none";'
        'var n=document.getElementById("__lban"); if(n) n.textContent="🔍  INSPECTOR — hover an element, click to lock it";',
      );
    } catch (_) {}
    setState(() { _liveSelector = null; _liveHtml = null; });
  }

  // ── Build ───────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final hasSelector = (_liveSelector ?? '').isNotEmpty;

    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.grey[900],
        foregroundColor: Colors.white,
        title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Capture: ${widget.captureLabel}',
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold)),
          Text(widget.domain,
              style: const TextStyle(fontSize: 11, color: Colors.white54),
              overflow: TextOverflow.ellipsis),
        ]),
        actions: [
          if (hasSelector)
            TextButton.icon(
              onPressed: _useSelector,
              icon: const Icon(Icons.check_circle, color: Colors.greenAccent),
              label: const Text('USE SELECTOR',
                  style: TextStyle(color: Colors.greenAccent, fontWeight: FontWeight.bold)),
            ),
          const SizedBox(width: 8),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [

          // ── URL bar ──────────────────────────────────────────────────────────
          _header('TARGET URL', Icons.link),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(
              child: TextField(
                controller: _urlCtrl,
                onChanged: (_) => setState(() {}),
                style: const TextStyle(color: Colors.white, fontFamily: 'Courier', fontSize: 13),
                decoration: InputDecoration(
                  hintText: 'https://example.com/listings',
                  hintStyle: const TextStyle(color: Colors.white24),
                  filled: true, fillColor: Colors.grey[900],
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(10),
                      borderSide: const BorderSide(color: Colors.white24)),
                  focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10),
                      borderSide: const BorderSide(color: Colors.blueAccent)),
                  prefixIcon: const Icon(Icons.public, color: Colors.white38),
                  contentPadding: const EdgeInsets.symmetric(vertical: 14),
                ),
              ),
            ),
            const SizedBox(width: 10),
            ElevatedButton.icon(
              onPressed: _loading ? null : _openSiteInWindow,
              icon: _loading
                  ? const SizedBox(width: 16, height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                  : Icon(_webviewOpen ? Icons.refresh : Icons.launch, size: 18),
              label: Text(
                _loading ? 'OPENING…' : _webviewOpen ? 'RELOAD' : 'OPEN INSPECTOR',
                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
              ),
              style: ElevatedButton.styleFrom(
                backgroundColor: _webviewOpen ? Colors.blue : Colors.greenAccent,
                foregroundColor: Colors.black,
                padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 20),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              ),
            ),
          ]),

          if (_error != null) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: Colors.red.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: Colors.red.withValues(alpha: 0.4)),
              ),
              child: Text(_error!, style: const TextStyle(color: Colors.redAccent, fontSize: 12)),
            ),
          ],

          if (_webviewOpen) ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              decoration: BoxDecoration(
                color: Colors.greenAccent.withValues(alpha: 0.07),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.greenAccent.withValues(alpha: 0.3)),
              ),
              child: const Row(children: [
                Icon(Icons.ads_click, color: Colors.greenAccent, size: 14),
                SizedBox(width: 8),
                Expanded(child: Text(
                  'Inspector window is open — hover to highlight, click to lock.',
                  style: TextStyle(color: Colors.greenAccent, fontSize: 11),
                )),
              ]),
            ),
          ],

          const SizedBox(height: 24),

          // ── Instructions (before first open) ─────────────────────────────────
          if (!_webviewOpen && !hasSelector) ...[
            _header('HOW TO USE', Icons.info_outline),
            const SizedBox(height: 10),
            ...[
              'Press OPEN INSPECTOR — the site opens in a separate window.',
              'Hover any element — the richest ancestor glows green.',
              'Click the element to lock it — it turns yellow.',
              'The CSS selector and element HTML appear here automatically.',
              'Click a different element to re-pick at any time.',
            ].asMap().entries.map((e) => _step('${e.key + 1}', e.value)),
          ],

          // ── Live captured element ─────────────────────────────────────────────
          if (_webviewOpen || hasSelector) ...[
            _header('CAPTURED ELEMENT', Icons.ads_click),
            const SizedBox(height: 10),
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 200),
              child: hasSelector ? _lockedCard() : _waitingCard(),
            ),
          ],

          // ── Manual entry toggle ───────────────────────────────────────────────
          // Lets the user skip the webview inspector entirely and paste raw HTML
          // for the element and pagination button directly.
          const SizedBox(height: 20),
          Row(children: [
            const Expanded(
              child: Divider(color: Colors.white12),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Text(
                'OR ENTER MANUALLY',
                style: TextStyle(
                  color: Colors.white24,
                  fontSize: 10,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.1,
                ),
              ),
            ),
            const Expanded(child: Divider(color: Colors.white12)),
          ]),
          const SizedBox(height: 12),

          // Toggle chip that switches between webview and manual mode
          GestureDetector(
            onTap: () => setState(() => _manualMode = !_manualMode),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 180),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              decoration: BoxDecoration(
                color: _manualMode
                    ? Colors.orangeAccent.withValues(alpha: 0.15)
                    : Colors.grey[900],
                borderRadius: BorderRadius.circular(20),
                border: Border.all(
                  color: _manualMode ? Colors.orangeAccent : Colors.white24,
                ),
              ),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(
                  _manualMode ? Icons.edit : Icons.edit_outlined,
                  size: 14,
                  color: _manualMode ? Colors.orangeAccent : Colors.white38,
                ),
                const SizedBox(width: 6),
                Text(
                  _manualMode ? 'MANUAL MODE ON' : 'SWITCH TO MANUAL ENTRY',
                  style: TextStyle(
                    color: _manualMode ? Colors.orangeAccent : Colors.white38,
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 0.8,
                  ),
                ),
              ]),
            ),
          ),

          // Manual input fields — only visible when _manualMode is true
          if (_manualMode) ...[
            const SizedBox(height: 20),

            // ── Site URL ────────────────────────────────────────────────────────
            _header('SITE URL', Icons.public),
            const SizedBox(height: 8),
            TextField(
              controller: _manualUrlCtrl,
              onChanged: (_) => setState(() {}),
              style: const TextStyle(
                color: Colors.white, fontFamily: 'Courier', fontSize: 13),
              decoration: InputDecoration(
                hintText: 'https://www.enfsolar.com/directory/installer/China',
                hintStyle: const TextStyle(color: Colors.white24),
                filled: true,
                fillColor: Colors.grey[900],
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: const BorderSide(color: Colors.white24),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: const BorderSide(color: Colors.orangeAccent),
                ),
                prefixIcon: const Icon(Icons.link, color: Colors.white38, size: 18),
                contentPadding: const EdgeInsets.symmetric(vertical: 14, horizontal: 12),
              ),
            ),

            const SizedBox(height: 20),

            // ── Element HTML ────────────────────────────────────────────────────
            _header('ELEMENT HTML', Icons.code),
            const SizedBox(height: 6),
            const Text(
              'Paste the full outerHTML of ONE example item '
              '(e.g. the <a> tag for a company name row).',
              style: TextStyle(color: Colors.white38, fontSize: 12, height: 1.4),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _manualElementCtrl,
              onChanged: (_) => setState(() {}),
              maxLines: 5,
              style: const TextStyle(
                color: Colors.greenAccent, fontFamily: 'Courier', fontSize: 12),
              decoration: InputDecoration(
                hintText:
                    '<a class="mkjs-a inline-block" href="/company/zonergy">\n'
                    '  Zonergy\n'
                    '</a>',
                hintStyle: const TextStyle(
                  color: Colors.white12, fontFamily: 'Courier', fontSize: 12),
                filled: true,
                fillColor: Colors.grey[900],
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: const BorderSide(color: Colors.white24),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: const BorderSide(color: Colors.greenAccent),
                ),
                contentPadding: const EdgeInsets.all(12),
              ),
            ),

            const SizedBox(height: 20),

            // ── Pagination HTML ─────────────────────────────────────────────────
            _header('PAGINATION BUTTON HTML', Icons.navigate_next),
            const SizedBox(height: 6),
            const Text(
              'Paste the full outerHTML of the Next / pagination button or link.',
              style: TextStyle(color: Colors.white38, fontSize: 12, height: 1.4),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _manualPaginationCtrl,
              onChanged: (_) => setState(() {}),
              maxLines: 4,
              style: const TextStyle(
                color: Colors.blueAccent, fontFamily: 'Courier', fontSize: 12),
              decoration: InputDecoration(
                hintText:
                    '<li>\n'
                    '  <a href="/directory/installer/China?page=2">2</a>\n'
                    '</li>',
                hintStyle: const TextStyle(
                  color: Colors.white12, fontFamily: 'Courier', fontSize: 12),
                filled: true,
                fillColor: Colors.grey[900],
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: const BorderSide(color: Colors.white24),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: const BorderSide(color: Colors.blueAccent),
                ),
                contentPadding: const EdgeInsets.all(12),
              ),
            ),

            const SizedBox(height: 28),

            // Confirm button — visible inline so the user never needs to scroll
            // past all three fields to find the accept button.
            // Enabled as soon as element HTML is filled (pagination is optional).
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: _manualElementCtrl.text.trim().isNotEmpty
                    ? _useSelector
                    : null,
                icon: const Icon(Icons.check_circle_outline, size: 20),
                label: Text(
                  _manualElementCtrl.text.trim().isNotEmpty
                      ? 'CONFIRM MANUAL INPUT & RETURN'
                      : 'PASTE ELEMENT HTML ABOVE TO ENABLE',
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 14,
                  ),
                ),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.orangeAccent,
                  foregroundColor: Colors.black,
                  disabledBackgroundColor: Colors.grey[850],
                  disabledForegroundColor: Colors.white24,
                  padding: const EdgeInsets.symmetric(vertical: 18),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
              ),
            ),

            // Inline cancel so the user doesn't need to scroll to abort
            const SizedBox(height: 6),
            Center(
              child: TextButton(
                onPressed: () => Navigator.pop(context, null),
                child: const Text(
                  'CANCEL',
                  style: TextStyle(color: Colors.white24, fontSize: 11),
                ),
              ),
            ),
          ],

          const SizedBox(height: 32), // fixed gap replaces the elastic Spacer

          // ── Accept button ─────────────────────────────────────────────────────
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: (_manualMode
                      ? _manualElementCtrl.text.trim().isNotEmpty
                      : hasSelector)
                  ? _useSelector
                  : null,
              icon: const Icon(Icons.check_circle_outline),
              label: Text(
                // Change button label to reflect which mode is active and
                // whether enough input exists to proceed.
                _manualMode
                    ? (_manualElementCtrl.text.trim().isNotEmpty
                        ? 'USE MANUAL INPUT & RETURN'
                        : 'PASTE ELEMENT HTML ABOVE TO CONTINUE')
                    : (hasSelector
                        ? 'USE THIS ELEMENT & RETURN'
                        : 'WAITING FOR ELEMENT SELECTION…'),
                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
              ),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.greenAccent,
                foregroundColor: Colors.black,
                disabledBackgroundColor: Colors.grey[850],
                disabledForegroundColor: Colors.white24,
                padding: const EdgeInsets.symmetric(vertical: 18),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Center(
            child: TextButton(
              onPressed: () => Navigator.pop(context, null),
              child: const Text('CANCEL', style: TextStyle(color: Colors.white38, fontSize: 12)),
            ),
          ),
        ]),
      ),
    );
  }
  // ── Sub-widgets ─────────────────────────────────────────────────────────────

  Widget _lockedCard() {
    return Container(
      key: ValueKey(_liveSelector),
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.greenAccent.withValues(alpha: 0.07),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.greenAccent.withValues(alpha: 0.5)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Icon(Icons.lock, color: Colors.greenAccent, size: 15),
          const SizedBox(width: 7),
          const Text('ELEMENT LOCKED',
              style: TextStyle(color: Colors.greenAccent, fontSize: 11,
                  fontWeight: FontWeight.bold, letterSpacing: 1.1)),
          const Spacer(),
          TextButton.icon(
            onPressed: _clearLock,
            icon: const Icon(Icons.refresh, size: 13, color: Colors.white38),
            label: const Text('RE-PICK',
                style: TextStyle(color: Colors.white38, fontSize: 11)),
            style: TextButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 6),
                minimumSize: Size.zero),
          ),
        ]),
        const SizedBox(height: 10),

        const Text('CSS SELECTOR',
            style: TextStyle(color: Colors.white38, fontSize: 10,
                fontWeight: FontWeight.bold, letterSpacing: 1)),
        const SizedBox(height: 4),
        SelectableText(_liveSelector ?? '',
            style: const TextStyle(
                color: Colors.greenAccent, fontFamily: 'Courier', fontSize: 12)),

        if ((_liveHtml ?? '').isNotEmpty) ...[
          const SizedBox(height: 12),
          const Text('ELEMENT HTML',
              style: TextStyle(color: Colors.white38, fontSize: 10,
                  fontWeight: FontWeight.bold, letterSpacing: 1)),
          const SizedBox(height: 4),
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.black,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.white12),
            ),
            child: SelectableText(
              _liveHtml!.length > 400
                  ? '${_liveHtml!.substring(0, 400)}…'
                  : _liveHtml!,
              style: const TextStyle(
                  color: Colors.white60, fontFamily: 'Courier',
                  fontSize: 11, height: 1.4),
            ),
          ),
        ],
      ]),
    );
  }

  Widget _waitingCard() {
    return Container(
      key: const ValueKey('waiting'),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 16),
      decoration: BoxDecoration(
        color: Colors.grey[900],
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white12),
      ),
      child: Row(children: [
        SizedBox(width: 18, height: 18,
            child: CircularProgressIndicator(strokeWidth: 2,
                color: Colors.white.withValues(alpha: 0.25))),
        const SizedBox(width: 14),
        const Expanded(child: Text(
          'Hover & click an element in the inspector window…',
          style: TextStyle(color: Colors.white38, fontSize: 13),
        )),
      ]),
    );
  }

  Widget _step(String n, String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          width: 22, height: 22, alignment: Alignment.center,
          decoration: BoxDecoration(
              color: Colors.greenAccent.withValues(alpha: 0.12),
              shape: BoxShape.circle,
              border: Border.all(color: Colors.greenAccent.withValues(alpha: 0.4))),
          child: Text(n, style: const TextStyle(color: Colors.greenAccent,
              fontSize: 11, fontWeight: FontWeight.bold)),
        ),
        const SizedBox(width: 10),
        Expanded(child: Text(text,
            style: const TextStyle(color: Colors.white60, fontSize: 13, height: 1.4))),
      ]),
    );
  }

  Widget _header(String text, IconData icon) {
    return Row(children: [
      Icon(icon, color: Colors.greenAccent, size: 16),
      const SizedBox(width: 8),
      Text(text, style: const TextStyle(color: Colors.white, fontSize: 11,
          fontWeight: FontWeight.bold, letterSpacing: 1.1)),
    ]);
  }
}