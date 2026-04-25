import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'visual_trainer.dart';
import 'results_page.dart';

// ─────────────────────────────────────────────────────────────────────────────
// Data model for a captured element selector
// ─────────────────────────────────────────────────────────────────────────────
class _CapturedSelector {
  final String label;       // e.g. "Lead container" / "Next button"
  final String selector;    // CSS selector, e.g. "div.listing-item"
  final String outerHtml;   // Raw outerHTML of the clicked element (for Groq)

  const _CapturedSelector({
    required this.label,
    required this.selector,
    this.outerHtml = '',
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Widget
// ─────────────────────────────────────────────────────────────────────────────
class ExecutionPage extends StatefulWidget {
  final String taskId;
  final String promptOrUrl;

  const ExecutionPage({
    super.key,
    required this.taskId,
    required this.promptOrUrl,
  });

  @override
  State<ExecutionPage> createState() => _ExecutionPageState();
}

class _ExecutionPageState extends State<ExecutionPage> {
  // ── Network config ──────────────────────────────────────────────────────────
  static const String _baseUrl = 'http://localhost:8000';
  static const String _apiKey  = 'jkuat_secret_2026';

  // ── Polling timers ──────────────────────────────────────────────────────────
  Timer? _statusTimer;
  Timer? _frameTimer;

  // ── Task state (driven by backend polling) ──────────────────────────────────
  String _status       = 'INITIALIZING';
  int    _leadCount    = 0;
  int    _companyCount = 0;
  List<String> _logs   = ['System: Initializing Orchestrator...'];
  String? _liveFrameBase64;

  // ── Training wizard state ────────────────────────────────────────────────────
  // Steps:  0 = tier selection
  //         1 = primary-selector capture  (open VisualTrainerPage)
  //         2 = pagination-selector capture (open VisualTrainerPage)
  //         3 = review & confirm
  int    _wizardStep    = 0;
  int    _selectedTier  = 1;
  bool   _trainingOpen  = false; // guard: prevents double-push

  // Selectors captured via VisualTrainerPage
  _CapturedSelector? _primarySelector;
  _CapturedSelector? _paginationSelector;
  _CapturedSelector? _subpageSelector;     // Tier 2 only: element to extract inside subpage
  _CapturedSelector? _lastPageSelector;    // Tier 1/2: optional last-page indicator

  // ── Start-button guard ───────────────────────────────────────────────────────
  bool _startInProgress = false;

  // ─────────────────────────────────────────────────────────────────────────
  // Lifecycle
  // ─────────────────────────────────────────────────────────────────────────

  @override
  void initState() {
    super.initState();
    _startPolling();
  }

  @override
  void dispose() {
    _statusTimer?.cancel();
    _frameTimer?.cancel();
    super.dispose();
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Polling
  // ─────────────────────────────────────────────────────────────────────────

  void _startPolling() {
    _statusTimer = Timer.periodic(
      const Duration(seconds: 2),
      (_) => _fetchStatus(),
    );
    _frameTimer = Timer.periodic(
      const Duration(milliseconds: 500),
      (_) => _fetchFrame(),
    );
  }

  void _stopPolling() {
    _statusTimer?.cancel();
    _frameTimer?.cancel();
  }

  // Suppresses timeout noise while VisualTrainerPage is open.
  bool _capturePending = false;

  Future<void> _fetchStatus() async {
    if (_capturePending) return; // don't spam while picker window is open
    try {
      final response = await http
          .get(Uri.parse('$_baseUrl/tasks/${widget.taskId}'))
          .timeout(const Duration(seconds: 5));

      if (!mounted) return;

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        final newStatus = (data['status'] as String? ?? 'INITIALIZING').toUpperCase();

        setState(() {
          _status       = newStatus;
          _leadCount    = data['lead_count']    as int? ?? 0;
          _companyCount = data['company_count'] as int? ?? 0;
          if (data['logs'] != null) {
            _logs = List<String>.from(data['logs'] as List);
          }
        });

        // When the backend signals training is needed, open VisualTrainerPage
        // once. The guard prevents re-pushing while the page is already open.
        if (newStatus == 'AWAITING_TRAINING' && !_trainingOpen) {
          _openTrainingFlow();
        }

        // Navigate away when the task finishes
        if (newStatus == 'COMPLETED') {
          _stopPolling();
          _navigateToResults();
        }
      }
    } on Exception catch (e) {
      debugPrint('Status poll error: $e');
    }
  }

  Future<void> _fetchFrame() async {
    try {
      final response = await http
          .get(Uri.parse('$_baseUrl/tasks/${widget.taskId}/frame'))
          .timeout(const Duration(seconds: 3));

      if (!mounted) return;
      if (response.statusCode == 200) {
        final frame = jsonDecode(response.body)['frame'] as String?;
        if (frame != null) setState(() => _liveFrameBase64 = frame);
      }
    } on Exception {
      // Silent – frame is best-effort
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Training flow — opens VisualTrainerPage for element capture
  // ─────────────────────────────────────────────────────────────────────────

  /// Opens the training wizard overlay and stops the live-frame timer so the
  /// static snapshot behind the wizard doesn't flicker.
  void _openTrainingFlow() {
    setState(() {
      _trainingOpen = true;
      _wizardStep   = 0;
    });
    // Keep status polling running so we stay aware of backend state,
    // but pause the frame timer – no Selenium is running yet at this stage.
    _frameTimer?.cancel();
  }

  /// Called when the user picks a tier on wizard step 0.
  void _onTierSelected(int tier) {
    setState(() {
      _selectedTier      = tier;
      _wizardStep        = 1;
      // Reset all selectors when tier changes
      _primarySelector   = null;
      _paginationSelector= null;
      _subpageSelector   = null;
      _lastPageSelector  = null;
    });
    _addLog('User: Tier $tier selected. Ready to capture primary selector.');
  }

  /// Opens VisualTrainerPage to capture ONE selector.
  /// [label] is shown in the snackbar / UI ("Lead container", "Next button").
  /// [onCapture] receives the CSS selector string when the user taps Accept.
  /// Converts a raw prompt/URL string into the best launchable URL for
  /// VisualTrainerPage. The page will let the user further edit it.
  static String _toInspectorUrl(String raw) {
    final t = raw.trim();
    if (t.startsWith('http://') || t.startsWith('https://')) return t;
    if (!t.contains(' ') && t.contains('.')) return 'https://$t';
    return 'https://www.google.com/search?q=${Uri.encodeComponent(t)}';
  }

  Future<void> _openSelectorCapture({
    required String label,
    required void Function(String selector, String outerHtml) onCapture,
  }) async {
    setState(() => _capturePending = true);

    final captured = await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => VisualTrainerPage(
          taskId: widget.taskId, // Pass the taskId
          domain: Uri.parse(widget.promptOrUrl).host, // FIX: Extract domain for the required parameter
          captureLabel: 'Target Element', // Optional: Match your UI label
          // NOTE: siteUrl and tier have been removed here because 
          // they are not in your current constructor!
        ),
      ),
    );

    if (!mounted) return;
    setState(() => _capturePending = false);

    if (captured != null && captured.isNotEmpty) {
      // Format from webview mode:  "selector|elementHtml"
      // Format from manual mode:   "selector|elementHtml||paginationHtml"
      // Split on first '|' for selector, remainder for html.
      // If the double-pipe separator is present, the caller receives the
      // pagination HTML appended — _saveRecipeAndFinish reads it below.
      final pipeIdx  = captured.indexOf('|');
      final selector = pipeIdx >= 0 ? captured.substring(0, pipeIdx) : captured;
      final rest     = pipeIdx >= 0 ? captured.substring(pipeIdx + 1) : '';

      // Check for manual-mode pagination payload ("elementHtml||paginationHtml")
      final doublePipe  = rest.indexOf('||');
      final html        = doublePipe >= 0 ? rest.substring(0, doublePipe) : rest;
      final manualPagHtml = doublePipe >= 0 ? rest.substring(doublePipe + 2) : '';

      // If manual mode sent pagination HTML and we don't yet have a pagination
      // selector captured, auto-fill it so the user doesn't have to open the
      // inspector a second time just for pagination.
      if (manualPagHtml.isNotEmpty && _paginationSelector == null) {
        final pagTagMatch   = RegExp(r'^<([a-zA-Z][a-zA-Z0-9]*)').firstMatch(manualPagHtml);
        
        // FIX: Removed 'r' prefix here to allow proper escaping of single quotes
        final pagClassMatch = RegExp('class=["\']([^"\']+)["\']').firstMatch(manualPagHtml);
        
        final pagTag        = pagTagMatch?.group(1)?.toLowerCase() ?? 'a';
        final pagClass      = pagClassMatch?.group(1)?.split(RegExp(r'\s+'))
                                  .where((c) => c.isNotEmpty).first ?? '';
        final pagSel        = pagClass.isNotEmpty ? '$pagTag.$pagClass' : pagTag;
        
        setState(() {
          _paginationSelector = _CapturedSelector(
            label:     'Pagination (from manual entry)',
            selector:  pagSel,
            outerHtml: manualPagHtml,
          );
        });
        _addLog('Auto-filled pagination from manual entry: $pagSel');
      }

      onCapture(selector, html);
    } else {
      _addLog('User: Selector capture cancelled for "$label".');
    }
  }

  /// Wizard step 1 — capture the primary (lead-data) selector.
  Future<void> _capturePrimarySelector() async {
    await _openSelectorCapture(
      label: _tier1Label(_selectedTier),
      onCapture: (sel, html) {
        setState(() {
          _primarySelector = _CapturedSelector(
            label:     _tier1Label(_selectedTier),
            selector:  sel,
            outerHtml: html,
          );
          _wizardStep = 2;
        });
        _addLog('Captured primary selector: $sel');
      },
    );
  }

  /// Wizard step 1b — Tier 2 only: capture subpage extraction element.
  Future<void> _captureSubpageSelector() async {
    await _openSelectorCapture(
      label: 'Email / lead element (inside subpage)',
      onCapture: (sel, html) {
        setState(() {
          _subpageSelector = _CapturedSelector(
            label:     'Subpage element',
            selector:  sel,
            outerHtml: html,
          );
        });
        _addLog('Captured subpage selector: $sel');
      },
    );
  }

  /// Wizard step 2b — optional: last-page indicator.
  Future<void> _captureLastPageSelector() async {
    await _openSelectorCapture(
      label: 'Last page / disabled Next indicator (optional)',
      onCapture: (sel, html) {
        setState(() {
          _lastPageSelector = _CapturedSelector(
            label:     'Last page indicator',
            selector:  sel,
            outerHtml: html,
          );
        });
        _addLog('Captured last-page selector: $sel');
      },
    );
  }

  /// Wizard step 2 — capture the pagination ("Next") selector.
  Future<void> _capturePaginationSelector() async {
    await _openSelectorCapture(
      label: 'Next / pagination button',
      onCapture: (sel, html) {
        setState(() {
          _paginationSelector = _CapturedSelector(
            label:     'Pagination',
            selector:  sel,
            outerHtml: html,
          );
          _wizardStep = 3;
        });
        _addLog('Captured pagination selector: $sel');
      },
    );
  }

  /// Wizard step 3 — POST recipe to /recipes, PATCH task to TRAINED.
  Future<void> _saveRecipeAndFinish() async {
    if (_primarySelector == null) return;

    // Resolve the full target URL — preserve path so backend has the exact page
    final targetUrl = _toInspectorUrl(widget.promptOrUrl);
    final uri       = Uri.tryParse(targetUrl);
    final domain    = (uri != null && uri.hasAuthority) ? uri.host : widget.promptOrUrl;

    // Method heuristic: Tier 1 default BS4, Tier 2/3 Selenium.
    // Will be overridden by Groq if it detects JS pagination.
    final method = _selectedTier == 1 ? 'BS4' : 'SELENIUM';

    try {
      // ── 1. Save recipe (selectors + outerHTML for every captured element) ──
      final recipeBody = jsonEncode({
        'domain':          domain,
        'pagination_type': method.toLowerCase(),
        'selectors': {
          'item_container':         _primarySelector!.selector,
          'next_button':            _paginationSelector?.selector ?? '',
          'subpage':                _subpageSelector?.selector    ?? '',
          'last_page':              _lastPageSelector?.selector   ?? '',
        },
        // Raw HTML of each clicked element — forwarded to Groq for validation
        'element_html': {
          'primary':    _primarySelector!.outerHtml,
          'pagination': _paginationSelector?.outerHtml ?? '',
          'subpage':    _subpageSelector?.outerHtml    ?? '',
          'last_page':  _lastPageSelector?.outerHtml   ?? '',
        },
        'site_url':  targetUrl,
        'tier':      _selectedTier,
        'max_pages': 10,
      });

      final recipeResp = await http.post(
        Uri.parse('$_baseUrl/recipes'),
        headers: {'X-API-KEY': _apiKey, 'Content-Type': 'application/json'},
        body: recipeBody,
      );

      if (recipeResp.statusCode != 200) {
        _addLog('Error: Recipe save failed (${recipeResp.statusCode}).');
        return;
      }

      // ── 2. Signal backend that training is complete ─────────────────────────
      await http.patch(
        Uri.parse('$_baseUrl/tasks/${widget.taskId}/status'),
        headers: {'X-API-KEY': _apiKey, 'Content-Type': 'application/json'},
        body: jsonEncode({'status': 'TRAINED'}),
      );

      if (!mounted) return;

      setState(() {
        _trainingOpen = false;
        _status       = 'TRAINED';
        _wizardStep   = 0;
      });

      _addLog('System: Recipe saved. Tier $_selectedTier engine ready. Press START.');

    } on Exception catch (e) {
      _addLog('Error saving recipe: $e');
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Extraction start
  // ─────────────────────────────────────────────────────────────────────────

  Future<void> _startSystem() async {
    if (_startInProgress) return;
    setState(() => _startInProgress = true);
    _addLog('User: START command issued.');

    final targetUrl = _toInspectorUrl(widget.promptOrUrl);

    // Full recipe sent to /tasks/{id}/start — includes outerHTML for Groq
    final recipe = {
      'tier':               _selectedTier,
      'site_url':           targetUrl,
      'primary_selector':   _primarySelector?.selector    ?? '',
      'pagination_selector':_paginationSelector?.selector ?? '',
      'subpage_selector':   _subpageSelector?.selector    ?? '',
      'last_page_selector': _lastPageSelector?.selector   ?? '',
      'method':             _selectedTier == 1 ? 'BS4' : 'SELENIUM',
      'max_pages':          10,
      // outerHTML of every captured element — used by Groq to validate selectors
      'element_html': {
        'primary':    _primarySelector?.outerHtml    ?? '',
        'pagination': _paginationSelector?.outerHtml ?? '',
        'subpage':    _subpageSelector?.outerHtml    ?? '',
        'last_page':  _lastPageSelector?.outerHtml   ?? '',
      },
    };

    try {
      final response = await http.post(
        Uri.parse('$_baseUrl/tasks/${widget.taskId}/start'),
        headers: {'X-API-KEY': _apiKey, 'Content-Type': 'application/json'},
        body: jsonEncode(recipe),
      );

      if (!mounted) return;

      if (response.statusCode == 200) {
        setState(() => _status = 'EXTRACTING');
        _addLog('System: Extraction engine started (Tier $_selectedTier).');
        // Resume frame polling now that Selenium is running on the backend.
        _frameTimer = Timer.periodic(
          const Duration(milliseconds: 500),
          (_) => _fetchFrame(),
        );
      } else {
        _addLog('Error: START failed (${response.statusCode}): ${response.body}');
        setState(() => _startInProgress = false);
      }
    } on Exception catch (e) {
      _addLog('Error: $e');
      setState(() => _startInProgress = false);
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Navigation
  // ─────────────────────────────────────────────────────────────────────────

  void _navigateToResults() {
    if (!mounted) return;
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(
        builder: (_) => ResultsPage(
          taskId:   widget.taskId,
          taskName: widget.promptOrUrl,
        ),
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Helpers
  // ─────────────────────────────────────────────────────────────────────────

  void _addLog(String message) {
    if (!mounted) return;
    setState(() => _logs.add(message));
  }

  String _tier1Label(int tier) {
    switch (tier) {
      case 1: return 'Email / lead element';
      case 2: return 'Subpage link element';
      case 3: return 'Company name element';
      default: return 'Lead element';
    }
  }

  bool get _canStart =>
      (_status == 'TRAINED' || _status == 'READY') && !_startInProgress;

  Color get _statusColor {
    switch (_status) {
      case 'COMPLETED':        return Colors.greenAccent;
      case 'EXTRACTING':       return Colors.orangeAccent;
      case 'AWAITING_TRAINING':return Colors.purpleAccent;
      case 'TRAINED':          return Colors.lightBlueAccent;
      case 'FAILED':           return Colors.redAccent;
      default:                 return Colors.white54;
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Build
  // ─────────────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Row(
        children: [
          // ── LEFT: live preview + training wizard ───────────────────────────
          Expanded(
            flex: 3,
            child: Container(
              margin: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: Colors.grey[900],
                borderRadius: BorderRadius.circular(30),
                border: Border.all(color: Colors.white10),
              ),
              child: Stack(
                fit: StackFit.expand,
                children: [
                  // Background: live Selenium screenshot feed
                  ClipRRect(
                    borderRadius: BorderRadius.circular(30),
                    child: _liveFrameBase64 != null
                        ? Image.memory(
                            base64Decode(_liveFrameBase64!),
                            fit: BoxFit.cover,
                            gaplessPlayback: true,
                          )
                        : const Center(
                            child: CircularProgressIndicator(
                              color: Colors.white24,
                            ),
                          ),
                  ),

                  // Training wizard overlay — only while AWAITING_TRAINING
                  if (_trainingOpen) _buildTrainingWizard(),

                  // Top label
                  Positioned(
                    top: 20,
                    left: 20,
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 15, vertical: 8),
                      decoration: BoxDecoration(
                        color: Colors.black54,
                        borderRadius: BorderRadius.circular(15),
                      ),
                      child: Text(
                        'LIVE INSTANCE: ${widget.promptOrUrl}',
                        style: const TextStyle(
                            color: Colors.white, fontSize: 12),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),

          // ── RIGHT: controls + logs ─────────────────────────────────────────
          Expanded(
            flex: 2,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(0, 20, 20, 20),
              child: Column(
                children: [
                  _buildStatusCard(),
                  const SizedBox(height: 20),
                  _buildLogConsole(),
                  const SizedBox(height: 20),
                  _buildStartButton(),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Widget builders
  // ─────────────────────────────────────────────────────────────────────────

  /// Status card — lead + company counters and current status badge.
  Widget _buildStatusCard() {
    return Container(
      padding: const EdgeInsets.all(25),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(30),
      ),
      child: Column(
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              _statTile('LEADS',     _leadCount.toString(),    Colors.green),
              _statTile('COMPANIES', _companyCount.toString(), Colors.blue),
              _statTile('TIER',      _selectedTier.toString(), Colors.purple),
            ],
          ),
          const Divider(height: 40),
          Row(
            children: [
              Icon(Icons.radar, color: _statusColor, size: 20),
              const SizedBox(width: 10),
              Flexible(
                child: Text(
                  'STATUS: $_status',
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.2,
                    color: _status == 'FAILED' ? Colors.red : Colors.black,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _statTile(String label, String value, Color color) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: TextStyle(
            color: Colors.grey[600],
            fontSize: 10,
            fontWeight: FontWeight.bold,
          ),
        ),
        Text(
          value,
          style: TextStyle(
            fontSize: 32,
            fontWeight: FontWeight.bold,
            color: color,
          ),
        ),
      ],
    );
  }

  /// Scrollable log console.
  Widget _buildLogConsole() {
    final scrollController = ScrollController();
    // Auto-scroll to bottom whenever logs update.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (scrollController.hasClients) {
        scrollController.animateTo(
          scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });

    return Expanded(
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: Colors.grey[900],
          borderRadius: BorderRadius.circular(30),
        ),
        child: ListView.builder(
          controller: scrollController,
          itemCount: _logs.length,
          itemBuilder: (_, i) => Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text(
              '> ${_logs[i]}',
              style: const TextStyle(
                color: Colors.greenAccent,
                fontFamily: 'Courier',
                fontSize: 12,
              ),
            ),
          ),
        ),
      ),
    );
  }

  /// START button — active only when status is TRAINED or READY.
  Widget _buildStartButton() {
    return SizedBox(
      width: double.infinity,
      height: 80,
      child: ElevatedButton(
        onPressed: _canStart ? _startSystem : null,
        style: ElevatedButton.styleFrom(
          backgroundColor: Colors.greenAccent,
          foregroundColor: Colors.black,
          disabledBackgroundColor: Colors.grey[800],
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(25),
          ),
        ),
        child: _startInProgress
            ? const SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(
                  color: Colors.black,
                  strokeWidth: 2.5,
                ),
              )
            : const Text(
                'START EXTRACTION SYSTEM',
                style: TextStyle(
                  fontWeight: FontWeight.bold,
                  fontSize: 18,
                ),
              ),
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Training wizard
  // ─────────────────────────────────────────────────────────────────────────

  Widget _buildTrainingWizard() {
    return Container(
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.92),
        borderRadius: BorderRadius.circular(30),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 40, vertical: 32),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.psychology, color: Colors.greenAccent, size: 56),
            const SizedBox(height: 16),

            // ── Step indicator ──────────────────────────────────────────────
            _buildStepIndicator(),
            const SizedBox(height: 28),

            // ── Step content ────────────────────────────────────────────────
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 250),
              child: KeyedSubtree(
                key: ValueKey(_wizardStep),
                child: _buildWizardStep(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStepIndicator() {
    const steps = ['Tier', 'Primary', 'Pagination', 'Confirm'];
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(steps.length, (i) {
        final active   = i == _wizardStep;
        final complete = i < _wizardStep;
        return Row(
          children: [
            AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              width:  active ? 32 : 10,
              height: 10,
              decoration: BoxDecoration(
                color: complete
                    ? Colors.greenAccent
                    : active
                        ? Colors.white
                        : Colors.white24,
                borderRadius: BorderRadius.circular(5),
              ),
            ),
            if (i < steps.length - 1)
              Container(
                width: 20, height: 1,
                color: complete ? Colors.greenAccent : Colors.white24,
                margin: const EdgeInsets.symmetric(horizontal: 4),
              ),
          ],
        );
      }),
    );
  }

  Widget _buildWizardStep() {
    switch (_wizardStep) {
      // ── Step 0: choose extraction tier ───────────────────────────────────
      case 0:
        return _buildStep(
          title: 'TRAINING: WHERE ARE THE LEADS?',
          subtitle: 'Choose the extraction tier that matches this site.',
          children: [
            _buildTierCard(
              tier:     1,
              icon:     Icons.format_list_bulleted,
              title:    'Tier 1 — Emails on main page',
              subtitle: 'Emails or contact info are directly visible in the listing.',
            ),
            const SizedBox(height: 12),
            _buildTierCard(
              tier:     2,
              icon:     Icons.open_in_new,
              title:    'Tier 2 — Emails inside subpages',
              subtitle: 'Each listing row links to a detail page that has the email.',
            ),
            const SizedBox(height: 12),
            _buildTierCard(
              tier:     3,
              icon:     Icons.business,
              title:    'Tier 3 — Only company names visible',
              subtitle: 'No emails shown; names will be searched via Serper.',
            ),
          ],
        );

      // ── Step 1: capture primary selector ─────────────────────────────────
      case 1:
        return _buildStep(
          title: 'CAPTURE: ${_tier1Label(_selectedTier).toUpperCase()}',
          subtitle: _selectedTier == 2
              ? 'Click the element on the MAIN page that links to each company subpage.'
              : 'Click the element that contains the data you want to extract.',
          children: [
            if (_primarySelector != null)
              _buildCapturedBadge(_primarySelector!),
            const SizedBox(height: 16),
            _wizardButton(
              label: _primarySelector == null ? 'OPEN INSPECTOR' : 'RE-CAPTURE',
              icon:  Icons.ads_click,
              color: Colors.white,
              onTap: _capturePrimarySelector,
            ),

            // Tier 2 only: also capture the subpage extraction element here
            if (_selectedTier == 2) ...[
              const SizedBox(height: 20),
              const Divider(color: Colors.white12),
              const SizedBox(height: 8),
              const Text(
                'STEP 1B — SUBPAGE ELEMENT',
                style: TextStyle(
                  color: Colors.white38, fontSize: 10,
                  fontWeight: FontWeight.bold, letterSpacing: 1.2,
                ),
              ),
              const SizedBox(height: 4),
              const Text(
                'Open the inspector, navigate to a subpage, then click '
                'the element that holds the email or lead data.',
                style: TextStyle(color: Colors.white54, fontSize: 12, height: 1.4),
              ),
              const SizedBox(height: 10),
              if (_subpageSelector != null)
                _buildCapturedBadge(_subpageSelector!),
              const SizedBox(height: 8),
              _wizardButton(
                label: _subpageSelector == null
                    ? 'OPEN INSPECTOR (SUBPAGE)'
                    : 'RE-CAPTURE SUBPAGE',
                icon:  Icons.open_in_new,
                color: Colors.blueAccent,
                onTap: _captureSubpageSelector,
              ),
            ],

            if (_primarySelector != null &&
                (_selectedTier != 2 || _subpageSelector != null)) ...[
              const SizedBox(height: 12),
              _wizardButton(
                label: 'NEXT: CAPTURE PAGINATION →',
                icon:  Icons.arrow_forward,
                color: Colors.greenAccent,
                onTap: () => setState(() => _wizardStep = 2),
              ),
            ],
          ],
        );

      // ── Step 2: capture pagination selector + optional last-page indicator ──
      case 2:
        return _buildStep(
          title: 'CAPTURE: NEXT / PAGINATION BUTTON',
          subtitle: 'Click the Next page button. Then optionally click the disabled/last-page indicator.',
          children: [
            if (_paginationSelector != null)
              _buildCapturedBadge(_paginationSelector!),
            const SizedBox(height: 16),
            _wizardButton(
              label: _paginationSelector == null ? 'OPEN INSPECTOR' : 'RE-CAPTURE',
              icon:  Icons.ads_click,
              color: Colors.white,
              onTap: _capturePaginationSelector,
            ),
            const SizedBox(height: 12),
            _wizardButton(
              label: 'SKIP (single-page site)',
              icon:  Icons.skip_next,
              color: Colors.white38,
              onTap: () => setState(() {
                _paginationSelector = const _CapturedSelector(
                  label: 'Pagination', selector: 'a.next',
                );
                _wizardStep = 3;
              }),
            ),
            if (_paginationSelector != null) ...[
              const SizedBox(height: 20),
              const Divider(color: Colors.white12),
              const SizedBox(height: 8),
              const Text(
                'LAST-PAGE INDICATOR (OPTIONAL)',
                style: TextStyle(
                  color: Colors.white38, fontSize: 10,
                  fontWeight: FontWeight.bold, letterSpacing: 1.2,
                ),
              ),
              const SizedBox(height: 4),
              const Text(
                'Click the element that appears when you are on the last page '
                '(e.g. a disabled "Next" button). Skip if none.',
                style: TextStyle(color: Colors.white54, fontSize: 12),
              ),
              const SizedBox(height: 10),
              if (_lastPageSelector != null)
                _buildCapturedBadge(_lastPageSelector!),
              const SizedBox(height: 8),
              _wizardButton(
                label: _lastPageSelector == null
                    ? 'CAPTURE LAST-PAGE INDICATOR'
                    : 'RE-CAPTURE',
                icon:  Icons.last_page,
                color: Colors.orangeAccent,
                onTap: _captureLastPageSelector,
              ),
              const SizedBox(height: 12),
              _wizardButton(
                label: 'NEXT: REVIEW RECIPE →',
                icon:  Icons.arrow_forward,
                color: Colors.greenAccent,
                onTap: () => setState(() => _wizardStep = 3),
              ),
            ],
          ],
        );

      // ── Step 3: review + save ─────────────────────────────────────────────
      case 3:
        return _buildStep(
          title: 'CONFIRM RECIPE',
          subtitle: 'Review your selections before saving.',
          children: [
            _buildRecipeReviewRow('Tier',       'Tier $_selectedTier'),
            _buildRecipeReviewRow(
              'Primary',
              _primarySelector?.selector ?? '—',
            ),
            _buildRecipeReviewRow(
              'Pagination',
              _paginationSelector?.selector ?? 'a.next (default)',
            ),
            _buildRecipeReviewRow(
              'Method',
              _selectedTier == 1 ? 'BS4 (fast)' : 'Selenium (JS)',
            ),
            const SizedBox(height: 24),
            _wizardButton(
              label: 'SAVE RECIPE & ENABLE START',
              icon:  Icons.save_alt,
              color: Colors.greenAccent,
              onTap: _saveRecipeAndFinish,
            ),
            const SizedBox(height: 12),
            _wizardButton(
              label: '← BACK',
              icon:  Icons.arrow_back,
              color: Colors.white24,
              onTap: () => setState(() => _wizardStep = 2),
            ),
          ],
        );

      default:
        return const SizedBox.shrink();
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Wizard sub-widgets
  // ─────────────────────────────────────────────────────────────────────────

  Widget _buildStep({
    required String title,
    required String subtitle,
    required List<Widget> children,
  }) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          title,
          textAlign: TextAlign.center,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 18,
            fontWeight: FontWeight.bold,
            letterSpacing: 1,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          subtitle,
          textAlign: TextAlign.center,
          style: const TextStyle(color: Colors.white60, fontSize: 13),
        ),
        const SizedBox(height: 24),
        ...children,
      ],
    );
  }

  Widget _buildTierCard({
    required int tier,
    required IconData icon,
    required String title,
    required String subtitle,
  }) {
    final selected = _selectedTier == tier;
    return GestureDetector(
      onTap: () => _onTierSelected(tier),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        decoration: BoxDecoration(
          color: selected ? Colors.greenAccent.withValues(alpha: 0.15) : Colors.white.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: selected ? Colors.greenAccent : Colors.white24,
            width: selected ? 1.5 : 1,
          ),
        ),
        child: Row(
          children: [
            Icon(icon, color: selected ? Colors.greenAccent : Colors.white54, size: 28),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: TextStyle(
                      color: selected ? Colors.greenAccent : Colors.white,
                      fontWeight: FontWeight.bold,
                      fontSize: 13,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    subtitle,
                    style: const TextStyle(color: Colors.white54, fontSize: 11),
                  ),
                ],
              ),
            ),
            if (selected)
              const Icon(Icons.check_circle, color: Colors.greenAccent, size: 20),
          ],
        ),
      ),
    );
  }

  Widget _buildCapturedBadge(_CapturedSelector sel) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      decoration: BoxDecoration(
        color: Colors.greenAccent.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.greenAccent.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          const Icon(Icons.check, color: Colors.greenAccent, size: 16),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              sel.selector,
              style: const TextStyle(
                color: Colors.greenAccent,
                fontFamily: 'Courier',
                fontSize: 12,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRecipeReviewRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 90,
            child: Text(
              label,
              style: const TextStyle(
                color: Colors.white54,
                fontSize: 12,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 12,
                fontFamily: 'Courier',
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }

  Widget _wizardButton({
    required String label,
    required IconData icon,
    required Color color,
    required VoidCallback onTap,
  }) {
    return SizedBox(
      width: double.infinity,
      child: ElevatedButton.icon(
        onPressed: onTap,
        icon: Icon(icon, size: 16),
        label: Text(label, style: const TextStyle(fontSize: 13)),
        style: ElevatedButton.styleFrom(
          backgroundColor: color.withValues(alpha: 0.15),
          foregroundColor: color,
          side: BorderSide(color: color.withValues(alpha: 0.4)),
          padding: const EdgeInsets.symmetric(vertical: 14),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      ),
    );
  }
}